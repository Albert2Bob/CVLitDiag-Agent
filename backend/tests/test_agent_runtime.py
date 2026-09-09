"""使用流式 BaseChatModel 测试真实的 create_agent 路由；无需 API 密钥。"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field, SecretStr

from backend.app import agent_runtime as runtime


class ScriptedModel(BaseChatModel):
    state: dict = Field(default_factory=lambda: {"calls": [], "ended": []})
    tool_rounds: int = 1
    timezone: str = "Asia/Shanghai"
    fail: bool = False
    delay: float = 0
    gate: object = None

    @property
    def _llm_type(self):
        return "scripted-streaming-agent-test"

    def _generate(self, *args, **kwargs):
        raise AssertionError("The runtime must use the streaming model path")

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self.bind(tools=tools, tool_choice=tool_choice, **kwargs)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        call = len(self.state["calls"]) + 1
        self.state["calls"].append(
            {
                "messages": [m.model_dump() for m in messages],
                "tools": bool(kwargs.get("tools")),
                "tool_choice": kwargs.get("tool_choice"),
            }
        )
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("PRIVATE_PROVIDER_ERROR")

        def chunk(content="", **extra):
            return ChatGenerationChunk(message=AIMessageChunk(content=content, **extra))

        # 内容块和提供商特有的推理内容绝不能泄露。
        yield chunk("", additional_kwargs={"reasoning_content": "PRIVATE_REASONING"})
        if kwargs.get("tools") and call <= self.tool_rounds:
            yield chunk("PRIVATE_TOOL_PREAMBLE")
            yield chunk(
                tool_call_chunks=[{"name": "get_current_time", "id": f"call_{call}", "args": "", "index": 0}]
            )
            args = json.dumps({"timezone": self.timezone})
            yield chunk(tool_call_chunks=[{"name": None, "id": None, "args": args[:12], "index": 0}])
            yield chunk(tool_call_chunks=[{"name": None, "id": None, "args": args[12:], "index": 0}])
        else:
            yield chunk([{"type": "reasoning", "reasoning": "PRIVATE_BLOCK"}])
            for text in ("<thi", "nk>PRIVATE_TAG", "</th", "ink>", '{"status":"complete","summary":"Hello'):
                yield chunk(text)
            if self.gate:
                await self.gate.wait()
            yield chunk(' world","missing_information":["无文献证据"]}')
        self.state["ended"].append(call)


@pytest.fixture
def settings():
    return SimpleNamespace(
        deepseek_api_key=SecretStr("test-key"),
        deepseek_model="deepseek-v4-flash",
        deepseek_base_url="https://api.deepseek.com",
        model_timeout_seconds=5,
        max_iterations=6,
    )


async def test_actual_tool_loop_and_private_state(settings, caplog, capsys):
    model = ScriptedModel()
    events = []

    async def emit(kind, payload):
        events.append((kind, payload))

    answer = await runtime.execute_agent(settings, [{"role": "user", "content": "time?"}], emit, model)
    assert answer.summary == "Hello world"
    assert [kind for kind, _ in events] == [
        "model_started",
        "model_finished",
        "tool_validation_started",
        "tool_started",
        "tool_finished",
        "model_started",
        "model_finished",
        "output_validation_started",
        "answer_delta",
    ]
    assert [p["iteration"] for k, p in events if k == "model_started"] == [1, 2]
    assert [c["tools"] for c in model.state["calls"]] == [True, True]
    tool_result = next(m for m in model.state["calls"][1]["messages"] if m["type"] == "tool")
    assert "Asia/Shanghai" in tool_result["content"]
    assert "+08:00" in tool_result["content"]
    for kind, payload in events:
        if kind.startswith("tool_"):
            assert payload["name"] == "get_current_time"
            assert payload["tool_call_id"] == "call_1"
        if "duration_ms" in payload:
            assert payload["duration_ms"] >= 0
    combined = json.dumps(events) + caplog.text + str(capsys.readouterr())
    assert "PRIVATE_" not in combined
    for marker in ("PRIVATE_REASONING", "PRIVATE_BLOCK", "PRIVATE_TAG", "PRIVATE_TOOL_PREAMBLE"):
        assert marker not in json.dumps(model.state)
    call = next(m for m in model.state["calls"][1]["messages"] if m["type"] == "ai")
    assert call["tool_calls"][0]["args"]["timezone"] == "Asia/Shanghai"
    assert json.loads(tool_result["content"])["ok"] is True


async def test_final_text_is_buffered_until_provider_finishes(settings):
    gate = asyncio.Event()
    first = asyncio.Event()
    model = ScriptedModel(tool_rounds=0, gate=gate)

    async def emit(kind, payload):
        if kind == "answer_delta":
            first.set()

    task = asyncio.create_task(runtime.execute_agent(settings, [], emit, model))
    try:
        for _ in range(100):
            if model.state["calls"]:
                break
            await asyncio.sleep(0.001)
        await asyncio.sleep(0.01)
        assert not first.is_set()
        assert not task.done()
        assert model.state["ended"] == []
        gate.set()
        assert (await task).summary == "Hello world"
        assert first.is_set()
        assert len(model.state["calls"]) == 1
    finally:
        gate.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_limit_prevents_next_model_request(settings):
    settings.max_iterations = 1
    model = ScriptedModel(tool_rounds=10)
    events = []

    async def emit(kind, payload):
        events.append((kind, payload))

    with pytest.raises(runtime.IterationLimitError):
        await runtime.execute_agent(settings, [], emit, model)
    assert len(model.state["calls"]) == 1
    assert not any(k == "answer_delta" for k, _ in events)


@pytest.mark.parametrize(
    "cancel_at", ["model_started", "model_finished", "tool_started", "tool_finished", "answer_delta"]
)
async def test_emit_cancellation_stops_work(settings, cancel_at):
    model = ScriptedModel()
    events = []

    async def emit(kind, payload):
        events.append(kind)
        if kind == cancel_at:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await runtime.execute_agent(settings, [], emit, model)
    calls = len(model.state["calls"])
    ended = len(model.state["ended"])
    await asyncio.sleep(0)
    assert len(model.state["calls"]) == calls
    assert len(model.state["ended"]) == ended
    assert events[-1] == cancel_at
    assert calls == (0 if cancel_at == "model_started" else 2 if cancel_at == "answer_delta" else 1)


async def test_invalid_timezone_failure_is_sanitized_and_recoverable(settings):
    model = ScriptedModel(timezone="PRIVATE_INVALID_ZONE")
    events = []

    async def emit(kind, payload):
        events.append((kind, payload))

    assert (await runtime.execute_agent(settings, [], emit, model)).summary == "Hello world"
    failed = next(p for k, p in events if k == "tool_failed")
    assert failed["status"] == "failed"
    assert failed["code"] == "INVALID_ARGUMENT"
    assert "PRIVATE_" not in json.dumps(events)
    assert "PRIVATE_INVALID_ZONE" in json.dumps(model.state["calls"][1]["messages"])
    assert any(m["type"] == "tool" and m["status"] == "error" for m in model.state["calls"][1]["messages"])


async def test_model_failure_lifecycle_has_no_error_body(settings):
    events = []

    async def emit(kind, payload):
        events.append((kind, payload))

    with pytest.raises(RuntimeError):
        await runtime.execute_agent(settings, [], emit, ScriptedModel(fail=True))
    assert events[-1][0] == "model_finished"
    assert events[-1][1]["status"] == "failed"
    assert "PRIVATE_" not in json.dumps(events)


async def test_timeout_stops_model(settings):
    settings.model_timeout_seconds = 0.01
    model = ScriptedModel(delay=1)

    async def emit(kind, payload):
        pass

    with pytest.raises(TimeoutError):
        await runtime.execute_agent(settings, [], emit, model)
    assert len(model.state["calls"]) == 1
    assert not model.state["ended"]


async def test_deepseek_constructor_disables_thinking(settings, monkeypatch):
    captured = {}

    def constructor(**kwargs):
        captured.update(kwargs)
        return ScriptedModel(tool_rounds=0)

    monkeypatch.setattr(runtime, "ChatDeepSeek", constructor)

    async def emit(kind, payload):
        pass

    await runtime.execute_agent(settings, [], emit)
    assert captured["extra_body"] == {
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
    }
    assert captured["model"] == settings.deepseek_model
    assert captured["api_base"] == settings.deepseek_base_url
    assert captured["max_retries"] == 0
    assert captured["streaming"] is True
    assert captured["cache"] is False
