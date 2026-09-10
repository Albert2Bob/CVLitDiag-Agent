"""阶段 4 使用确定性 Embedding 和重排器，绝不访问网络。"""

import asyncio
import hashlib
import time
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.output_validation import validate_answer
from backend.app.rag.chunking import chunk_document
from backend.app.rag.evaluation import evaluate
from backend.app.rag.extractors import extract_csv, extract_json, extract_markdown, extract_pdf
from backend.app.rag.fusion import rrf_fuse
from backend.app.rag.query import normalize_query
from backend.app.rag.reranker import DeterministicReranker, rerank
from backend.app.rag.retrieval import RetrievalService, RetrievalUnavailable, evidence_id
from backend.app.rag.schemas import ExtractedUnit, ExtractionResult, RetrievalCandidate, SearchArguments
from backend.app.storage import Store
from backend.app.tool_executor import RunContext, ToolExecutor


def settings(tmp_path, **kwargs):
    return Settings(
        _env_file=None,
        database_path=str(tmp_path / "phase4.db"),
        document_storage_path=str(tmp_path / "documents"),
        embedding_provider="deterministic",
        embedding_model="test-hash",
        reranker_provider="deterministic",
        **kwargs,
    )


def pdf_bytes(text="第一页可检索内容", second="第二页指标 AP 42.1"):
    doc = pymupdf.open()
    for value in (text, second):
        page = doc.new_page()
        if value:
            page.insert_text((72, 72), value, fontname="china-s")
    data = doc.tobytes()
    doc.close()
    return data


def wait_document(client, document_id):
    for _ in range(200):
        item = client.get(f"/api/documents/{document_id}").json()
        if item["parse_status"] in {"ready", "failed", "unsupported"}:
            return item
        time.sleep(0.01)
    raise AssertionError("文档处理未进入终态")


@pytest.mark.parametrize(
    "filename,mime,content",
    [
        ("paper.md", "text/markdown", b"# Method\n\nResNet uses residual blocks."),
        ("notes.txt", "text/plain", "目标检测使用边界框。".encode()),
        ("metrics.csv", "text/csv", b"model,AP\nResNet,42.1\nViT,43.2"),
        ("config.json", "application/json", b'{"model":{"name":"ResNet","depth":50}}'),
        ("paper.pdf", "application/pdf", pdf_bytes()),
    ],
)
def test_supported_uploads_reach_ready_and_restore_status(tmp_path, filename, mime, content):
    cfg = settings(tmp_path)
    with TestClient(create_app(cfg)) as client:
        project_id = client.get("/api/projects").json()[0]["project_id"]
        response = client.post(
            f"/api/projects/{project_id}/documents", files={"file": (filename, content, mime)}
        )
        assert response.status_code == 202
        item = wait_document(client, response.json()["document_id"])
        assert item["parse_status"] == "ready"
        assert [event["type"] for event in item["events"]] == [
            "document_uploaded",
            "document_parsing_started",
            "document_parsing_finished",
            "document_indexing_started",
            "document_indexing_finished",
        ]
        assert client.get(f"/api/projects/{project_id}/documents").status_code == 200


def test_scanned_pdf_and_upload_validation(tmp_path):
    cfg = settings(tmp_path, max_upload_bytes=5000)
    with TestClient(create_app(cfg)) as client:
        project_id = client.get("/api/projects").json()[0]["project_id"]
        empty = client.post(
            f"/api/projects/{project_id}/documents",
            files={"file": ("scan.pdf", pdf_bytes("", ""), "application/pdf")},
        )
        assert wait_document(client, empty.json()["document_id"])["parse_status"] == "unsupported"
        for name, body, mime, status in [
            ("bad.exe", b"x", "application/octet-stream", 415),
            ("fake.pdf", b"plain", "application/pdf", 415),
            ("fake.txt", b"%PDF-1.7", "text/plain", 415),
            ("large.txt", b"x" * 5001, "text/plain", 413),
            ("bad.txt", b"x", "image/png", 415),
        ]:
            response = client.post(
                f"/api/projects/{project_id}/documents", files={"file": (name, body, mime)}
            )
            assert response.status_code == status


