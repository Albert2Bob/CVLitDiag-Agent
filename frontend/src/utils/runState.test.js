import { describe, it, expect } from "vitest";
import { applyEvent, restoreRun } from "./runState";
import { buildSchedule } from "../mocks/service";
import { resultFor, seed } from "../mocks/data";
import { renderMarkdown } from "./markdown";
const base = () => ({
  run_id: "r1",
  project_id: "project_vision",
  thread_id: "t1",
  started_at: 1000000,
  scenario: "paper",
  status: "queued",
  events: [],
  evidence: [],
  answer: null,
  sequence: 0,
  draft: "",
});
const event = (sequence, type, payload = {}) => ({
  event_id: `e${sequence}`,
  run_id: "r1",
  sequence,
  timestamp: new Date(1000000 + sequence).toISOString(),
  type,
  payload,
});
describe("event reducer and recovery", () => {
  it("deduplicates IDs and ignores wrong task, unknown, malformed and old events", () => {
    const r = base();
    const e = event(1, "answer_delta", { delta: "hello" });
    expect(applyEvent(r, e)).toBe(true);
    for (const invalid of [
      e,
      { ...e, event_id: "different" },
      { ...event(2, "answer_delta", { delta: "bad" }), run_id: "other" },
      event(2, "unknown"),
      event(2, "answer_delta", {}),
    ])
      expect(applyEvent(r, invalid)).toBe(false);
    expect(r.draft).toBe("hello");
  });
  it.each(["cancelled", "failed", "completed"])(
    "does not reopen %s",
    (status) => {
      const r = base();
      const result = resultFor(r, seed().documents);
      applyEvent(
        r,
        event(1, status, status === "completed" ? result : { message: "stop" }),
      );
      expect(applyEvent(r, event(2, "answer_delta", { delta: "late" }))).toBe(
        false,
      );
      expect(r.status).toBe(status);
    },
  );
  it("replays a deterministic prefix on refresh and resumes without duplicate text", () => {
    const r = base();
    const schedule = buildSchedule(r, resultFor(r, seed().documents));
    for (const e of schedule.slice(0, 12)) applyEvent(r, e);
    const recovered = restoreRun(JSON.parse(JSON.stringify(r)));
    expect(recovered.draft).toBe(r.draft);
    for (const e of schedule) applyEvent(recovered, e);
    expect(recovered.status).toBe("completed");
    expect(recovered.draft).toBe("");
    expect(recovered.events.length).toBe(schedule.length);
    expect(recovered.answer.summary).toContain("残差连接");
    expect(buildSchedule(base(), resultFor(base(), seed().documents))).toEqual(
      schedule,
    );
  });
  it("rejects evidence belonging to another project or missing references", () => {
    const r = base(),
      result = resultFor(r, seed().documents);
    result.evidence[0].project_id = "other";
    applyEvent(r, event(1, "completed", result));
    expect(r.status).toBe("failed");
    expect(r.answer).toBeNull();
  });
  it("does not invent evidence from user uploads or another project", () => {
    const r = { ...base(), project_id: "project_medical" };
    const result = resultFor(r, seed().documents);
    expect(result.answer.status).toBe("insufficient_evidence");
    expect(result.evidence).toEqual([]);
  });
  it("validates the authoritative final snapshot again during refresh", () => {
    const r = base(),
      result = resultFor(r, seed().documents);
    const recovered = restoreRun({
      ...r,
      ...result,
      status: "completed",
      evidence: [],
      events: [null, { type: "unknown" }],
    });
    expect(recovered.status).toBe("failed");
    expect(recovered.answer).toBeNull();
  });
  it("escapes HTML and unsafe links while retaining tables and code blocks", () => {
    const html = renderMarkdown(
      "<img src=x onerror=alert(1)>\n\n[x](javascript:alert(1))\n\n| A | B |\n|---|---|\n|1|2|\n\n```js\nalert(1)\n```",
    );
    expect(html).not.toContain("<img");
    expect(html).not.toContain('href="javascript:');
    expect(html).toContain("<table>");
    expect(html).toContain("<pre>");
  });
});
