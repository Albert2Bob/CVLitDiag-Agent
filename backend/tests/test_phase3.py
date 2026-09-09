"""使用可控模型与工具验证业务契约，不依赖真实提供商。"""

import asyncio
import json
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from backend.app.agent_runtime import execute_agent
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.output_validation import OutputValidationFailed, finalize, validate_answer
from backend.app.schemas import ErrorCode, ToolCallRequest
from backend.app.storage import Store
from backend.app.tool_executor import RunContext, ToolExecutor, default_tools
from backend.tests.test_agent_runtime import ScriptedModel


def valid(summary="测试回答"):
    return {"status": "complete", "summary": summary, "missing_information": ["尚无文献证据"]}


@pytest.fixture
def scope():
    store = Store(":memory:")
    pid = store.list_projects()[0]["project_id"]
    tid = store.create_thread(pid)["thread_id"]
    rid = store.create_run(tid, pid, "测试")["run_id"]
    context = RunContext(store.user_id, pid, tid, rid, store, ("sk-test-secret",))
    yield context
    store.db.close()


def request(name="get_current_time", args=None):
    return ToolCallRequest(
        tool_name=name, arguments={} if args is None else args, tool_call_id="call_" + uuid4().hex
    )


async def noop(*args):
    pass


async def test_argument_gate_unknown_and_safe_exception(scope):
    calls = []

    async def spy(args, context):
        calls.append(args)
        raise RuntimeError("sk-test-secret database://root:password@internal C:\\private")

    definition = replace(default_tools()[0], execute=spy)
    executor = ToolExecutor(scope, noop, [definition])
    bad = await executor.execute(request(args={"timezone": "not/a/zone"}))
    assert bad.error.code == ErrorCode.INVALID_ARGUMENT
    assert not calls
    unknown = await executor.execute(request("unknown", {"api_key": "sk-test-secret"}))
    assert unknown.error.code == ErrorCode.TOOL_NOT_FOUND
    error = await executor.execute(request())
    assert len(calls) == 1 and error.error.code == ErrorCode.TOOL_EXECUTION_FAILED
    assert error.data is None and error.duration_ms >= 0
    assert "sk-test-secret" not in json.dumps(scope.store.rows("SELECT record FROM audits"))
    assert "private" not in error.model_dump_json()


async def test_timeout_and_failed_results_not_cached(scope):
    calls = []

    async def slow(args, ctx):
        calls.append(1)
        await asyncio.sleep(1)

    executor = ToolExecutor(scope, noop, [replace(default_tools()[0], execute=slow, timeout_seconds=0.01)])
    for _ in range(2):
        assert (await executor.execute(request())).error.code == ErrorCode.TOOL_TIMEOUT
    assert len(calls) == 2 and not executor.cache


async def test_clock_cache_scope_order_defaults_and_concurrency(scope):
    events = []

    async def emit(kind, payload):
        events.append((kind, payload))

    executor = ToolExecutor(scope, emit)
    first, second = await asyncio.gather(executor.execute(request()), executor.execute(request()))
    assert first.ok and second.ok
    assert first.data["current_time"].endswith("+08:00")
    assert first.trace_id != second.trace_id
    assert executor.records[-1].cache_hit
    await executor.execute(request(args={"timezone": "Asia/Shanghai"}))
    assert executor.records[-1].cache_hit
    await executor.execute(request(args={"timezone": "UTC"}))
    assert not executor.records[-1].cache_hit
    args = {"project_id": scope.project_id, "file_type": "md"}
    await executor.execute(request("list_project_documents", args))
    await executor.execute(request("list_project_documents", dict(reversed(list(args.items())))))
    assert executor.records[-1].cache_hit
    assert any(p.get("cache_hit") for k, p in events if k == "tool_finished")
    tid = scope.store.create_thread(scope.project_id)["thread_id"]
    rid = scope.store.create_run(tid, scope.project_id, "其他运行")["run_id"]
    other = ToolExecutor(replace(scope, run_id=rid, thread_id=tid), noop)
    await other.execute(request())
    assert not other.records[-1].cache_hit
    assert other.cache.keys().isdisjoint(executor.cache.keys())


