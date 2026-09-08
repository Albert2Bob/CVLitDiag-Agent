import { seed, resultFor, SCENARIOS } from "./data";
import { readLocal, writeLocal } from "../utils/storage";
import { applyEvent } from "../utils/runState";
import { TERMINAL, FILE_TYPES } from "../constants/contracts";
const KEY = "vision-research.mock.v1";
const clone = (x) => JSON.parse(JSON.stringify(x));
const id = (prefix) => `${prefix}_${crypto.randomUUID()}`;
const load = () => {
  const d = readLocal(KEY, null);
  return d?.version === 1 ? d : seed();
};
const save = (d) => writeLocal(KEY, d);
function need(list, key, value) {
  const item = list.find((x) => x[key] === value);
  if (!item) throw new Error("记录不存在或已删除。");
  return item;
}
/** Fixed timestamps and durable event IDs make reload/reconnect replay deterministic. */
export function buildSchedule(run, result) {
  const schedule = [];
  const add = (offset, type, payload = {}) =>
    schedule.push({
      event_id: `${run.run_id}:${schedule.length + 1}`,
      run_id: run.run_id,
      sequence: schedule.length + 1,
      timestamp: new Date(run.started_at + offset).toISOString(),
      type,
      payload,
    });
  add(100, "run_started");
  add(500, "skill_selected", {
    name: SCENARIOS.find((s) => s.id === run.scenario)?.skill || "paper-qa",
  });
  add(900, "skill_loaded", { name: "科研分析流程", duration_ms: 400 });
  add(1400, "retrieval_started", { name: "查找项目演示资料" });
  add(2100, "retrieval_finished", {
    name: `找到 ${result.evidence.length} 条演示证据`,
    duration_ms: 700,
  });
  add(2600, "tool_started", { name: "整理证据片段" });
  if (run.scenario === "failure") {
    add(3400, "validation_failed", {
      name: "工具结果不完整",
      duration_ms: 800,
    });
    add(4100, "failed", {
      message:
        "演示工具暂时不可用。可重新生成以重试本场景，或切换其他场景继续探索。",
    });
    return schedule;
  }
  add(3300, "tool_finished", { name: "证据整理完成", duration_ms: 700 });
  add(3500, "heartbeat");
  const chunks = result.answer.summary.match(/[\s\S]{1,16}/g) || [];
  chunks.forEach((delta, i) => add(3700 + i * 160, "answer_delta", { delta }));
  add(3900 + chunks.length * 160, "completed", {
    answer: result.answer,
    evidence: result.evidence,
    name: "回答与引用校验完成",
    duration_ms: 200,
  });
  return schedule;
}
function advance(db, run, now = Date.now()) {
  if (!TERMINAL.includes(run.status))
    for (const e of run.schedule)
      if (Date.parse(e.timestamp) <= now) applyEvent(run, e);
  return run;
}
function documents(db) {
  return db.documents.map((d) => {
    if (d.uploaded_at) {
      const age = Date.now() - d.uploaded_at;
      d.status =
        age < 700
          ? "uploading"
          : age < 1900
            ? "parsing"
            : d.should_fail
              ? "failed"
              : "ready";
    }
    return d;
  });
}
export const mockService = {
  scenarios: () => Promise.resolve(clone(SCENARIOS)),
  async listProjects() {
    return clone(load().projects);
  },
  async createProject({ name }) {
    const db = load();
    const p = {
      project_id: id("project"),
      name,
      description: "新的独立科研空间",
    };
    db.projects.push(p);
    save(db);
    return clone(p);
  },
  async listThreads(project_id) {
    return clone(load().threads.filter((t) => t.project_id === project_id));
  },
  async createThread({ project_id }) {
    const db = load();
    need(db.projects, "project_id", project_id);
    const t = { thread_id: id("thread"), project_id, title: "新的科研对话" };
    db.threads.push(t);
    save(db);
    return clone(t);
  },
  async getMessages(thread_id) {
    return clone(load().messages.filter((m) => m.thread_id === thread_id));
  },
  async listDocuments(project_id) {
    const db = load();
    const docs = documents(db).filter((d) => d.project_id === project_id);
    save(db);
    return clone(docs);
  },
  async getDocument(document_id) {
    const db = load();
    return clone(need(documents(db), "document_id", document_id));
  },
  async uploadDocument(project_id, file, fail = false) {
    const type = file.name.split(".").pop().toLowerCase();
    if (!FILE_TYPES.includes(type))
      throw new Error("仅支持 PDF、Markdown、TXT、CSV、JSON 文件。");
    if (file.size > 20 * 1024 * 1024)
      throw new Error("原型单文件大小上限为 20 MB。");
    const db = load();
    need(db.projects, "project_id", project_id);
    const doc = {
      document_id: id("doc"),
      project_id,
      name: file.name,
      type,
      status: "uploading",
      demo: true,
      seeded: false,
      uploaded_at: Date.now(),
      should_fail: fail || file.size === 0,
    };
    db.documents.push(doc);
    save(db);
    return clone(doc);
  },
  async deleteDocument(document_id) {
    const db = load();
    need(db.documents, "document_id", document_id);
    db.documents = db.documents.filter((d) => d.document_id !== document_id);
    save(db);
  },
  async createRun({
    project_id,
    thread_id,
    question,
    scenario = "paper",
    user_id,
  }) {
    const db = load();
    const thread = need(db.threads, "thread_id", thread_id);
    if (thread.project_id !== project_id)
      throw new Error("会话不属于当前项目。");
    if (
      Object.values(db.runs).some((r) => {
        advance(db, r);
        return r.thread_id === thread_id && !TERMINAL.includes(r.status);
      })
    )
      throw new Error("当前会话已有任务正在运行。");
    const run = {
      run_id: id("run"),
      project_id,
      thread_id,
      user_id,
      question,
      scenario,
      started_at: Date.now(),
      status: "queued",
      events: [],
      evidence: [],
      answer: null,
      draft: "",
      sequence: 0,
    };
    run.schedule = buildSchedule(run, resultFor(run, documents(db)));
    db.runs[run.run_id] = run;
    db.messages.push(
      {
        message_id: id("message"),
        role: "user",
        thread_id,
        project_id,
        content: question,
        run_id: run.run_id,
      },
      {
        message_id: id("message"),
        role: "assistant",
        thread_id,
        project_id,
        run_id: run.run_id,
        content: "",
      },
    );
    if (thread.title === "新的科研对话" || thread.title === "开始一次科研探索")
      thread.title = question.slice(0, 24);
    save(db);
    return clone(run);
  },
  async getRun(run_id) {
    const db = load();
    const r = db.runs[run_id];
    if (!r) throw new Error("任务不存在，无法恢复。");
    advance(db, r);
    save(db);
    return clone(r);
  },
  async cancelRun(run_id) {
    const db = load();
    const run = db.runs[run_id];
    if (!run) throw new Error("任务不存在。");
    advance(db, run);
    if (!TERMINAL.includes(run.status)) {
      applyEvent(run, {
        event_id: `${run_id}:cancel`,
        run_id,
        sequence: run.sequence + 1,
        timestamp: new Date().toISOString(),
        type: "cancelled",
        payload: { message: "已停止生成，保留未完成内容。" },
      });
      run.schedule = [];
    }
    save(db);
    return clone(run);
  },
  subscribe(run_id, { onEvent, onConnection, onError }, lastEventId = "") {
    let closed = false;
    let timer;
    let cursor = lastEventId;
    const close = () => {
      closed = true;
      clearTimeout(timer);
    };
    const poll = async () => {
      if (closed) return;
      try {
        const run = await this.getRun(run_id);
        if (closed) return;
        onConnection("connected");
        const index = run.events.findIndex((e) => e.event_id === cursor);
        for (const event of run.events.slice(index + 1)) {
          if (closed) return;
          onEvent(event);
          cursor = event.event_id;
        }
        if (TERMINAL.includes(run.status)) {
          close();
          onConnection("closed");
          return;
        }
        timer = setTimeout(poll, 100);
      } catch (error) {
        close();
        onError(error);
        onConnection("disconnected");
      }
    };
    timer = setTimeout(poll, 0);
    return close;
  },
};
