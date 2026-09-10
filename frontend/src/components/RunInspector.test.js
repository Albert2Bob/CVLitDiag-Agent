import { expect, it, vi } from "vitest";
import { createSSRApp } from "vue";
import { renderToString } from "vue/server-renderer";
import { briefSummary, formatDuration } from "../utils/executionDisplay";
import RunInspector from "./RunInspector.vue";
const { store } = vi.hoisted(() => ({
  store: {
    evidenceId: "",
    selectedRunId: "r",
    connections: { r: "connected" },
    warnings: {},
    currentRun: {
      run_id: "r",
      status: "running",
      question: "q",
      evidence: [],
      events: [
        {
          event_id: "e",
          type: "tool_finished",
          payload: {
            name: "search",
            tool_call_id: "call-unique",
            arguments: { query: "<script>" },
            summary: "safe result ".repeat(30),
            duration_ms: 0.2,
          },
        },
      ],
    },
  },
}));
vi.mock("../stores/workspace", () => ({ useWorkspace: () => store }));
vi.mock("../services", () => ({ isMock: false }));
it("defaults real mode to execution with collapsed safe tool details and manual disconnect", async () => {
  const html = await renderToString(createSSRApp(RunInspector));
  expect(html).toContain("真实执行事件摘要，不是模型隐藏思维链");
  expect(html).toMatch(/class="selected">\s*执行过程/);
  expect(html).toContain("断开连接");
  expect(html).not.toContain("模拟断线");
  expect(html).toContain("&lt;1 ms");
  const details = html.match(/<details>([\s\S]*?)<\/details>/)?.[1];
  expect(details).toContain("参数与结果");
  expect(details).toContain("call-unique");
  expect(details).toContain("safe result ".repeat(30));
  expect(html.replace(/<details>[\s\S]*?<\/details>/g, "")).not.toContain(
    "call-unique",
  );
  expect(html).not.toContain("<script>");
  expect(html).not.toContain("<details open");
});
it("keeps brief summaries bounded and small durations readable", () => {
  expect(briefSummary("a".repeat(200))).toBe("a".repeat(120) + "…");
  expect([0, 0.4, 1, 12.3, 1250].map(formatDuration)).toEqual([
    "<1 ms",
    "<1 ms",
    "1 ms",
    "12.3 ms",
    "1.25 秒",
  ]);
});


it("renders real evidence sections and page ranges without demo wording", async () => {
  store.evidenceId = "e1";
  store.currentRun = {
    ...store.currentRun,
    status: "completed",
    evidence: [
      {
        evidence_id: "e1",
        document_name: "paper.pdf",
        section: "Experiments",
        page_number: 3,
        page_end: 4,
        snippet: "真实保存的证据片段",
      },
    ],
  };
  const html = await renderToString(createSSRApp(RunInspector));
  expect(html).toContain("Experiments");
  expect(html).toContain("第 3–4 页");
  expect(html).toContain("真实保存的证据片段");
  expect(html).not.toContain("人工编写的演示数据");
});
