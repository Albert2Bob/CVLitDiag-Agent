import { expect, it } from "vitest";
import { applyEvent, restoreRun } from "./runState";
import { assertRun, checkEvent } from "../services/validation";
import { eventStatus } from "./eventStatus";
const base = {
  run_id: "r",
  thread_id: "t",
  project_id: "p",
  question: "q",
  status: "running",
  answer: null,
  evidence: [],
  events: [],
  error: null,
};
const event = (sequence, type, payload) => ({
  event_id: `e${sequence}`,
  run_id: "r",
  sequence,
  type,
  timestamp: new Date().toISOString(),
  payload,
});
it("replays text deltas and accepts authoritative string completions with no evidence", () => {
  const delta = event(1, "answer_delta", { delta: "partial" });
  const run = restoreRun(assertRun({ ...base, events: [delta] }));
  expect(run.status).toBe("running");
  expect(run.draft).toBe("partial");
  expect(applyEvent(run, delta)).toBe(false);
  applyEvent(
    run,
    event(2, "completed", {
      answer: "# Final answer",
      status: "completed",
      evidence: [],
    }),
  );
  expect(run.answer).toBe("# Final answer");
  expect(run.draft).toBe("");
  expect(restoreRun(assertRun(run)).answer).toBe("# Final answer");
  expect(
    restoreRun({ ...base, status: "completed", answer: "", events: [] }).status,
  ).toBe("completed");
});
it("accepts model and tool events and pairs overlapping calls by identity", () => {
  const timeline = [
    event(1, "tool_started", {
      tool_call_id: "a",
      name: "search",
      arguments: {},
    }),
    event(2, "tool_started", {
      tool_call_id: "b",
      name: "search",
      arguments: {},
    }),
    event(3, "tool_failed", {
      tool_call_id: "b",
      status: "failed",
      message: "unavailable",
      duration_ms: 30,
    }),
  ];
  expect(timeline.every(checkEvent)).toBe(true);
  expect(eventStatus(timeline[0], 0, timeline, "running")).toBe("running");
  expect(eventStatus(timeline[1], 1, timeline, "running")).toBe("failed");
  const model = [
    event(1, "model_started", { iteration: 1 }),
    event(2, "model_finished", {
      iteration: 2,
      status: "completed",
      duration_ms: 20,
    }),
  ];
  expect(model.every(checkEvent)).toBe(true);
  expect(eventStatus(model[0], 0, model, "running")).toBe("running");
});
it("does not treat a recoverable tool failure as a terminal run failure", () => {
  const run = restoreRun(base);
  applyEvent(
    run,
    event(1, "tool_failed", {
      tool_call_id: "a",
      name: "search",
      message: "failed",
      status: "failed",
    }),
  );
  expect(run.status).toBe("running");
  applyEvent(
    run,
    event(2, "completed", {
      answer: "fallback",
      status: "completed",
      evidence: [],
    }),
  );
  expect(run.status).toBe("completed");
});