def test_filename_boundary_duplicate_and_delete(tmp_path):
    cfg = settings(tmp_path)
    with TestClient(create_app(cfg)) as client:
        project_id = client.get("/api/projects").json()[0]["project_id"]
        files = {"file": ("../../notes.txt", b"safe unique content", "text/plain")}
        first = client.post(f"/api/projects/{project_id}/documents", files=files)
        assert first.status_code == 202
        document_id = first.json()["document_id"]
        wait_document(client, document_id)
        row = client.app.state.store.document(document_id, internal=True)
        target = (Path(cfg.document_storage_path).resolve() / row["storage_key"]).resolve()
        assert Path(cfg.document_storage_path).resolve() in target.parents
        assert client.post(f"/api/projects/{project_id}/documents", files=files).status_code == 409
        assert client.delete(f"/api/documents/{document_id}").status_code == 204
        assert not target.exists()
        assert client.get(f"/api/documents/{document_id}").status_code == 403


def test_extractors_preserve_locations_and_pdf_pages(tmp_path):
    markdown = extract_markdown("# 一级\n正文\n## 二级\n更多".encode(), max_chars=1000)
    assert [unit.section for unit in markdown.units] == ["一级", "一级 > 二级"]
    csv_result = extract_csv(b"name,value\na,1\nb,2", max_chars=1000)
    assert csv_result.units[0].locator == "rows 2-3"
    json_result = extract_json(b'{"model":{"layers":[18,34]}}', max_chars=1000)
    assert [unit.locator for unit in json_result.units] == ["$.model.layers[0]", "$.model.layers[1]"]
    path = tmp_path / "paper.pdf"
    path.write_bytes(pdf_bytes())
    result = extract_pdf(path, max_pages=10, max_chars=10000)
    assert [unit.page_start for unit in result.units] == [1, 2]

    section_path = tmp_path / "section.pdf"
    section_path.write_bytes(pdf_bytes("METHODS\nResidual blocks are evaluated.", "RESULTS\nAP is 42.1."))
    section_result = extract_pdf(section_path, max_pages=10, max_chars=10000)
    assert [unit.section for unit in section_result.units] == ["METHODS", "RESULTS"]


def test_chunk_ids_are_stable_and_change_with_strategy():
    result = ExtractionResult(
        units=[ExtractedUnit(content="A paragraph. " * 100, page_start=1, page_end=1)],
        page_count=1,
        parse_quality="high",
        extractor_name="test",
        extractor_version="1",
    )
    kwargs = dict(document_id="document_x", document_version=1, project_id="project_x", access_scope="project", size=300, overlap=30, max_chunks=100)
    first = chunk_document(result, **kwargs)
    assert [item.chunk_id for item in first] == [item.chunk_id for item in chunk_document(result, **kwargs)]
    changed = chunk_document(result, **{**kwargs, "size": 320})
    assert [item.chunk_id for item in first] != [item.chunk_id for item in changed]
    assert all(item.page_number == 1 for item in first)


def candidate(chunk_id, content, rank, source="bm25", document_id="document_x"):
    from backend.app.rag.schemas import DocumentChunk

    chunk = DocumentChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        document_version=1,
        project_id="project_x",
        chunk_index=rank,
        content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        token_count=1,
        created_at="2026-01-01T00:00:00+00:00",
    )
    return RetrievalCandidate(chunk=chunk, retrieval_sources=[source], source_ranks={source: rank})


def test_rrf_uses_ranks_deduplicates_and_sorts_stably():
    a = candidate("chunk_a", "ResNet exact evidence", 1)
    duplicate = candidate("chunk_a", "ResNet exact evidence", 2, "vector")
    b = candidate("chunk_b", "different content", 1, "vector")
    fused = rrf_fuse([[a], [b, duplicate]], k=60)
    assert fused[0].chunk.chunk_id == "chunk_a"
    assert fused[0].retrieval_sources == ["bm25", "vector"]
    assert fused[0].fused_score == pytest.approx(1 / 61 + 1 / 62)
    assert [item.fused_rank for item in fused] == [1, 2]
    repeated_source = rrf_fuse(
        [[candidate("chunk_c", "same", 4)], [candidate("chunk_c", "same", 1)]], k=60
    )
    assert repeated_source[0].fused_score == pytest.approx(1 / 61)
    cross_document = rrf_fuse(
        [
            [candidate("chunk_d", "identical evidence", 1, document_id="document_a")],
            [candidate("chunk_e", "identical evidence", 1, "vector", "document_b")],
        ]
    )
    assert {item.chunk.document_id for item in cross_document} == {"document_a", "document_b"}


