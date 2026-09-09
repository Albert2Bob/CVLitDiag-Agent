import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { service, isMock } from "../services";
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
  const runVersions = new Map();
  const selectionKey = `vision-research.selection.${isMock ? "mock" : "http"}`;
  const savedThreads = readLocal(selectionKey, {});
  const displayMessages = computed(() =>
    messages.value.flatMap((m) =>
      m.role === "user" &&
      runs.value[m.run_id] &&
      !messages.value.some(
        (a) => a.role === "assistant" && a.run_id === m.run_id,
      )
        ? [
            m,
            {
              ...m,
              message_id: `answer:${m.run_id}`,
              role: "assistant",
              content: "",
            },
          ]
        : [m],
    ),
  );
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
    ++revision;
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
      const version = (runVersions.get(run_id) || 0) + 1;
      runVersions.set(run_id, version);
      const navigation = revision;
      const previous = runs.value[run_id];
      const previousSequence = previous?.sequence;
      const snapshot = await service.getRun(run_id);
      if (
        previous &&
        (runs.value[run_id] !== previous ||
          previous.sequence !== previousSequence)
      )
        return runs.value[run_id];
      if (navigation !== revision || runVersions.get(run_id) !== version)
        return null;
      const run = restoreRun(snapshot);
      runs.value[run_id] = run;
      warnings.value[run_id] = "";
      connect(run);
      return run;
    });
  }
  async function selectThread(id) {
    const version = ++revision;
    const pid = projectId.value;
    threadId.value = id;
    savedThreads[pid] = id;
    try {
      writeLocal(selectionKey, savedThreads);
    } catch {
      /* 即使存储不可用，导航仍可正常工作。 */
    }
    error.value = "";
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
      const ids = [
        ...new Set(messages.value.map((m) => m.run_id).filter(Boolean)),
      ];
      const snapshots = await Promise.all(
        ids.map(async (run_id) => {
          try {
            const runVersion = runVersions.get(run_id);
            const existing = runs.value[run_id];
            const sequence = existing?.sequence;
            const snapshot = await service.getRun(run_id);
            if (
              runVersions.get(run_id) !== runVersion ||
              runs.value[run_id] !== existing ||
              existing?.sequence !== sequence
            )
              return null;
            return snapshot;
          } catch (e) {
            warnings.value[run_id] = e.message;
            return null;
          }
        }),
      );
      if (version !== revision) return;
      for (const snapshot of snapshots.filter(Boolean)) {
        if (snapshot.thread_id !== id || snapshot.project_id !== pid) continue;
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
  async function selectProject(id, preferredThread = "") {
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
      if (threads.value.length) {
        const preferred = preferredThread || savedThreads[id];
        await selectThread(
          threads.value.find((t) => t.thread_id === preferred)?.thread_id ||
            threads.value[0].thread_id,
        );
      }
    } catch (e) {
      if (version === revision) error.value = e.message;
    } finally {
      if (version === revision) loading.value = false;
    }
  }
  async function newThread() {
    const pid = projectId.value;
    const version = revision;
    return attempt(async () => {
      const t = await service.createThread({
        project_id: pid,
        user_id: user.value.user_id,
      });
      if (pid === projectId.value && version === revision) {
        threads.value.push(t);
        await selectThread(t.thread_id);
      }
      return t;
    });
  }
  async function send(question, scenario) {
    if (!question.trim() || loading.value || sending.value || activeRun.value)
      return null;
    sending.value = true;
    const pid = projectId.value;
    const startingRevision = revision;
    let tid = threadId.value;
    try {
      if (!tid) {
        const t = await newThread();
        if (
          !t ||
          pid !== projectId.value ||
          threadId.value !== t.thread_id ||
          revision !== startingRevision + 1
        )
          return null;
        tid = t.thread_id;
      }
      const version = revision;
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
        if (
          version === revision &&
          pid === projectId.value &&
          tid === threadId.value
        ) {
          selectedRunId.value = snapshot.run_id;
          evidenceId.value = "";
          const [ms, ts] = await Promise.all([
            service.getMessages(tid),
            service.listThreads(pid),
          ]);
          if (
            version === revision &&
            pid === projectId.value &&
            tid === threadId.value
          )
            messages.value = ms.filter(
              (m) => m.project_id === pid && m.thread_id === tid,
            );
          if (version === revision && pid === projectId.value)
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
      runVersions.set(run_id, (runVersions.get(run_id) || 0) + 1);
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
    displayMessages,
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
