"""仅供测试使用的 OpenAI 兼容流式服务器；生产应用绝不会导入它。

在 8011 端口启动，并使用虚拟密钥将测试后端指向该服务器。方括号标记用于选择
确定性的传输夹具。这里不模拟真实的模型决策。
"""

import asyncio
import json
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()
requests_seen = []


@app.get("/stats")
async def stats():
    return {"calls": len(requests_seen), "tools_returned": sum(r["has_tool"] for r in requests_seen)}


@app.post("/chat/completions")
async def chat(request: Request):
    body = await request.json()
    if body.get("response_format") != {"type": "json_object"}:
        return JSONResponse(status_code=400, content={"error": {"message": "测试要求 JSON 模式"}})
    messages = body["messages"]
    question = next(m["content"] for m in reversed(messages) if m["role"] == "user")
    has_tool = messages[-1]["role"] == "tool"
    requests_seen.append({"has_tool": has_tool})
    if "[AUTH]" in question:
        return JSONResponse(
            status_code=401,
            content={"error": {"message": "test credential rejected", "type": "authentication_error"}},
        )
    if "[RATE]" in question:
        return JSONResponse(
            status_code=429, content={"error": {"message": "test limited", "type": "rate_limit_error"}}
        )
    message_id = "chatcmpl-" + uuid4().hex

    def frame(delta, finish_reason=None):
        return (
            "data: "
            + json.dumps(
                {
                    "id": message_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": body["model"],
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )

    async def generate():
        if "[SLOW]" in question:
            await asyncio.sleep(15)
        yield frame({"role": "assistant", "content": ""})
        # 验证公开映射器会忽略这个意外出现的提供商私有字段。
        yield frame({"reasoning_content": "PRIVATE_TEST_DRAFT_MUST_NOT_LEAK"})
        if any(tag in question for tag in ("[TOOL]", "[CACHE]", "[INVALID]", "[DENIED]")) and (
            not has_tool or ("[CACHE]" in question and sum(m["role"] == "tool" for m in messages) < 2)
        ):
            yield frame(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_" + uuid4().hex,
                            "type": "function",
                            "function": {
                                "name": "get_document_metadata"
                                if "[DENIED]" in question
                                else "get_current_time",
                                "arguments": "",
                            },
                        }
                    ]
                }
            )
            arguments = (
                {"document_id": "forged_document"}
                if "[DENIED]" in question
                else {"timezone": "invalid/zone" if "[INVALID]" in question else "Asia/Shanghai"}
            )
            yield frame({"tool_calls": [{"index": 0, "function": {"arguments": json.dumps(arguments)}}]})
            yield frame({}, "tool_calls")
        else:
            text = (
                ("时间工具已返回：" + messages[-1]["content"])
                if has_tool
                else "你好！这是通过真实 HTTP、LangChain Agent 和 SSE 传输的可控测试回答。"
            )
            repairing = "只修复 JSON" in messages[0]["content"]
            text = json.dumps(
                {
                    "status": "partial"
                    if "[PARTIAL]" in question
                    else "insufficient_evidence"
                    if "[INSUFFICIENT]" in question
                    else "complete",
                    "summary": "时间工具查询完成。" if has_tool else text,
                    "claims": [{"statement": "这是可控传输测试结果。", "evidence_ids": []}],
                    "hypotheses": [
                        {"hypothesis": "示例假设", "confidence": 0.8, "validation_method": "对照实验"}
                    ],
                    "experiments": [
                        {
                            "objective": "验证示例",
                            "change": "单一变量",
                            "metrics": ["准确率"],
                            "success_criteria": "达到基线",
                        }
                    ],
                    "missing_information": ["开发测试，无文献证据"],
                },
                ensure_ascii=False,
            )
            if "[BAD]" in question or ("[REPAIR]" in question and not repairing):
                text = "{invalid [BAD]" if "[BAD]" in question else "{invalid [REPAIR]"
            for start in range(0, len(text), 20):
                yield frame({"content": text[start : start + 20]})
                await asyncio.sleep(0.04)
            yield frame({}, "stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
