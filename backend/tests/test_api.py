import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APITimeoutError, AuthenticationError, RateLimitError

from backend.app.config import Settings
from backend.app.main import Runner, create_app
from backend.app.storage import Store


def settings(tmp_path, **kwargs):
    return Settings(_env_file=None, database_path=str(tmp_path / "test.sqlite3"), **kwargs)


def new_run(client):
    project = client.get("/api/projects").json()[0]["project_id"]
    thread = client.post("/api/threads", json={"project_id": project}).json()["thread_id"]
    body = {"project_id": project, "thread_id": thread, "question": "你好"}
    response = client.post("/api/runs", json=body)
    assert response.status_code == 202
    return response.json(), body


def parse_events(response):
    result = []
    for frame in response.text.strip().split("\n\n"):
        if not frame:
            continue
        lines = frame.splitlines()
        event = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))
        assert f"id: {event['event_id']}" in lines
        assert f"event: {event['type']}" in lines
        result.append(event)
    return result


def test_saved_replay_cursor_refresh_and_no_second_execution(tmp_path):
    calls = []

    async def fake(config, messages, emit):
        calls.append(messages)
        await emit("model_started", {"iteration": 1, "status": "running"})
        for text in ["你", "好"]:
            await emit("answer_delta", {"delta": text})
            await asyncio.sleep(0.02)
        await emit("model_finished", {"iteration": 1, "status": "completed"})
        return {"status": "complete", "summary": "你好", "missing_information": ["无文献证据"]}

    cfg = settings(tmp_path)
    with TestClient(create_app(cfg, fake)) as client:
        run, body = new_run(client)
        url = f"/api/runs/{run['run_id']}"
        events = parse_events(client.get(url + "/events"))
        assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
        assert events[-1]["type"] == "completed"
        cursor = events[1]["event_id"]
        assert parse_events(client.get(url + "/events", headers={"Last-Event-ID": cursor})) == events[2:]
        assert parse_events(client.get(url + "/events", params={"last_event_id": cursor})) == events[2:]
        # 原生自动重连的标头优先于原始查询游标。
        assert (
            parse_events(
                client.get(
                    url + "/events",
                    params={"last_event_id": cursor},
                    headers={"Last-Event-ID": events[-1]["event_id"]},
                )
            )
            == []
        )
        assert client.get(url + "/events", params={"last_event_id": "foreign:1"}).status_code == 400
        assert client.get(url).json()["answer"]["summary"] == "你好"
        assert client.post(url + "/cancel").json()["status"] == "completed"
        assert len(calls) == 1
        messages = client.get(f"/api/threads/{body['thread_id']}/messages").json()
        assert messages[-1]["content"] == "你好"
    with TestClient(create_app(cfg, fake)) as client:
        assert client.get(url).json()["events"] == events
        assert client.get(url).json()["answer"]["summary"] == "你好"


def test_cancel_busy_idempotence_and_new_run(tmp_path):
    async def blocked(config, messages, emit):
        await asyncio.sleep(30)
        await emit("answer_delta", {"delta": "迟到"})
        return "迟到"

    with TestClient(create_app(settings(tmp_path), blocked)) as client:
        run, body = new_run(client)
        assert client.post("/api/runs", json=body).status_code == 409
        url = f"/api/runs/{run['run_id']}"
        first = client.post(url + "/cancel").json()
        second = client.post(url + "/cancel").json()
        assert first == second
        assert first["status"] == "cancelled"
        assert first["events"][-1]["type"] == "cancelled"
        regenerated = client.post("/api/runs", json=body).json()
        assert regenerated["run_id"] != run["run_id"]


@pytest.mark.parametrize(
    "error,code",
    [
        (TimeoutError(), "MODEL_TIMEOUT"),
        (APITimeoutError(request=httpx.Request("POST", "https://example.com")), "MODEL_TIMEOUT"),
        (
            AuthenticationError(
                "secret",
                response=httpx.Response(401, request=httpx.Request("POST", "https://example.com")),
                body=None,
            ),
            "MODEL_AUTHENTICATION_FAILED",
        ),
        (
            RateLimitError(
                "secret",
                response=httpx.Response(429, request=httpx.Request("POST", "https://example.com")),
                body=None,
            ),
            "MODEL_RATE_LIMITED",
        ),
        (ValueError("secret"), "AGENT_FAILED"),
    ],
)
def test_safe_model_failures(tmp_path, error, code):
    async def fail(config, messages, emit):
        raise error

    with TestClient(create_app(settings(tmp_path), fail)) as client:
        run, _ = new_run(client)
        response = client.get(f"/api/runs/{run['run_id']}/events")
        assert "secret" not in response.text
        final = parse_events(response)[-1]
        assert final["type"] == "failed"
        assert final["payload"]["code"] == code


def test_missing_key_health_and_run(tmp_path):
    with TestClient(create_app(settings(tmp_path, deepseek_api_key=""))) as client:
        health = client.get("/health")
        assert health.status_code == 503
        assert health.headers["cache-control"] == "no-store"
        assert health.json()["storage"] is True
        run, _ = new_run(client)
        final = parse_events(client.get(f"/api/runs/{run['run_id']}/events"))[-1]
        assert final["payload"]["code"] == "MODEL_NOT_CONFIGURED"


def test_restart_marks_orphans_failed(tmp_path):
    cfg = settings(tmp_path)
    store = Store(cfg.database_path)
    project = store.list_projects()[0]["project_id"]
    thread = store.create_thread(project)
    run = store.create_run(thread["thread_id"], project, "hello")
    store.append(run["run_id"], "run_started", {"status": "running"})
    store.db.close()
    with TestClient(create_app(cfg)) as client:
        saved = client.get(f"/api/runs/{run['run_id']}").json()
        assert saved["status"] == "failed"
        assert saved["events"][-1]["payload"]["code"] == "SERVICE_RESTARTED"


async def test_cancel_discards_late_output_and_stops_followup(tmp_path):
    store = Store(str(tmp_path / "race.sqlite3"))
    project = store.list_projects()[0]["project_id"]
    thread = store.create_thread(project)
    run = store.create_run(thread["thread_id"], project, "hello")
    waiting = asyncio.Event()
    followup = []

    async def stubborn(config, messages, emit):
        waiting.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass  # 模拟 SDK 在取消后仍延迟送达回调。
        await emit("answer_delta", {"delta": "late"})
        followup.append("next model call")
        return "late"

    runner = Runner(store, settings(tmp_path), stubborn)
    runner.start(run["run_id"])
    await waiting.wait()
    task = runner.tasks[run["run_id"]]
    runner.cancel(run["run_id"])
    await task
    assert not followup
    saved = store.run(run["run_id"])
    assert saved["status"] == "cancelled"
    assert not any(e["type"] == "answer_delta" for e in saved["events"])
    assert store.append(run["run_id"], "completed", {"answer": "late"}) is None
    store.db.close()


async def test_total_timeout(tmp_path):
    async def slow(config, messages, emit):
        await asyncio.sleep(20)

    app = create_app(settings(tmp_path, run_timeout_seconds=0.02), slow)
    async with app.router.lifespan_context(app):
        store = app.state.store
        pid = store.list_projects()[0]["project_id"]
        tid = store.create_thread(pid)["thread_id"]
        run = store.create_run(tid, pid, "hi")
        await app.state.runner.execute(run["run_id"])
        assert store.run(run["run_id"])["events"][-1]["payload"]["code"] == "MODEL_TIMEOUT"
