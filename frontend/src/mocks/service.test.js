import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockService } from "./service";
const request = {
  user_id: "demo_researcher",
  project_id: "project_vision",
  thread_id: "project_vision_welcome",
  question: "解释残差连接",
  scenario: "paper",
};
beforeEach(() => {
  const storage = new Map();
  vi.stubGlobal("localStorage", {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
  });
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-08T08:00:00Z"));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
describe("durable Mock lifecycle", () => {
  it("cancels durably, stops timers and never emits later answer chunks", async () => {
    const run = await mockService.createRun(request),
      seen = [];
    mockService.subscribe(run.run_id, {
      onEvent: (e) => seen.push(e),
      onConnection: () => {},
      onError: (e) => {
        throw e;
      },
    });
    await vi.advanceTimersByTimeAsync(4200);
    expect(seen.some((e) => e.type === "answer_delta")).toBe(true);
    await mockService.cancelRun(run.run_id);
    await vi.advanceTimersByTimeAsync(100);
    const length = seen.length;
    expect(seen.at(-1).type).toBe("cancelled");
    await vi.advanceTimersByTimeAsync(60000);
    expect(seen.length).toBe(length);
    expect((await mockService.getRun(run.run_id)).status).toBe("cancelled");
    expect(vi.getTimerCount()).toBe(0);
  });
  it("restores after offline time without creating a second task and regenerates a new ID", async () => {
    const first = await mockService.createRun(request);
    vi.setSystemTime(Date.now() + 60000);
    const restored = await mockService.getRun(first.run_id);
    expect(restored.status).toBe("completed");
    expect((await mockService.getMessages(request.thread_id)).length).toBe(2);
    const second = await mockService.createRun(request);
    expect(second.run_id).not.toBe(first.run_id);
    expect((await mockService.getMessages(request.thread_id)).length).toBe(4);
  });
  it("rejects cross-project threads and isolates documents and histories", async () => {
    await expect(
      mockService.createRun({ ...request, project_id: "project_medical" }),
    ).rejects.toThrow("不属于");
    const docs = await mockService.listDocuments("project_medical");
    expect(docs.every((d) => d.project_id === "project_medical")).toBe(true);
    expect(await mockService.getMessages("project_medical_welcome")).toEqual(
      [],
    );
  });
  it("manual unsubscribe releases the timer but task continues on the durable clock", async () => {
    const run = await mockService.createRun(request);
    const stop = mockService.subscribe(run.run_id, {
      onEvent: () => {},
      onConnection: () => {},
      onError: () => {},
    });
    await vi.advanceTimersByTimeAsync(700);
    stop();
    expect(vi.getTimerCount()).toBe(0);
    vi.setSystemTime(Date.now() + 60000);
    expect((await mockService.getRun(run.run_id)).status).toBe("completed");
  });
});