async def test_reranker_changes_order_and_falls_back():
    items = [candidate("chunk_a", "unrelated", 1), candidate("chunk_b", "ResNet", 2)]
    ranked, degraded = await rerank("ResNet", items, DeterministicReranker(), 2, 1)
    assert ranked[0].chunk.chunk_id == "chunk_b" and not degraded

    class Broken:
        async def score(self, query, texts):
            raise RuntimeError

    fallback, degraded = await rerank("ResNet", items, Broken(), 2, 1)
    assert fallback == items and degraded


async def test_three_routes_are_concurrent_and_all_failure_is_clear(tmp_path):
    store = Store(":memory:")
    project_id = store.list_projects()[0]["project_id"]
    thread_id = store.create_thread(project_id)["thread_id"]
    run_id = store.create_run(thread_id, project_id, "question")["run_id"]
    context = RunContext(store.user_id, project_id, thread_id, run_id, store, question="question")

    class Slow:
        async def search(self, *args):
            await asyncio.sleep(0.05)
            return []

    cfg = settings(tmp_path)
    service = RetrievalService(store, Slow(), Slow(), Slow(), DeterministicReranker(), cfg)
    started = time.perf_counter()
    result = await service.search(SearchArguments(query="question", project_id=project_id), context, lambda *args: asyncio.sleep(0))
    assert time.perf_counter() - started < 0.12
    assert result.evidence == []

    class Broken:
        async def search(self, *args):
            raise RuntimeError

    degraded_service = RetrievalService(store, Broken(), Slow(), Slow(), DeterministicReranker(), cfg)
    degraded = await degraded_service.search(
        SearchArguments(query="question", project_id=project_id),
        context,
        lambda *args: asyncio.sleep(0),
    )
    assert degraded.degraded_sources == ["bm25"]

    service = RetrievalService(store, Broken(), Broken(), Broken(), DeterministicReranker(), cfg)
    failed_events = []

    async def capture(kind, payload):
        failed_events.append((kind, payload))

    with pytest.raises(RetrievalUnavailable):
        await service.search(
            SearchArguments(query="question", project_id=project_id), context, capture
        )
    started_event = next(payload for kind, payload in failed_events if kind == "retrieval_started")
    finished_event = next(payload for kind, payload in failed_events if kind == "retrieval_finished")
    assert finished_event["retrieval_id"] == started_event["retrieval_id"]
    assert finished_event["status"] == "failed"
    store.db.close()


def test_query_expansion_and_evidence_validation():
    values = normalize_query("残差网络的 AP 是多少？")
    assert values[0] == "残差网络的 AP 是多少？"
    assert any("ResNet" in value for value in values)
    first = evidence_id("run_x", "project_x", "chunk_x", 1)
    assert first == evidence_id("run_x", "project_x", "chunk_x", 1)
    assert first != evidence_id("run_x", "project_y", "chunk_x", 1)
    answer = {"status": "complete", "summary": "有证据", "claims": [{"statement": "结论", "evidence_ids": [first]}]}
    assert validate_answer(answer, {first}).claims[0].evidence_ids == [first]
    with pytest.raises(ValueError):
        validate_answer(answer, set())


def test_evidence_selection_preserves_comparison_coverage_and_neighbor_boundary(tmp_path):
    ranked = [
        candidate("chunk_a1", "shared term a", 1, document_id="document_a"),
        candidate("chunk_a2", "shared term b", 2, document_id="document_a"),
        candidate("chunk_b1", "shared term c", 3, document_id="document_b"),
    ]
    ranked = [item.model_copy(update={"rerank_score": 1 - index / 10}) for index, item in enumerate(ranked)]

    class BoundaryStore:
        def adjacent_chunk(self, chunk, offset):
            return candidate("chunk_foreign", "foreign", 4, document_id="document_b").chunk

    context = RunContext("user", "project_x", "thread", "run", BoundaryStore())
    limited = settings(tmp_path, evidence_per_document=1, evidence_top_k=3)
    service = RetrievalService(None, None, None, None, DeterministicReranker(), limited)
    selected = service._select(ranked, 3, True, context)
    assert {item.chunk.document_id for item in selected} == {"document_a", "document_b"}
    assert len(selected) == 2

    neighbor_cfg = settings(tmp_path, evidence_per_document=2, evidence_top_k=2)
    neighbor_service = RetrievalService(None, None, None, None, DeterministicReranker(), neighbor_cfg)
    selected = neighbor_service._select(ranked[:1], 2, False, context)
    assert [item.chunk.chunk_id for item in selected] == ["chunk_a1"]


