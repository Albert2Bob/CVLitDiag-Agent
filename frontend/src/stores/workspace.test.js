import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { service } from "../services";
import { useWorkspace } from "./workspace";
vi.mock("../services", () => ({
  isMock: false,
  service: {
    listThreads: vi.fn(),
    listDocuments: vi.fn(),
    getMessages: vi.fn(),
    getRun: vi.fn(),
    createThread: vi.fn(),
    createRun: vi.fn(),
    cancelRun: vi.fn(),
    subscribe: vi.fn(),
  },
}));
const deferred = () => {
  let resolve;
  const promise = new Promise((r) => {
    resolve = r;
  });
  return { promise, resolve };
};
const snapshot = (status = "running") => ({
  run_id: "r",
  project_id: "p",
  thread_id: "a",
  question: "q",
  status,
  answer: null,
  events: [],
  evidence: [],
  error: null,
});
const message = {
  message_id: "m",
  project_id: "p",
  thread_id: "a",
  run_id: "r",
  role: "user",
  content: "q",
};
beforeEach(() => {
  vi.resetAllMocks();
  const data = new Map();
  vi.stubGlobal("localStorage", {
    getItem: (k) => data.get(k),
    setItem: (k, v) => data.set(k, v),
  });
  setActivePinia(createPinia());
  service.listThreads.mockResolvedValue(
    ["a", "b"].map((thread_id) => ({
      thread_id,
      project_id: "p",
      title: thread_id,
    })),
  );
  service.listDocuments.mockResolvedValue([]);
  service.getMessages.mockResolvedValue([]);
  service.subscribe.mockReturnValue(vi.fn());
});
afterEach(() => vi.unstubAllGlobals());
it("restores the selected empty thread after a fresh store and respects explicit navigation", async () => {
  const store = useWorkspace();
  await store.selectProject("p");
  await store.selectThread("b");
  setActivePinia(createPinia());
  const fresh = useWorkspace();
  await fresh.selectProject("p");
  expect(fresh.threadId).toBe("b");
  await fresh.selectProject("p", "a");
  expect(fresh.threadId).toBe("a");
});
it("ignores delayed message responses after thread switches", async () => {
  const store = useWorkspace();
  store.projectId = "p";
  const pending = deferred();
  service.getMessages.mockReturnValueOnce(pending.promise);
  const first = store.selectThread("a");
  await store.selectThread("b");
  pending.resolve([message]);
  await first;
  expect(store.threadId).toBe("b");
  expect(store.messages).toEqual([]);
  expect(service.getRun).not.toHaveBeenCalled();
  expect(store.loading).toBe(false);
});
it("does not install stale snapshots or subscriptions after navigation", async () => {
  const store = useWorkspace();
  store.projectId = "p";
  const pending = deferred();
  service.getMessages.mockResolvedValueOnce([message]);
  service.getRun.mockReturnValueOnce(pending.promise);
  const first = store.selectThread("a");
  await vi.waitFor(() => expect(service.getRun).toHaveBeenCalled());
  await store.selectThread("b");
  pending.resolve(snapshot());
  await first;
  expect(store.runs).toEqual({});
  expect(service.subscribe).not.toHaveBeenCalled();
});
it("renders a running answer when only the user message is saved, without duplicating saved assistants", async () => {
  const store = useWorkspace();
  store.projectId = "p";
  service.getMessages.mockResolvedValue([message]);
  service.getRun.mockResolvedValue(snapshot());
  await store.selectThread("a");
  expect(store.displayMessages.map((m) => m.role)).toEqual([
    "user",
    "assistant",
  ]);
  store.messages.push({
    ...message,
    message_id: "assistant",
    role: "assistant",
    content: "answer",
  });
  expect(store.displayMessages).toHaveLength(2);
});
it("a pending recovery cannot reopen a cancelled run", async () => {
  const store = useWorkspace();
  const pending = deferred();
  service.getRun.mockReturnValue(pending.promise);
  const recovery = store.recover("r");
  service.cancelRun.mockResolvedValue(snapshot("cancelled"));
  await store.cancel("r");
  pending.resolve(snapshot());
  await recovery;
  expect(store.runs.r.status).toBe("cancelled");
  expect(service.subscribe).not.toHaveBeenCalled();
});
it("does not send a question to another thread after delayed thread creation", async () => {
  const store = useWorkspace();
  store.projectId = "p";
  store.user = { user_id: "u" };
  const pending = deferred();
  service.createThread.mockReturnValue(pending.promise);
  const sending = store.send("question");
  await store.selectThread("b");
  pending.resolve({ thread_id: "a", project_id: "p", title: "a" });
  await sending;
  expect(service.createRun).not.toHaveBeenCalled();
  expect(store.threadId).toBe("b");
});
