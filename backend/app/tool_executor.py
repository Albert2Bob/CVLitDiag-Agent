"""所有工具调用的校验、授权、运行缓存和持久审计入口。"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Callable, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, field_validator

from .schemas import (
    Contract,
    DocumentMetadata,
    ErrorCode,
    ResourceId,
    ToolCallRecord,
    ToolCallRequest,
    ToolExecutionError,
    ToolExecutionResult,
)
from .security import PermissionDenied, redact


@dataclass(frozen=True)
class RunContext:
    # 运行身份与资源边界由服务端创建，不能从模型生成的工具参数中推断。
    user_id: str
    project_id: str
    thread_id: str
    run_id: str
    store: object = None
    secrets: tuple = ()


class TimeArguments(Contract):
    timezone: str = "Asia/Shanghai"

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        try:
            if len(value) > 100:
                raise ValueError
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("请提供有效的 IANA 时区") from None
        return value


class ListArguments(Contract):
    project_id: ResourceId
    file_type: Literal["pdf", "md", "txt", "csv", "json"] | None = None
    parse_status: Literal["mock_metadata"] | None = None


class MetadataArguments(Contract):
    document_id: ResourceId


class TimeData(Contract):
    timezone: str
    current_time: str


class DocumentList(Contract):
    documents: list[DocumentMetadata]
    source: Literal["development_fixture"] = "development_fixture"


async def clock(args, context):
    return TimeData(
        timezone=args.timezone,
        current_time=datetime.now(ZoneInfo(args.timezone)).isoformat(timespec="seconds"),
    )


async def list_documents(args, context):
    return DocumentList(
        documents=context.store.documents(context.project_id, args.file_type, args.parse_status)
    )


async def metadata(args, context):
    return DocumentMetadata.model_validate(context.store.document(args.document_id))


@dataclass(frozen=True)
class ToolDefinition:
    # 工具的输入、输出和读写属性集中声明，执行器据此统一校验与审计。
    name: str
    description: str
    arguments: type[BaseModel]
    data_model: type[BaseModel]
    execute: Callable
    permission: Literal["session", "project", "document"]
    read_only: bool = True
    timeout_seconds: float = 5


def default_tools():
    # 文档工具只读取阶段 3 的开发夹具；真正的解析与检索留到后续阶段接入。
    return [
        ToolDefinition(
            "get_current_time",
            "读取指定 IANA 时区的当前时间，默认 Asia/Shanghai。",
            TimeArguments,
            TimeData,
            clock,
            "session",
        ),
        ToolDefinition(
            "list_project_documents",
            "列出当前项目的开发模拟文档元数据，不读取正文。",
            ListArguments,
            DocumentList,
            list_documents,
            "project",
        ),
        ToolDefinition(
            "get_document_metadata",
            "读取当前项目内文档元数据，仅开发模拟资料，不是 RAG 证据。",
            MetadataArguments,
            DocumentMetadata,
            metadata,
            "document",
        ),
    ]


ERROR_MESSAGES = {
    ErrorCode.INVALID_ARGUMENT: "工具参数不合法，请按参数结构修正。",
    ErrorCode.PERMISSION_DENIED: "无权访问该项目或文档。",
    ErrorCode.TOOL_TIMEOUT: "工具执行超时，请稍后重试。",
    ErrorCode.RATE_LIMITED: "工具服务限流，请稍后重试。",
    ErrorCode.SERVICE_UNAVAILABLE: "工具服务暂时不可用。",
    ErrorCode.EMPTY_RESULT: "未找到符合条件的结果。",
    ErrorCode.TOOL_NOT_FOUND: "请求的工具不存在。",
    ErrorCode.TOOL_EXECUTION_FAILED: "工具执行失败。",
}


class ToolFailure(Exception):
    def __init__(self, code):
        self.code = code


@dataclass
class ToolExecutor:
    # 所有工具都经过同一入口，确保参数校验、鉴权、缓存和审计不会被绕过。
    context: RunContext
    emit: Callable
    definitions: list = field(default_factory=default_tools)

    def __post_init__(self):
        self.registry = {d.name: d for d in self.definitions}
        if len(self.registry) != len(self.definitions):
            raise ValueError("工具名称必须唯一")
        self.cache = {}
        self.lock = asyncio.Lock()
        self.records = []

    def langchain_tools(self):
        # LangChain 只获得工具描述和参数模式，实际调用仍回到 execute()。
        async def forbidden(**kwargs):
            raise RuntimeError("工具必须通过统一执行器调用")

        return [
            StructuredTool.from_function(
                name=d.name, description=d.description, args_schema=d.arguments, coroutine=forbidden
            )
            for d in self.definitions
        ]

    def authorize(self, definition, args):
        ctx = self.context
        # 先校验服务端上下文；模型提供的 ID 只是访问请求，不是身份凭证。
        if ctx.store:
            ctx.store.check_project(ctx.project_id, ctx.user_id)
        if definition.permission == "project":
            if not ctx.store or args.project_id != ctx.project_id:
                raise PermissionDenied
        if definition.permission == "document":
            if not ctx.store:
                raise PermissionDenied
            doc = ctx.store.document(args.document_id)
            if doc["project_id"] != ctx.project_id:
                raise PermissionDenied

    async def execute(self, request: ToolCallRequest, iteration=1):
        # 串行化同一运行的检查与执行，保证并行重复只读调用也只执行一次。
        async with self.lock:
            return await self._execute(request, iteration)

    async def _execute(self, request, iteration):
        start = perf_counter()
        ctx = self.context
        record = ToolCallRecord(
            run_id=ctx.run_id,
            trace_id="trace_" + uuid4().hex,
            tool_call_id=request.tool_call_id,
            iteration=iteration,
            tool_name=request.tool_name,
            raw_arguments=redact(request.arguments, ctx.secrets),
        )
        base = dict(
            name=request.tool_name if request.tool_name in self.registry else "[未知工具]",
            tool_call_id=request.tool_call_id,
            trace_id=record.trace_id,
            iteration=iteration,
            duration_ms=0,
        )
        await self.emit("tool_validation_started", {**base, "summary": "正在校验参数和资源权限。"})
        code = None
        data = None
        try:
            definition = self.registry.get(request.tool_name)
            if definition is None:
                raise ToolFailure(ErrorCode.TOOL_NOT_FOUND)
            try:
                args = definition.arguments.model_validate(request.arguments)
            except ValueError:
                record.argument_validation = "failed"
                raise ToolFailure(ErrorCode.INVALID_ARGUMENT) from None
            record.argument_validation = "passed"
            self.authorize(definition, args)
            record.permission_validation = "passed"
            # 缓存键包含运行、用户和项目边界，避免相同参数在不同权限域之间复用。
            key = (
                ctx.run_id,
                ctx.user_id,
                ctx.project_id,
                definition.name,
                json.dumps(args.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            )
            record.cache_hit = definition.read_only and key in self.cache
            await self.emit(
                "tool_started",
                {
                    **base,
                    "status": "running",
                    "cache_hit": record.cache_hit,
                    "summary": "命中本次运行缓存。"
                    if record.cache_hit
                    else "参数和权限校验通过，正在执行工具。",
                },
            )
            if record.cache_hit:
                # 缓存只复用数据；本次调用仍会生成独立事件和审计记录。
                data = self.cache[key].copy()
            else:
                async with asyncio.timeout(definition.timeout_seconds):
                    output = await definition.execute(args, ctx)
                if output is None:
                    raise ToolFailure(ErrorCode.EMPTY_RESULT)
                data = definition.data_model.model_validate(output).model_dump(mode="json")
                if data.get("documents") == []:
                    raise ToolFailure(ErrorCode.EMPTY_RESULT)
                data = redact(data, ctx.secrets)
                if definition.read_only:
                    # 只缓存已通过输出校验和脱敏的只读结果。
                    self.cache[key] = data.copy()
        except PermissionDenied:
            record.permission_validation = "failed"
            code = ErrorCode.PERMISSION_DENIED
        except TimeoutError:
            code = ErrorCode.TOOL_TIMEOUT
        except ToolFailure as exc:
            code = exc.code
        except Exception:
            # 未知异常对外收敛为固定错误码，避免把堆栈或敏感信息带入事件流。
            code = ErrorCode.TOOL_EXECUTION_FAILED
        result = ToolExecutionResult(
            ok=code is None,
            data=data if code is None else None,
            error=ToolExecutionError(code=code, message=ERROR_MESSAGES[code]) if code else None,
            trace_id=record.trace_id,
            duration_ms=round((perf_counter() - start) * 1000, 3),
        )
        record.result, record.error_code, record.duration_ms = result, code, result.duration_ms
        self.records.append(record)
        if ctx.store:
            # 审计库只保存脱敏后的参数摘要与执行结论。
            ctx.store.save_audit(ctx.run_id, "tool", record.model_dump(mode="json"))
        payload = {
            **base,
            "duration_ms": result.duration_ms,
            "cache_hit": record.cache_hit,
            "status": "completed" if result.ok else "failed",
            "code": code,
            "summary": "工具调用完成。" if result.ok else result.error.message,
        }
        if record.argument_validation == "failed" or record.permission_validation == "failed":
            await self.emit("tool_validation_failed", payload)
        await self.emit("tool_finished" if result.ok else "tool_failed", payload)
        return result
