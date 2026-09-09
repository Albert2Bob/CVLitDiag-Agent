import { mockService } from "../mocks/service";
import { httpService } from "./httpService";
import { assertList, assertRun } from "./validation";
export const isMock = import.meta.env.VITE_MOCK === "true";
const adapter = isMock ? mockService : httpService;
const lists = {
  listProjects: ["project_id", "name"],
  listThreads: ["thread_id", "project_id", "title"],
  getMessages: ["message_id", "thread_id", "project_id", "role", "run_id"],
  listDocuments: ["document_id", "project_id", "name", "type", "status"],
};
export const service = { ...adapter };
for (const [method, keys] of Object.entries(lists))
  service[method] = async (...args) =>
    assertList(await adapter[method](...args), keys);
for (const method of ["createRun", "getRun", "cancelRun"])
  service[method] = async (...args) =>
    assertRun(await adapter[method](...args));
for (const [method, keys] of Object.entries({
  createProject: ["project_id", "name"],
  createThread: ["thread_id", "project_id", "title"],
  getDocument: ["document_id", "project_id", "name", "status"],
  uploadDocument: ["document_id", "project_id", "name", "status"],
}))
  service[method] = async (...args) =>
    assertList([await adapter[method](...args)], keys)[0];

service.getMessages = async (...args) => {
  const messages = assertList(
    await adapter.getMessages(...args),
    lists.getMessages,
  );
  if (
    !messages.every(
      (m) =>
        ["user", "assistant"].includes(m.role) && typeof m.content === "string",
    )
  )
    throw new Error("消息响应格式不完整。");
  return messages;
};