async def test_cross_project_documents_unknown_ids_and_owner(scope):
    other = scope.store.create_project("其他项目")["project_id"]
    executor = ToolExecutor(scope, noop)
    for name, args in [
        ("get_document_metadata", {"document_id": other + "_demo"}),
        ("get_document_metadata", {"document_id": "forged_document"}),
        ("list_project_documents", {"project_id": other}),
    ]:
        result = await executor.execute(request(name, args))
        assert result.error.code == ErrorCode.PERMISSION_DENIED
        assert executor.records[-1].permission_validation == "failed"
    assert (
        await executor.execute(request("get_document_metadata", {"document_id": scope.project_id + "_demo"}))
    ).data["source"] == "development_fixture"
    scope.store.db.execute(
        "UPDATE project_owners SET user_id=? WHERE project_id=?", ("another_user", scope.project_id)
    )
    result = await executor.execute(
        request("get_document_metadata", {"document_id": scope.project_id + "_demo"})
    )
    assert result.error.code == ErrorCode.PERMISSION_DENIED
    assert not executor.records[-1].cache_hit


async def test_writes_never_cached_and_invalid_returns_safe(scope):
    executor = ToolExecutor(scope, noop, [replace(default_tools()[0], read_only=False)])
    await executor.execute(request())
    await executor.execute(request())
    assert not executor.cache and not executor.records[-1].cache_hit

    async def invalid(args, ctx):
        return {"private": "sk-test-secret"}

    executor = ToolExecutor(scope, noop, [replace(default_tools()[0], execute=invalid)])
    assert (await executor.execute(request())).error.code == ErrorCode.TOOL_EXECUTION_FAILED


def test_client_identity_cannot_change_resource_access(tmp_path):
    cfg = Settings(_env_file=None, database_path=str(tmp_path / "auth.db"))
    with TestClient(create_app(cfg)) as client:
        store = client.app.state.store
        own = store.list_projects()[0]["project_id"]
        foreign = store.create_project("其他用户项目")["project_id"]
        tid = store.create_thread(foreign)["thread_id"]
        rid = store.create_run(tid, foreign, "外部任务")["run_id"]
        store.db.execute("UPDATE project_owners SET user_id=? WHERE project_id=?", ("victim", foreign))
        store.db.commit()
        assert all(p["project_id"] != foreign for p in client.get("/api/projects").json())
        for url in [
            f"/api/projects/{foreign}/threads",
            f"/api/threads/{tid}/messages",
            f"/api/runs/{rid}",
            f"/api/runs/{rid}/events",
        ]:
            assert client.get(url).status_code == 403
        assert client.post(f"/api/runs/{rid}/cancel").status_code == 403
        assert (
            client.post("/api/threads", json={"project_id": foreign, "user_id": "victim"}).status_code == 403
        )
        assert (
            client.post(
                "/api/runs",
                json={"project_id": foreign, "thread_id": tid, "question": "伪造身份", "user_id": "victim"},
            ).status_code
            == 403
        )
        response = client.post("/api/threads", json={"project_id": own, "user_id": "victim"}).json()
        assert response["user_id"] == "demo_researcher"


@pytest.mark.parametrize(
    "candidate",
    [
        "{broken",
        {"status": "complete", "summary": ""},
        {**valid(), "claims": [{"statement": "伪造", "evidence_ids": ["invented"]}]},
    ],
)
async def test_exactly_one_repair_succeeds_and_audits(scope, candidate):
    repairs, events = [], []

    async def repair(prompt):
        repairs.append(json.loads(prompt))
        return json.dumps(valid())

    async def emit(kind, payload):
        events.append(kind)

    answer = await finalize(candidate, set(), emit, repair, scope)
    assert answer.summary == "测试回答" and len(repairs) == 1
    assert repairs[0]["schema"] and repairs[0]["errors"]
    assert events.count("output_validation_failed") == 1
    records = scope.store.rows("SELECT record FROM audits WHERE kind='output'")
    assert [json.loads(r["record"])["valid"] for r in records] == [False, True]


async def test_second_failure_has_no_answer_or_completion(scope):
    events, calls = [], []

    async def repair(prompt):
        calls.append(prompt)
        return "{invalid again"

    async def emit(kind, payload):
        events.append(kind)

    with pytest.raises(OutputValidationFailed):
        await finalize("{invalid", set(), emit, repair, scope)
    assert len(calls) == 1
    assert "completed" not in events and "answer_delta" not in events
    assert events.count("output_validation_failed") == 2


def test_evidence_membership_and_fences():
    candidate = {**valid(), "claims": [{"statement": "结论", "evidence_ids": ["real_id"]}]}
    with pytest.raises(ValueError):
        validate_answer(candidate, set())
    assert validate_answer(candidate, {"real_id"}).claims[0].evidence_ids == ["real_id"]
    assert validate_answer("```json\n" + json.dumps(valid()) + "\n```", set()).summary == "测试回答"
    with pytest.raises(ValueError):
        validate_answer({"status": "complete", "summary": "无证据断言"}, set())


