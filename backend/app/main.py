import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import Settings
from .output_validation import OutputValidationFailed, validate_answer
from .schemas import ErrorCode, FinalAnswer
from .security import PermissionDenied
from .storage import TERMINAL, Conflict, Store
from .tool_executor import RunContext


class ThreadInput(BaseModel):
    project_id: str
    # 保留阶段 2 请求格式；真实用户身份始终由服务端存储层提供。
    user_id: str = "demo_researcher"


class RunInput(ThreadInput):
    thread_id: str
    question: str = Field(min_length=1, max_length=12000)


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)


def safe_failure(exc):
    # 有意不序列化提供商错误正文、URL、标头或 repr(exc)。
    from openai import APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError

    if isinstance(exc, OutputValidationFailed):
        return ErrorCode.OUTPUT_VALIDATION_FAILED, "回答在一次修复后仍未通过校验，请重新生成。"
    if isinstance(exc, (TimeoutError, APITimeoutError)):
        return "MODEL_TIMEOUT", "模型请求或任务执行超时，请稍后重新生成。"
    if isinstance(exc, AuthenticationError):
        return "MODEL_AUTHENTICATION_FAILED", "模型认证失败，请检查服务端 API Key。"
    if isinstance(exc, RateLimitError):
        return "MODEL_RATE_LIMITED", "模型服务限流或配额不足，请稍后重试。"
    if isinstance(exc, APIConnectionError):
        return "MODEL_UNAVAILABLE", "暂时无法连接模型服务，请稍后重试。"
    if type(exc).__name__ in ("IterationLimitError", "GraphRecursionError", "ModelCallLimitExceeded"):
        return "ITERATION_LIMIT", "已达到模型调用次数上限，请简化问题后重试。"
    return "AGENT_FAILED", "任务执行失败，请检查模型配置或重新生成。"


class Runner:
    def __init__(self, store, settings, executor=None):
        self.store, self.settings = store, settings
        self.executor = executor
        self.tasks = {}

    def start(self, run_id):
        task = asyncio.create_task(self.execute(run_id), name=run_id)
        self.tasks[run_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(run_id, None))

    async def execute(self, run_id):
        async def emit(kind, payload):
            # 事件先持久化再广播，客户端重连后才能按序补齐执行过程。
            if not self.store.append(run_id, kind, payload):
                raise asyncio.CancelledError

        try:
            await emit("run_started", {"status": "running", "message": "正在处理当前问题。"})
            if not self.executor and not self.settings.model_ready:
                await emit(
                    "failed",
                    {
                        "status": "failed",
                        "code": "MODEL_NOT_CONFIGURED",
                        "message": "模型未配置，请在服务端设置 DEEPSEEK_API_KEY。",
                    },
                )
                return
            executor = self.executor
            if executor is None:
                from .agent_runtime import execute_agent

                executor = execute_agent
            async with asyncio.timeout(self.settings.run_timeout_seconds):
                if self.executor:
                    answer = await executor(self.settings, self.store.history(run_id), emit)
                else:
                    run = self.store.run(run_id)
                    # 执行上下文来自已鉴权的服务端记录，不采信请求体里的 user_id。
                    context = RunContext(
                        self.store.user_id,
                        run["project_id"],
                        run["thread_id"],
                        run_id,
                        self.store,
                        (self.settings.deepseek_api_key.get_secret_value(),),
                    )
                    answer = await executor(self.settings, self.store.history(run_id), emit, context=context)
                if isinstance(answer, FinalAnswer):
                    answer = answer.model_dump(mode="json")
                try:
                    # 完成事件前再次校验，防止自定义执行器绕过运行时的输出契约。
                    answer = validate_answer(answer, set()).model_dump(mode="json")
                except (ValueError, TypeError) as exc:
                    raise OutputValidationFailed from exc
                await emit("completed", {"status": "completed", "answer": answer, "evidence": []})
        except asyncio.CancelledError:
            # 取消端点或关停流程已经负责持久化终止事件。
            pass
        except Exception as exc:
            code, message = safe_failure(exc)
            self.store.append(run_id, "failed", {"status": "failed", "code": code, "message": message})
            logging.getLogger("agent").warning("run_failed run_id=%s code=%s", run_id, code)

    def cancel(self, run_id):
        changed = self.store.append(
            run_id,
            "cancelled",
            {"status": "cancelled", "message": "生成已停止；无法撤回提供商已处理的请求或费用。"},
        )
        if changed and (task := self.tasks.get(run_id)):
            task.cancel()
        return self.store.run(run_id)

    async def stop(self):
        tasks = list(self.tasks.items())
        for run_id, task in tasks:
            self.store.append(
                run_id,
                "failed",
                {
                    "status": "failed",
                    "code": "SERVICE_RESTARTED",
                    "message": "服务已停止，原任务无法继续，请重新生成。",
                },
            )
            task.cancel()
        if tasks:
            await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)


