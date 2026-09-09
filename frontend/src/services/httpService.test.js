import { createPinia, setActivePinia } from "pinia";
import { useWorkspace } from "../stores/workspace";
import { afterEach, expect, it, vi } from "vitest";
import { httpService } from "./httpService";
import { isMock, service } from "./index";
afterEach(() => vi.unstubAllGlobals());
it("defaults to real backend and passes full run snapshots through unchanged", async () => {
  expect(isMock).toBe(false);
  const snapshot = {
    run_id: "r",
    thread_id: "t",
    project_id: "p",
    question: "q",
    status: "completed",
    answer: "text",
    events: [],
    evidence: [],
    error: null,
  };
  const fetch = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => snapshot });
  vi.stubGlobal("fetch", fetch);
  expect(
    await service.createRun({
      project_id: "p",
      thread_id: "t",
      user_id: "u",
      question: "q",
      scenario: "paper",
    }),
  ).toEqual(snapshot);
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
    project_id: "p",
    thread_id: "t",
    user_id: "u",
    question: "q",
  });
  expect(await service.getRun("r")).toEqual(snapshot);
  expect(await service.cancelRun("r")).toEqual(snapshot);
  expect(fetch.mock.calls.map(([url]) => new URL(url).pathname)).toEqual([
    "/api/runs",
    "/api/runs/r",
    "/api/runs/r/cancel",
  ]);
});
it("uses the project, thread and message routes and validates message content", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
  vi.stubGlobal("fetch", fetch);
  await httpService.listProjects();
  await httpService.createProject({ name: "n" });
  await httpService.listThreads("p/a");
  await httpService.createThread({ project_id: "p" });
  await service.getMessages("t");
  expect(fetch.mock.calls.map(([url]) => new URL(url).pathname)).toEqual([
    "/api/projects",
    "/api/projects",
    "/api/projects/p%2Fa/threads",
    "/api/threads",
    "/api/threads/t/messages",
  ]);
  fetch.mockResolvedValue({
    ok: true,
    json: async () => [
      {
        message_id: "m",
        project_id: "p",
        thread_id: "t",
        run_id: "r",
        role: "assistant",
        content: {},
      },
    ],
  });
  await expect(service.getMessages("t")).rejects.toThrow();
});
it("keeps document uploads local even for real backend project IDs", async () => {
  const data = new Map();
  vi.stubGlobal("localStorage", {
    getItem: (k) => data.get(k),
    setItem: (k, v) => data.set(k, v),
  });
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const doc = await httpService.uploadDocument("backend-project", {
    name: "notes.txt",
    size: 10,
  });
  expect(doc.project_id).toBe("backend-project");
  expect(await httpService.listDocuments("backend-project")).toHaveLength(1);
  await httpService.deleteDocument(doc.document_id);
  expect(await httpService.listDocuments("backend-project")).toEqual([]);
  expect(fetch).not.toHaveBeenCalled();
});

it("selectProject loads backend threads when the project is absent from local demo data", async () => {
  const data = new Map();
  vi.stubGlobal("localStorage", {
    getItem: (k) => data.get(k),
    setItem: (k, v) => data.set(k, v),
  });
  const pid = "backend-generated-unknown-id";
  const fetch = vi.fn(async (url) => ({
    ok: true,
    json: async () =>
      new URL(url).pathname.endsWith("/threads")
        ? [{ project_id: pid, thread_id: "backend-thread", title: "Chat" }]
        : [],
  }));
  vi.stubGlobal("fetch", fetch);
  setActivePinia(createPinia());
  const store = useWorkspace();
  await store.selectProject(pid);
  expect(store.error).toBe("");
  expect(store.threadId).toBe("backend-thread");
  expect(store.documents).toEqual([]);
  expect(store.loading).toBe(false);
  expect(fetch.mock.calls.map(([url]) => new URL(url).pathname)).toEqual([
    `/api/projects/${pid}/threads`,
    "/api/threads/backend-thread/messages",
  ]);
});