class RepairModel(ScriptedModel):
    broken_repair: bool = False

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        if len(self.state["calls"]) == 0:
            async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
                yield chunk
            return
        self.state["calls"].append({"tools": bool(kwargs.get("tools"))})
        text = "{broken" if len(self.state["calls"]) == 2 or self.broken_repair else json.dumps(valid())
        yield ChatGenerationChunk(message=AIMessageChunk(content=text))


@pytest.mark.parametrize("broken", [False, True])
async def test_real_loop_repair_never_reexecutes_tools(scope, broken):
    model = RepairModel(broken_repair=broken)
    cfg = Settings(_env_file=None)
    if broken:
        with pytest.raises(OutputValidationFailed):
            await execute_agent(cfg, [], noop, model, context=scope)
    else:
        assert (await execute_agent(cfg, [], noop, model, context=scope)).summary == "测试回答"
    assert [c["tools"] for c in model.state["calls"]] == [True, True, False]
    assert len(scope.store.rows("SELECT * FROM audits WHERE kind='tool'")) == 1


@pytest.mark.parametrize(
    "cancel_at", ["tool_validation_started", "output_validation_started", "output_repair_started"]
)
async def test_cancel_prevents_new_tools_and_repair(scope, cancel_at):
    model = RepairModel()

    async def emit(kind, payload):
        if kind == cancel_at:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await execute_agent(Settings(_env_file=None), [], emit, model, context=scope)
    assert len(model.state["calls"]) <= 2
    if cancel_at == "tool_validation_started":
        assert not scope.store.rows("SELECT * FROM audits")


def test_invalid_injected_final_result_cannot_complete(tmp_path):
    async def fake(*args):
        return {"status": "complete", "summary": "未验证数据"}

    with TestClient(
        create_app(Settings(_env_file=None, database_path=str(tmp_path / "bad.db")), fake)
    ) as client:
        pid = client.get("/api/projects").json()[0]["project_id"]
        tid = client.post("/api/threads", json={"project_id": pid}).json()["thread_id"]
        rid = client.post("/api/runs", json={"project_id": pid, "thread_id": tid, "question": "测试"}).json()[
            "run_id"
        ]
        response = client.get(f"/api/runs/{rid}/events")
        assert "event: completed" not in response.text
        assert client.get(f"/api/runs/{rid}").json()["answer"] is None


class InvalidCallModel(ScriptedModel):
    unknown: bool = False

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        if self.state["calls"]:
            self.state["calls"].append({"messages": [m.model_dump() for m in messages]})
            yield ChatGenerationChunk(message=AIMessageChunk(content=json.dumps(valid())))
            return
        self.state["calls"].append({})
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "unknown_tool" if self.unknown else "get_current_time",
                        "id": "broken_call",
                        "args": "{}" if self.unknown else "{broken json",
                        "index": 0,
                    }
                ],
            )
        )


@pytest.mark.parametrize("unknown", [False, True])
async def test_model_unknown_and_malformed_calls_use_executor(scope, unknown):
    model = InvalidCallModel(unknown=unknown)
    answer = await execute_agent(Settings(_env_file=None), [], noop, model, context=scope)
    assert answer.summary == "测试回答"
    record = json.loads(scope.store.rows("SELECT record FROM audits WHERE kind='tool'")[0]["record"])
    assert record["error_code"] == ("TOOL_NOT_FOUND" if unknown else "INVALID_ARGUMENT")
    tool = next(m for m in model.state["calls"][1]["messages"] if m["type"] == "tool")
    assert json.loads(tool["content"])["error"]["code"] == record["error_code"]


def test_upgrade_is_repeatable_and_preserves_text_history(tmp_path):
    path = str(tmp_path / "migration.db")
    store = Store(path)
    pid = store.list_projects()[0]["project_id"]
    tid = store.create_thread(pid)["thread_id"]
    rid = store.create_run(tid, pid, "旧问题")["run_id"]
    store.append(rid, "completed", {"answer": "阶段 2 历史文本"})
    store.db.execute("ALTER TABLE runs DROP COLUMN final_answer")
    store.db.execute("DROP TABLE project_owners")
    store.db.execute("DROP TABLE audits")
    store.db.execute("DROP TABLE documents")
    store.db.execute("PRAGMA user_version=1")
    store.db.commit()
    store.db.close()
    for _ in range(2):
        store = Store(path)
        assert store.run(rid)["answer"] == "阶段 2 历史文本"
        assert store.messages(tid)[-1]["content"] == "阶段 2 历史文本"
        assert len(store.documents(pid)) == 1
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 3
        store.db.close()
