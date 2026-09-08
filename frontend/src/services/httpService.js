import { request } from "./apiClient";
import { subscribeSSE } from "./sseClient";
const enc = encodeURIComponent;
// List routes below are suggestions, not implemented backend capabilities. See README.
export const httpService = {
  scenarios: async () => [],
  listProjects: () => request("/api/projects"),
  createProject: (body) => request("/api/projects", { method: "POST", body }),
  listThreads: (project_id) =>
    request(`/api/projects/${enc(project_id)}/threads`),
  createThread: (body) => request("/api/threads", { method: "POST", body }),
  getMessages: (thread_id) =>
    request(`/api/threads/${enc(thread_id)}/messages`),
  listDocuments: (project_id) =>
    request(`/api/projects/${enc(project_id)}/documents`),
  getDocument: (document_id) => request(`/api/documents/${enc(document_id)}`),
  deleteDocument: (document_id) =>
    request(`/api/documents/${enc(document_id)}`, { method: "DELETE" }),
  uploadDocument: (project_id, file) => {
    const body = new FormData();
    body.append("file", file);
    return request(`/api/projects/${enc(project_id)}/documents`, {
      method: "POST",
      body,
    });
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