def create_app(settings=None, executor=None):
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        # SDK 调试日志可能包含请求载荷；此阶段仅公开安全事件。
        for name in ("httpx", "httpcore", "openai"):
            logging.getLogger(name).setLevel(logging.WARNING)
        store = Store(config.database_path, config.development_user_id)
        store.recover_interrupted()
        app.state.store = store
        app.state.runner = Runner(store, config, executor)
        try:
            yield
        finally:
            await app.state.runner.stop()
            store.db.close()

    app = FastAPI(title="科研 Agent · 阶段 3", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[s.strip() for s in config.cors_origins.split(",") if s.strip()],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )

    @app.middleware("http")
    async def prevent_stale_run_snapshots(request, call_next):
        response = await call_next(request)
        if request.url.path == "/health" or request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse(
            status_code=404, content={"code": "NOT_FOUND", "message": "项目、会话或任务不存在。"}
        )

    @app.exception_handler(PermissionDenied)
    async def denied(request, exc):
        return JSONResponse(
            status_code=403, content={"code": ErrorCode.PERMISSION_DENIED, "message": "无权访问该资源。"}
        )

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse(status_code=409, content={"code": "THREAD_BUSY", "message": str(exc)})

    @app.exception_handler(Exception)
    async def internal(request, exc):
        return JSONResponse(
            status_code=500, content={"code": "INTERNAL_ERROR", "message": "服务暂时不可用，请稍后重试。"}
        )

    @app.get("/health")
    async def health():
        try:
            app.state.store.db.execute("SELECT 1").fetchone()
            storage_ready = True
        except Exception:
            storage_ready = False
        ready = storage_ready and config.model_ready
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ready" if ready else "not_ready",
                "service": True,
                "storage": storage_ready,
                "model_configured": config.model_ready,
                "model": config.deepseek_model,
                "auth": "development_placeholder",
                "provider_verified": False,
            },
        )

    @app.get("/api/projects")
    async def projects():
        return app.state.store.list_projects()

    @app.post("/api/projects", status_code=201)
    async def project(body: ProjectInput):
        return app.state.store.create_project(body.name, body.description)

    @app.get("/api/projects/{project_id}/threads")
    async def threads(project_id: str):
        return app.state.store.list_threads(project_id)

    @app.post("/api/threads", status_code=201)
    async def thread(body: ThreadInput):
        return app.state.store.create_thread(body.project_id)

    @app.get("/api/threads/{thread_id}/messages")
    async def messages(thread_id: str):
        return app.state.store.messages(thread_id)

    @app.post("/api/runs", status_code=202)
    async def create_run(body: RunInput):
        if not body.question.strip():
            raise HTTPException(422, detail="问题不能为空。")
        run = app.state.store.create_run(body.thread_id, body.project_id, body.question.strip())
        app.state.runner.start(run["run_id"])
        return run

    @app.get("/api/runs/{run_id}")
    async def run(run_id: str):
        return app.state.store.run(run_id)

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel(run_id: str):
        app.state.store.run(run_id)
        return app.state.runner.cancel(run_id)

    @app.get("/api/runs/{run_id}/events")
    async def events(
        run_id: str,
        request: Request,
        last_event_id: str = "",
        header_cursor: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ):
        store = app.state.store
        store.run(run_id)
        try:
            cursor = store.cursor(run_id, header_cursor or last_event_id)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from None

        async def stream():
            nonlocal cursor
            loop = asyncio.get_running_loop()
            heartbeat_at = loop.time() + config.heartbeat_seconds
            while not await request.is_disconnected():
                # 重新读取持久化尾部：避免历史/实时交接竞争，也不使用内存队列。
                batch = store.events(run_id, cursor)
                for event in batch:
                    cursor = event["sequence"]
                    yield f"id: {event['event_id']}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if store.run(run_id)["status"] in TERMINAL:
                    # 最后一次读取尾部与终止检查之间没有 await；写入也在同一事件循环中执行。
                    return
                if loop.time() >= heartbeat_at:
                    store.append(run_id, "heartbeat", {"status": "connected"})
                    heartbeat_at = loop.time() + config.heartbeat_seconds
                    continue
                await asyncio.sleep(0.1)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
