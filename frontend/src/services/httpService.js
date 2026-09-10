import { request } from "./apiClient";
import { subscribeSSE } from "./sseClient";
const enc = encodeURIComponent;
const documentView = (doc) => ({
  ...doc,
  name: doc.filename,
  type: doc.file_type,
  status: doc.parse_status,
});
// 文档字段在适配层映射，组件无需感知后端持久化命名。
export const httpService = {
  scenarios: async () => [],
  listProjects: () => request("/api/projects"),
  createProject: (body) => request("/api/projects", { method: "POST", body }),
  listThreads: (project_id) =>
    request(`/api/projects/${enc(project_id)}/threads`),
  createThread: (body) => request("/api/threads", { method: "POST", body }),
  getMessages: (thread_id) =>
    request(`/api/threads/${enc(thread_id)}/messages`),
  listDocuments: async (project_id) =>
    (await request(`/api/projects/${enc(project_id)}/documents`)).map(documentView),
  getDocument: async (document_id) =>
    documentView(await request(`/api/documents/${enc(document_id)}`)),
  deleteDocument: (document_id) =>
    request(`/api/documents/${enc(document_id)}`, { method: "DELETE" }),
  uploadDocument: async (project_id, file) => {
    const body = new FormData();
    body.append("file", file);
    return documentView(
      await request(`/api/projects/${enc(project_id)}/documents`, {
        method: "POST",
        body,
      }),
    );
  },
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