async def test_tool_retrieval_round_limit_and_forged_documents(tmp_path):
    store = Store(":memory:")
    project_id = store.list_projects()[0]["project_id"]
    other = store.create_project("其他")["project_id"]
    thread_id = store.create_thread(project_id)["thread_id"]
    run_id = store.create_run(thread_id, project_id, "原问题")["run_id"]

    class Search:
        async def search(self, args, context, emit):
            from backend.app.rag.schemas import SearchResult

            return SearchResult(query=args.query, normalized_queries=[args.query], evidence=[], retrieval_summary={})

    context = RunContext(store.user_id, project_id, thread_id, run_id, store, question="原问题", retrieval_service=Search())
    executor = ToolExecutor(context, lambda *args: asyncio.sleep(0))
    from backend.app.schemas import ToolCallRequest

    async def call(arguments, index):
        return await executor.execute(ToolCallRequest(tool_name="search_project_documents", arguments=arguments, tool_call_id=f"call_{index}"))

    assert (await call({"query": "改写", "project_id": project_id}, 0)).ok is False
    assert (await call({"query": "原问题", "project_id": project_id}, 1)).ok
    assert not (await call({"query": "补充", "project_id": project_id}, 2)).ok
    assert (await call({"query": "补充", "project_id": project_id, "missing_information": ["缺口"]}, 3)).ok
    assert not (await call({"query": "再次", "project_id": project_id, "missing_information": ["缺口"]}, 4)).ok
    forged = await call({"query": "原问题", "project_id": project_id, "document_ids": [other + "_demo"]}, 5)
    assert not forged.ok
    store.db.close()


def test_real_index_three_route_retrieval_persists_evidence(tmp_path):
    cfg = settings(tmp_path)
    with TestClient(create_app(cfg)) as client:
        store = client.app.state.store
        project_id = store.list_projects()[0]["project_id"]
        response = client.post(
            f"/api/projects/{project_id}/documents",
            files={
                "file": (
                    "resnet.md",
                    b"# Method\n\nResNet residual connection computes Fx plus x.",
                    "text/markdown",
                )
            },
        )
        document_id = response.json()["document_id"]
        assert wait_document(client, document_id)["parse_status"] == "ready"
        thread_id = store.create_thread(project_id)["thread_id"]
        run_id = store.create_run(thread_id, project_id, "ResNet residual connection")["run_id"]
        context = RunContext(
            store.user_id,
            project_id,
            thread_id,
            run_id,
            store,
            question="ResNet residual connection",
        )
        events = []

        async def execute():
            async def emit(kind, payload):
                events.append((kind, payload))

            return await client.app.state.runner.retrieval_service.search(
                SearchArguments(query="ResNet residual connection", project_id=project_id),
                context,
                emit,
            )

        result = asyncio.run(execute())
        assert result.evidence[0].document_id == document_id
        assert {"bm25", "vector", "summary"}.issubset(result.evidence[0].retrieval_sources)
        assert store.run_evidence(run_id)[0]["snippet"].endswith("plus x.")
        assert [kind for kind, _ in events].count("retrieval_source_finished") == 3


def test_fixed_evaluation_metrics_are_repeatable():
    import json

    root = Path(__file__).parents[2] / "evals" / "phase4"
    cases = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    predictions = json.loads((root / "predictions.json").read_text(encoding="utf-8"))
    first = evaluate(cases, predictions)
    assert first == evaluate(cases, predictions)
    assert first["summary"] == {
        "recall_at_5": 1.0,
        "recall_at_10": 1.0,
        "citation_validity": 1.0,
        "citation_support": 1.0,
        "status_match": 1.0,
    }
