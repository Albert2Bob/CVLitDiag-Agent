import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { subscribeSSE } from "./sseClient";
let source;
beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("window", { location: { origin: "http://localhost:5173" } });
  vi.stubGlobal(
    "EventSource",
    class {
      constructor(url, options) {
        this.url = url;
        this.options = options;
        this.listeners = {};
        this.close = vi.fn();
        source = this;
      }
      addEventListener(type, fn) {
        this.listeners[type] = fn;
      }
    },
  );
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
it("uses a query cursor for new connections, ignores malformed messages and closes on termination", () => {
  const onEvent = vi.fn(),
    onError = vi.fn(),
    onConnection = vi.fn();
  subscribeSSE("r1", { onEvent, onError, onConnection }, "e7");
  expect(source.url.searchParams.get("last_event_id")).toBe("e7");
  expect(source.options).toEqual({ withCredentials: true });
  source.onmessage({ data: "{bad json" });
  source.onmessage({ data: JSON.stringify({ type: "unknown" }) });
  expect(onError).toHaveBeenCalledTimes(2);
  expect(onEvent).not.toHaveBeenCalled();
  source.listeners.cancelled({
    data: JSON.stringify({
      event_id: "e8",
      run_id: "r1",
      sequence: 8,
      timestamp: new Date().toISOString(),
      type: "cancelled",
      payload: {},
    }),
  });
  expect(source.close).toHaveBeenCalledOnce();
  expect(vi.getTimerCount()).toBe(0);
});
it("handles interruption without task submission and bounds an unresponsive connection", () => {
  const onConnection = vi.fn(),
    onError = vi.fn();
  subscribeSSE("r1", { onEvent: vi.fn(), onConnection, onError });
  source.onerror();
  expect(onConnection).toHaveBeenCalledWith("reconnecting");
  source.onopen();
  expect(onConnection).toHaveBeenCalledWith("connected");
  vi.advanceTimersByTime(45000);
  expect(source.close).toHaveBeenCalledOnce();
  expect(onError).toHaveBeenCalledOnce();
  expect(vi.getTimerCount()).toBe(0);
});
