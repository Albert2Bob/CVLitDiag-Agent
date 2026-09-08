import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { service } from "../services";
import { TERMINAL } from "../constants/contracts";
import { applyEvent, restoreRun } from "../utils/runState";
import { readLocal, writeLocal } from "../utils/storage";
export const useWorkspace = defineStore("workspace", () => {
  const user = ref(readLocal("vision-research.user", null));
  const projects = ref([]),
    threads = ref([]),
    documents = ref([]),
    messages = ref([]),
    runs = ref({});
  const projectId = ref(""),
    threadId = ref(""),
    loading = ref(false),
    sending = ref(false),
    error = ref(""),
    scenarios = ref([]);
  const connections = ref({}),
    warnings = ref({}),
    selectedRunId = ref(""),
    evidenceId = ref("");
  const closers = new Map();
  let revision = 0;
  const project = computed(() =>
    projects.value.find((p) => p.project_id === projectId.value),
  );
  const currentRun = computed(() => {
    const r = runs.value[selectedRunId.value];
    return r?.project_id === projectId.value && r?.thread_id === threadId.value
      ? r
      : null;
  });
  const activeRun = computed(() =>
    Object.values(runs.value).find(
      (r) =>
        r.thread_id === threadId.value &&
        r.project_id === projectId.value &&
        !TERMINAL.includes(r.status),
    ),
  );
  function login() {
    user.value = { user_id: "demo_researcher", name: "演示研究员" };
    writeLocal("vision-research.user", user.value);
  }
  function dispose() {
    for (const close of closers.values()) close();
    closers.clear();
  }
  function logout() {
    dispose();
    user.value = null;
    writeLocal("vision-research.user", null);
  }
  async function attempt(fn) {
    error.value = "";
    try {
      return await fn();
    } catch (e) {
      error.value = e.message;
      return null;
    }
  }
  async function loadProjects() {
    return attempt(async () => {
      projects.value = await service.listProjects();
      scenarios.value = await service.scenarios();
    });
  }
  function connect(run) {
    closers.get(run.run_id)?.();
    closers.delete(run.run_id);
    if (TERMINAL.includes(run.status)) {
      connections.value[run.run_id] = "closed";
      return;
    }
    connections.value[run.run_id] = "connecting";
    closers.set(
      run.run_id,
      service.subscribe(
        run.run_id,
        {
          onEvent: (e) => {
            const target = runs.value[run.run_id];
            if (
              target &&
              applyEvent(target, e) &&
              TERMINAL.includes(target.status)
            ) {
              closers.get(run.run_id)?.();
              closers.delete(run.run_id);
              connections.value[run.run_id] = "closed";
            }
          },
          onConnection: (state) => {
            connections.value[run.run_id] = state;
          },
          onError: (e) => {
            warnings.value[run.run_id] = e.message;
          },
        },
        run.last_event_id,
      ),
    );
  }
  async function recover(run_id) {
    return attempt(async () => {
      const snapshot = await service.getRun(run_id);
      const run = restoreRun(snapshot);
      runs.value[run_id] = run;
      warnings.value[run_id] = "";
      connect(run);
      return run;
    });
  }
  async function selectThread(id) {
    const version = ++revision;
    threadId.value = id;
    messages.value = [];
    selectedRunId.value = "";
    evidenceId.value = "";
    loading.value = true;
    try {
      const result = await service.getMessages(id);
      if (version !== revision) return;
      messages.value = result.filter(
        (m) => m.project_id === projectId.value && m.thread_id === id,
      );
      const ids = [...new Set(messages.value.map((m) => m.run_id))];
      const snapshots = await Promise.all(
        ids.map(async (run_id) => {
          try {
            return await service.getRun(run_id);
          } catch (e) {
            warnings.value[run_id] = e.message;
            return null;
          }
        }),
      );
      for (const snapshot of snapshots.filter(Boolean)) {
        if (
          snapshot.thread_id !== id ||
          snapshot.project_id !==
            messages.value.find((m) => m.thread_id === id)?.project_id
        )
          continue;
        runs.value[snapshot.run_id] = restoreRun(snapshot);
        connect(runs.value[snapshot.run_id]);
      }
      if (version === revision) selectedRunId.value = ids.at(-1) || "";
    } catch (e) {
      if (version === revision) error.value = e.message;
    } finally {
      if (version === revision) loading.value = false;
    }
  }
  async function selectProject(id) {
    const version = ++revision;
    projectId.value = id;
    threadId.value = "";
    threads.value = [];
    messages.value = [];
    documents.value = [];
    selectedRunId.value = "";
    evidenceId.value = "";
    loading.value = true;
    error.value = "";
    try {
      const [ts, ds] = await Promise.all([
        service.listThreads(id),
        service.listDocuments(id),
      ]);
      if (version !== revision) return;
      threads.value = ts.filter((t) => t.project_id === id);
      documents.value = ds.filter((d) => d.project_id === id);
      if (threads.value.length) await selectThread(threads.value[0].thread_id);
    } catch (e) {
      if (version === revision) error.value = e.message;
    } finally {
      if (version === revision) loading.value = false;
    }
  }
  async function newThread() {
    const pid = projectId.value;
    return attempt(async () => {
      const t = await service.createThread({
        project_id: pid,
        user_id: user.value.user_id,
      });
      if (pid === projectId.value) {
        threads.value.push(t);
        await selectThread(t.thread_id);
      }
      return t;
    });
  }
  async function send(question, scenario) {
    if (!question.trim() || sending.value || activeRun.value) return null;
    sending.value = true;
    const pid = projectId.value;
    try {
      if (!threadId.value) {
        const t = await newThread();
        if (!t) return null;
      }
      const tid = threadId.value;
      return await attempt(async () => {
        const snapshot = await service.createRun({
          project_id: pid,
          thread_id: tid,
          user_id: user.value.user_id,
          question: question.trim(),
          scenario,
        });
        runs.value[snapshot.run_id] = restoreRun(snapshot);
        connect(runs.value[snapshot.run_id]);
        if (pid === projectId.value && tid === threadId.value) {
          selectedRunId.value = snapshot.run_id;
          evidenceId.value = "";
          const [ms, ts] = await Promise.all([
            service.getMessages(tid),
            service.listThreads(pid),
          ]);
          if (pid === projectId.value && tid === threadId.value)
            messages.value = ms.filter(
              (m) => m.project_id === pid && m.thread_id === tid,
            );
          if (pid === projectId.value)
            threads.value = ts.filter((t) => t.project_id === pid);
        }
        return snapshot;
      });
    } finally {
      sending.value = false;
    }
  }
  async function cancel(run_id) {
    return attempt(async () => {
      const snapshot = await service.cancelRun(run_id);
      closers.get(run_id)?.();
      closers.delete(run_id);
      runs.value[run_id] = restoreRun(snapshot);
      connections.value[run_id] = "closed";
    });
  }
  function disconnect(run_id) {
    closers.get(run_id)?.();
    closers.delete(run_id);
    connections.value[run_id] = "disconnected";
  }
  async function refreshDocuments() {
    const pid = projectId.value;
    const ds = await service.listDocuments(pid);
    if (pid === projectId.value)
      documents.value = ds.filter((d) => d.project_id === pid);
  }
  function showEvidence(run_id, evidence_id) {
    const run = runs.value[run_id];
    if (
      run?.project_id !== projectId.value ||
      run?.thread_id !== threadId.value
    )
      return;
    selectedRunId.value = run_id;
    evidenceId.value = evidence_id;
  }
  return {
    user,
    projects,
    threads,
    documents,
    messages,
    runs,
    projectId,
    threadId,
    loading,
    sending,
    error,
    scenarios,
    project,
    currentRun,
    activeRun,
    connections,
    warnings,
    selectedRunId,
    evidenceId,
    login,
    logout,
    dispose,
    attempt,
    loadProjects,
    selectProject,
    selectThread,
    newThread,
    send,
    cancel,
    recover,
    disconnect,
    refreshDocuments,
    showEvidence,
  };
});
