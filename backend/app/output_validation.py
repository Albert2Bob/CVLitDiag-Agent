"""最终 JSON 和引用只允许一次独立修复，候选文本不向 SSE 公开。"""

import json
import re

from pydantic import ValidationError

from .schemas import ErrorCode, FinalAnswer
from .security import redact


class OutputValidationFailed(Exception):
    """唯一一次修复后仍未取得合法最终回答。"""


def validate_answer(candidate, evidence_ids):
    if isinstance(candidate, str):
        candidate = candidate.strip()
        # 仅兼容模型常见的单层 JSON 代码块，不尝试从任意文本中猜测 JSON。
        fence = re.fullmatch(r"```(?:json)?\s*\n([\s\S]*?)\n```", candidate)
        if fence:
            candidate = fence[1]
        candidate = json.loads(candidate)
    answer = FinalAnswer.model_validate(candidate)
    # 引用只能指向本次运行真实收集到的证据，集合校验使结果可重复。
    if any(eid not in evidence_ids for claim in answer.claims for eid in claim.evidence_ids):
        raise ValueError("引用必须来自当前运行真实获得的证据")
    if not evidence_ids and answer.status != "insufficient_evidence" and not answer.missing_information:
        raise ValueError("无引用证据时必须明确填写缺失信息")
    return answer


async def finalize(
    candidate, evidence_ids, emit, repair, context=None, *, require_insufficient=False
):
    # 两轮分别对应原始输出和唯一一次修复，防止模型进入无限修复循环。
    for attempt in range(2):
        await emit("output_validation_started", {"attempt": attempt, "summary": "正在校验回答结构和引用。"})
        error = None
        try:
            answer = validate_answer(candidate, evidence_ids)
            if require_insufficient and answer.status != "insufficient_evidence":
                raise ValueError("检索为空时必须返回 insufficient_evidence")
        except ValidationError as exc:
            # 不包含输入值、异常上下文和未知字段名称，避免回显秘密。
            error = [
                {
                    "type": item["type"],
                    "field": str(item["loc"][0])
                    if item["loc"] and item["loc"][0] in FinalAnswer.model_fields
                    else "answer",
                }
                for item in exc.errors(include_input=False, include_context=False, include_url=False)
            ][:20]
        except (ValueError, TypeError, RecursionError):
            error = [
                {
                    "type": "invalid_json_or_evidence",
                    "field": "answer",
                    "message": "请检查 JSON、引用集合和无证据时的 missing_information。",
                }
            ]
        if context and context.store:
            context.store.save_audit(
                context.run_id,
                "output",
                {
                    "candidate": redact(candidate, context.secrets),
                    "attempt": attempt,
                    "repaired": attempt == 1,
                    "valid": error is None,
                    "errors": error,
                },
            )
        if error is None:
            if attempt:
                await emit(
                    "output_repair_finished", {"status": "completed", "summary": "回答格式已修复并通过校验。"}
                )
            # 只有通过结构和引用校验的摘要才会进入面向用户的增量事件。
            await emit("answer_delta", {"delta": answer.summary})
            return answer
        await emit(
            "output_validation_failed",
            {
                "attempt": attempt,
                "code": ErrorCode.OUTPUT_VALIDATION_FAILED,
                "summary": "回答结构或引用未通过校验。",
            },
        )
        if attempt:
            await emit(
                "output_repair_finished", {"status": "failed", "summary": "唯一一次修复后仍未通过校验。"}
            )
            raise OutputValidationFailed
        await emit("output_repair_started", {"summary": "正在修复回答格式（仅一次）。"})
        # 修复调用只接收安全错误摘要和目标结构，也不具备任何工具能力。
        candidate = await repair(
            json.dumps(
                {
                    "instruction": "仅修复以下候选结果。只返回符合目标 Schema 的 JSON，不执行任何工具，不添加新事实。无证据时填写 missing_information 或使用 insufficient_evidence。",
                    "candidate": candidate,
                    "errors": error,
                    "schema": FinalAnswer.model_json_schema(),
                    "allowed_evidence_ids": sorted(evidence_ids),
                    "allowed_evidence": [
                        {
                            "evidence_id": item["evidence_id"],
                            "document_name": item["document_name"],
                            "page_number": item.get("page_number"),
                            "section": item.get("section", ""),
                            "snippet": item["snippet"][:500],
                        }
                        for item in (context.store.run_evidence(context.run_id) if context and context.store else [])
                        if item["evidence_id"] in evidence_ids
                    ],
                },
                ensure_ascii=False,
            )
        )
