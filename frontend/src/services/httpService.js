import { mockService } from "../mocks/service";
import { request } from "./apiClient";
import { subscribeSSE } from "./sseClient";
const enc = encodeURIComponent;
// 第三阶段后端路由；文档控制功能仍为本地演示。
export const httpService = {
  scenarios: async () => [],
  listProjects: () => request("/api/projects"),
  createProject: (body) => request("/api/projects", { method: "POST", body }),
  listThreads: (project_id) =>
    request(`/api/projects/${enc(project_id)}/threads`),
  createThread: (body) => request("/api/threads", { method: "POST", body }),
  getMessages: (thread_id) =>
    request(`/api/threads/${enc(thread_id)}/messages`),
  listDocuments: mockService.listDocuments,
  getDocument: mockService.getDocument,
  deleteDocument: mockService.deleteDocument,
  uploadDocument: (project_id, file, fail = false) =>
    mockService.uploadDocument(project_id, file, fail, true),
  createRun: ({ project_id, thread_id, user_id, question }) =>
    request("/api/runs", {
      method: "POST",
      body: { project_id, thread_id, user_id, question },
    }),
  getRun: (run_id) => request(`/api/runs/${enc(run_id)}`),
  cancelRun: (run_id) =>
    request(`/api/runs/${enc(run_id)}/cancel`, { method: "POST" }),
  subscribe: subscribeSSE,
};
