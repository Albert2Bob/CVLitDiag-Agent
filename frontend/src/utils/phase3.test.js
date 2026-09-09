import { expect, it } from "vitest";
import { createSSRApp } from "vue";
import { renderToString } from "vue/server-renderer";
import AnswerContent from "../components/AnswerContent.vue";
import { checkAnswer, checkEvent } from "../services/validation";
import { applyEvent, restoreRun } from "./runState";
import { eventStatus } from "./eventStatus";

const answer = {
  status: "partial",
  summary: "回答摘要",
  claims: [{ statement: "结论", evidence_ids: [] }],
  hypotheses: [
    {
      hypothesis: "待验证假设",
      confidence: 0.8,
      validation_method: "控制变量",
    },
  ],
  experiments: [
    {
      objective: "实验目标",
      change: "修改变量",
      metrics: ["准确率"],
      success_criteria: "提升指标",
    },
  ],
  missing_information: ["缺少训练日志"],
  ignored_future_field: { nested: true },
};
const event = (sequence, type, payload = {}) => ({
  sequence,
  type,
  payload,
  run_id: "r",
  event_id: `r:${sequence}`,
  timestamp: new Date().toISOString(),
});
it.each([
  ["complete", "完整回答"],
  ["partial", "部分回答"],
  ["insufficient_evidence", "证据不足"],
])("渲染 %s 的全部字段并忽略扩展字段", async (status, label) => {
  const html = await renderToString(
    createSSRApp(AnswerContent, {
      run: {
        status: "completed",
        answer: { ...answer, status },
        evidence: [],
      },
    }),
  );
  for (const text of [
    label,
    "回答摘要",
    "结论",
    "80%",
    "控制变量",
    "实验目标",
    "修改变量",
    "准确率",
    "提升指标",
    "缺少训练日志",
  ])
    expect(html).toContain(text);
});
it("异常嵌套字段不能导致运行时校验或组件崩溃", async () => {
  for (const patch of [
    { claims: [null] },
    { hypotheses: [null] },
    { experiments: [null] },
    { summary: 7 },
  ]) {
    const invalid = { ...answer, ...patch };
    expect(checkAnswer(invalid)).toBeFalsy();
    await expect(
      renderToString(
        createSSRApp(AnswerContent, {
          run: { answer: invalid, evidence: [], status: "failed" },
        }),
      ),
    ).resolves.toContain("未完成回答");
  }
});
it("修复事件幂等归并且最终失败清除预览", () => {
  const run = {
    run_id: "r",
    status: "running",
    events: [],
    draft: "未确认内容",
  };
  const start = event(1, "output_repair_started");
  expect(checkEvent(start)).toBe(true);
  expect(applyEvent(run, start)).toBe(true);
  expect(applyEvent(run, start)).toBe(false);
  expect(run.outputPhase).toBe("repairing");
  expect(run.draft).toBe("");
  applyEvent(run, event(2, "answer_delta", { delta: "临时预览" }));
  applyEvent(run, event(3, "failed", { message: "回答校验失败" }));
  expect(run.draft).toBe("");
  expect(restoreRun({ ...run, evidence: [], answer: null }).draft).toBe("");
});
it("校验时间线按调用 ID 配对并标记权限失败", () => {
  const timeline = [
    event(1, "tool_validation_started", { tool_call_id: "a" }),
    event(2, "tool_validation_failed", { tool_call_id: "b", status: "failed" }),
    event(3, "tool_started", { tool_call_id: "a", cache_hit: true }),
  ];
  expect(eventStatus(timeline[0], 0, timeline, "running")).toBe("completed");
  expect(eventStatus(timeline[1], 1, timeline, "running")).toBe("failed");
});
