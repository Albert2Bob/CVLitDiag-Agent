"""三路并发召回、重排、相邻块补取与证据选择。"""

import asyncio
import hashlib
from time import perf_counter
from uuid import uuid4

from .fusion import rrf_fuse
from .query import normalize_query
from .reranker import rerank
from .schemas import Evidence, SearchResult


class RetrievalUnavailable(RuntimeError):
    pass


def evidence_id(run_id, project_id, chunk_id, version, selection_version="v1"):
    raw = f"{run_id}\0{project_id}\0{chunk_id}\0{version}\0{selection_version}".encode()
    return "evidence_" + hashlib.sha256(raw).hexdigest()[:32]


class RetrievalService:
    def __init__(self, store, keyword, vector, summary, reranker, settings):
        self.store, self.keyword, self.vector, self.summary = store, keyword, vector, summary
        self.reranker, self.settings = reranker, settings

    async def search(self, args, context, emit):
        started = perf_counter()
        retrieval_id = "retrieval_" + uuid4().hex
        queries = normalize_query(args.query)
        await emit("retrieval_started", {"retrieval_id": retrieval_id, "summary": "正在并行执行三路召回。"})
        sources = {"bm25": self.keyword, "vector": self.vector, "summary": self.summary}

        async def one(name, index):
            try:
                async with asyncio.timeout(self.settings.retrieval_timeout_seconds):
                    result = await index.search(queries, context.project_id, args.document_ids, self.settings.retrieval_top_k_each)
                await emit("retrieval_source_finished", {"retrieval_id": retrieval_id, "source": name, "status": "completed", "candidate_count": len(result)})
                return name, result, None
            except Exception:
                await emit("retrieval_source_finished", {"retrieval_id": retrieval_id, "source": name, "status": "failed", "candidate_count": 0})
                return name, [], name

        results = await asyncio.gather(*(one(name, index) for name, index in sources.items()))
        degraded = [failure for _, _, failure in results if failure]
        if len(degraded) == len(sources):
            duration = round((perf_counter() - started) * 1000, 3)
            await emit(
                "retrieval_finished",
                {
                    "retrieval_id": retrieval_id,
                    "status": "failed",
                    "candidate_count": 0,
                    "evidence_count": 0,
                    "duration_ms": duration,
                    "degraded_sources": degraded,
                    "summary": "三路检索均不可用。",
                },
            )
            raise RetrievalUnavailable("三路检索均不可用")
        fused = rrf_fuse([items for _, items, _ in results], self.settings.rrf_k)
        await emit("rerank_started", {"retrieval_id": retrieval_id, "candidate_count": min(len(fused), self.settings.rerank_top_n), "summary": "正在重排候选证据。"})
        ranked, rerank_degraded = await rerank(args.query, fused, self.reranker, self.settings.rerank_top_n, self.settings.retrieval_timeout_seconds)
        if rerank_degraded:
            degraded.append("reranker")
        await emit("rerank_finished", {"retrieval_id": retrieval_id, "status": "degraded" if rerank_degraded else "completed", "candidate_count": len(ranked)})
        selected = self._select(ranked, args.top_k, args.comparison_mode, context)
        evidence = [self._evidence(item, context) for item in selected]
        context.store.save_run_evidence(context.run_id, evidence)
        duration = round((perf_counter() - started) * 1000, 3)
        await emit("retrieval_finished", {"retrieval_id": retrieval_id, "candidate_count": len(fused), "evidence_count": len(evidence), "duration_ms": duration, "degraded_sources": degraded, "summary": f"检索完成，获得 {len(evidence)} 条证据。"})
        return SearchResult(query=args.query, normalized_queries=queries, evidence=evidence, retrieval_summary={"retrieval_id": retrieval_id, "candidate_count": len(fused), "duration_ms": duration}, degraded_sources=degraded, has_more=len(ranked) > len(selected))

    def _select(self, ranked, top_k, comparison, context):
        limit = min(top_k, self.settings.evidence_top_k)
        selected, per_doc, chars = [], {}, 0
        pool = ranked
        if comparison:
            first = {}
            for item in ranked:
                first.setdefault(item.chunk.document_id, item)
            pool = list(first.values()) + [item for item in ranked if item not in first.values()]
        for item in pool:
            if item.rerank_score is not None and item.rerank_score <= 0:
                continue
            doc = item.chunk.document_id
            if per_doc.get(doc, 0) >= self.settings.evidence_per_document:
                continue
            if chars + len(item.chunk.content) > self.settings.evidence_max_chars:
                continue
            selected.append(item)
            per_doc[doc] = per_doc.get(doc, 0) + 1
            chars += len(item.chunk.content)
            if len(selected) >= limit:
                break
        # 仅补取严格同项目、文档和版本的相邻块，并仍受总预算限制。
        for item in list(selected):
            if len(selected) >= limit:
                break
            neighbor = context.store.adjacent_chunk(item.chunk, 1)
            if (
                neighbor
                and neighbor.project_id == item.chunk.project_id == context.project_id
                and neighbor.document_id == item.chunk.document_id
                and neighbor.document_version == item.chunk.document_version
                and neighbor.access_scope == item.chunk.access_scope
                and per_doc.get(neighbor.document_id, 0) < self.settings.evidence_per_document
                and all(x.chunk.chunk_id != neighbor.chunk_id for x in selected)
                and chars + len(neighbor.content) <= self.settings.evidence_max_chars
            ):
                selected.append(
                    item.model_copy(
                        update={
                            "chunk": neighbor,
                            "retrieval_sources": ["adjacent"],
                            "source_ranks": {},
                            "rerank_score": None,
                        }
                    )
                )
                chars += len(neighbor.content)
                per_doc[neighbor.document_id] = per_doc.get(neighbor.document_id, 0) + 1
        return selected[:limit]

    def _evidence(self, item, context):
        chunk = item.chunk
        doc = context.store.document(chunk.document_id)
        return Evidence(evidence_id=evidence_id(context.run_id, context.project_id, chunk.chunk_id, chunk.document_version), run_id=context.run_id, project_id=context.project_id, document_id=chunk.document_id, document_version=chunk.document_version, chunk_id=chunk.chunk_id, document_name=doc["filename"], section=chunk.section, page_number=chunk.page_number, page_end=chunk.page_end, locator=chunk.locator, snippet=chunk.content, retrieval_sources=item.retrieval_sources, fused_rank=item.fused_rank, rerank_score=item.rerank_score)
