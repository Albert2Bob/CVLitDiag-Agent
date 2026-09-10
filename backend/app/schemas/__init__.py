"""阶段 3 的工具和回答契约，统一使用 Pydantic v2。"""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 通用字段约束集中放在这里，供不同契约复用，避免各处出现不一致的校验规则。
Text = Annotated[str, Field(min_length=1, max_length=4000)]
ResourceId = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[\w-]+$")]


class Contract(BaseModel):
    # 所有契约都拒绝未声明字段，并统一清理字符串首尾空白。
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ErrorCode(StrEnum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    EMPTY_RESULT = "EMPTY_RESULT"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    OUTPUT_VALIDATION_FAILED = "OUTPUT_VALIDATION_FAILED"


class ToolCallRequest(Contract):
    tool_name: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z][\w-]*$")]
    arguments: Any
    tool_call_id: Annotated[str, Field(min_length=1, max_length=200)]


class ToolExecutionError(Contract):
    code: ErrorCode
    message: Text
    details: dict = Field(default_factory=dict)


class ToolExecutionResult(Contract):
    ok: bool
    data: dict | None = None
    error: ToolExecutionError | None = None
    trace_id: str
    duration_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def consistent(self):
        # 成功结果必须携带数据，失败结果必须携带错误，避免出现含义不明的响应。
        if (self.ok and (self.data is None or self.error is not None)) or (
            not self.ok and (self.data is not None or self.error is None)
        ):
            raise ValueError("工具结果状态不一致")
        return self


class ToolCallRecord(Contract):
    # 记录工具调用的完整生命周期，便于追踪、审计和定位单次执行问题。
    run_id: str
    trace_id: str
    tool_call_id: str
    iteration: int
    tool_name: str
    raw_arguments: Any
    argument_validation: str = "not_checked"
    permission_validation: str = "not_checked"
    cache_hit: bool = False
    result: ToolExecutionResult | None = None
    error_code: ErrorCode | None = None
    duration_ms: float = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AnswerStatus(StrEnum):
    complete = "complete"
    partial = "partial"
    insufficient_evidence = "insufficient_evidence"


class Claim(Contract):
    statement: Text
    evidence_ids: list[ResourceId] = Field(default_factory=list, max_length=50)


class Hypothesis(Contract):
    hypothesis: Text
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    validation_method: Text


class Experiment(Contract):
    objective: Text
    change: Text
    metrics: list[Text] = Field(default_factory=list, max_length=30)
    success_criteria: Text


class FinalAnswer(Contract):
    # 最终回答同时保留结论、证据、假设和实验信息，方便后续展示与复核。
    status: AnswerStatus
    summary: Annotated[str, Field(min_length=1, max_length=24000)]
    claims: list[Claim] = Field(default_factory=list, max_length=100)
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=30)
    experiments: list[Experiment] = Field(default_factory=list, max_length=30)
    missing_information: list[Text] = Field(default_factory=list, max_length=50)


class DocumentMetadata(Contract):
    document_id: ResourceId
    project_id: ResourceId
    filename: Text
    file_type: Literal["pdf", "md", "txt", "csv", "json"]
    parse_status: Literal["uploaded", "parsing", "indexing", "ready", "failed", "unsupported", "mock_metadata"]
    created_at: str
    updated_at: str | None = None
    page_count: int | None = Field(default=None, ge=1)
    document_version: int = Field(default=1, ge=1)
    content_hash: str = ""
    file_size: int = Field(default=0, ge=0)
    parse_quality: str | None = None
    access_scope: str = "project"
    error_code: str | None = None
    error_message: str | None = None
    source: Literal["upload", "development_fixture"] = "upload"
