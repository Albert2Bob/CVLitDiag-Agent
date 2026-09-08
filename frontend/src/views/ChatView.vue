<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useWorkspace } from "../stores/workspace";
import { isMock } from "../services";
import { LABELS, TERMINAL } from "../constants/contracts";
import AnswerContent from "../components/AnswerContent.vue";
import RunInspector from "../components/RunInspector.vue";
import DocumentManager from "../components/DocumentManager.vue";
const store = useWorkspace(),
  route = useRoute(),
  router = useRouter();
const input = ref(""),
  scenario = ref("paper"),
  panel = ref(true),
  manager = ref(false),
  messageArea = ref(null);
let initial = true;
async function init() {
  await store.loadProjects();
  await store.selectProject(route.params.project_id);
  const run_id = route.query.run_id;
  if (typeof run_id === "string") {
    const r = await store.recover(run_id);
    if (r?.project_id === store.projectId) {
      await store.selectThread(r.thread_id);
      store.selectedRunId = run_id;
    } else if (r) store.error = "该任务不属于当前项目，已阻止显示。";
  }
  initial = false;
}
onMounted(init);
onUnmounted(() => store.dispose());
watch(
  () => route.params.project_id,
  async (id) => {
    if (id) {
      input.value = "";
      manager.value = false;
      await store.selectProject(id);
    }
  },
);
watch(
  () => store.selectedRunId,
  (id) => {
    if (!initial) router.replace({ query: id ? { run_id: id } : {} });
  },
);
watch(
  () => [store.messages.length, store.currentRun?.draft],
  async () => {
    const el = messageArea.value;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 180) {
      await nextTick();
      el.scrollTop = el.scrollHeight;
    }
  },
);
function choose(s) {
  scenario.value = s.id;
  input.value = s.question;
}
function onInputKey(event) {
  if (
    event.key === "Enter" &&
    !event.shiftKey &&
    !event.isComposing &&
    event.keyCode !== 229
  ) {
    event.preventDefault();
    send();
  }
}
async function send() {
  const text = input.value;
  if (await store.send(text, scenario.value)) {
    input.value = "";
    await nextTick();
    messageArea.value?.scrollTo({
      top: messageArea.value.scrollHeight,
      behavior: "smooth",
    });
  }
}
async function regenerate(run) {
  await store.send(run.question, run.scenario);
}
function cite(run_id, evidence_id) {
  store.showEvidence(run_id, evidence_id);
  panel.value = true;
}
async function switchProject(event) {
  await router.push(`/chat/${event.target.value}`);
}
</script>
<template>
  <main class="workspace" :class="{ 'panel-hidden': !panel }">
    <aside class="sidebar">
      <RouterLink class="brand" to="/projects">
        <span>视研</span>
        Research
      </RouterLink>
      <label class="nav-label" for="project-switch">当前项目</label>
      <select
        id="project-switch"
        :value="store.projectId"
        :disabled="store.sending"
        @change="switchProject"
      >
        <option
          v-for="p in store.projects"
          :key="p.project_id"
          :value="p.project_id"
        >
          {{ p.name }}
        </option>
      </select>
      <button
        class="primary new-thread"
        :disabled="store.loading || store.sending"
        @click="store.newThread"
      >
        ＋ 新建会话
      </button>
      <div class="nav-label">会话</div>
      <nav class="thread-list">
        <button
          v-for="t in store.threads"
          :key="t.thread_id"
          :class="{ active: t.thread_id === store.threadId }"
          :disabled="store.sending"
          @click="store.selectThread(t.thread_id)"
        >
          <span class="thread-mark">▤</span>
          {{ t.title }}
        </button>
        <p v-if="!store.threads.length" class="caption">还没有会话</p>
      </nav>
      <div class="sidebar-documents">
        <div class="nav-label">
          资料库
          <span>{{ store.documents.length }}</span>
        </div>
        <button
          v-for="d in store.documents.slice(0, 3)"
          :key="d.document_id"
          class="sidebar-file"
          @click="manager = true"
        >
          <span class="file-icon small">{{ d.type.toUpperCase() }}</span>
          <span>{{ d.name }}</span>
        </button>
        <button class="manage-button" @click="manager = true">管理资料</button>
      </div>
      <RouterLink class="mode-link" to="/projects">
        {{ isMock ? "◌ 演示模式" : "◌ 接口联调模式" }}
        <small>切换科研空间 →</small>
      </RouterLink>
    </aside>
    <section class="chat-main">
      <header class="chat-header">
        <div>
          <h1>科研对话</h1>
          <p>基于文献的科研助手，助力高效阅读与思考</p>
        </div>
        <button @click="panel = !panel">
          {{ panel ? "收起详情" : "查看详情" }}
        </button>
      </header>
      <div v-if="store.error" class="global-error" role="alert">
        {{ store.error }}
        <button @click="store.selectProject(store.projectId)">重新加载</button>
        <button @click="store.error = ''">关闭提示</button>
      </div>
      <div ref="messageArea" class="messages">
        <p v-if="store.loading" class="notice" role="status">正在加载会话…</p>
        <div v-else-if="!store.messages.length" class="empty-state">
          <div class="assistant-avatar">视</div>
          <h2>今天，想探索什么？</h2>
          <p>从论文里的一个细节，走向下一步可验证的实验。</p>
          <div v-if="isMock" class="scenario-grid">
            <button
              v-for="s in store.scenarios.slice(0, 4)"
              :key="s.id"
              @click="choose(s)"
            >
              <strong>
                {{ s.name }}
                <span>↗</span>
              </strong>
              <small>{{ s.question }}</small>
            </button>
          </div>
          <p class="caption">回答与引用均为演示数据，不代表真实分析结果。</p>
        </div>
        <template v-else>
          <article
            v-for="m in store.messages"
            :key="m.message_id"
            :class="['message', m.role]"
          >
            <template v-if="m.role === 'user'">
              <div class="user-bubble">{{ m.content }}</div>
              <small>你</small>
            </template>
            <template v-else-if="store.runs[m.run_id]">
              <div class="assistant-avatar">视</div>
              <div class="assistant-body">
                <div class="message-heading">
                  <strong>视研助手</strong>
                  <span :class="['status', store.runs[m.run_id].status]">
                    {{ LABELS[store.runs[m.run_id].status] }}
                  </span>
                  <button
                    class="text-button"
                    @click="
                      store.selectedRunId = m.run_id;
                      panel = true;
                    "
                  >
                    运行详情
                  </button>
                </div>
                <AnswerContent
                  :run="store.runs[m.run_id]"
                  @citation="(id) => cite(m.run_id, id)"
                />
                <div class="message-actions">
                  <button
                    v-if="TERMINAL.includes(store.runs[m.run_id].status)"
                    :disabled="!!store.activeRun || store.sending"
                    @click="regenerate(store.runs[m.run_id])"
                  >
                    重新生成
                  </button>
                  <button v-else @click="store.cancel(m.run_id)">
                    停止生成
                  </button>
                  <button
                    v-if="
                      store.connections[m.run_id] === 'disconnected' ||
                        store.warnings[m.run_id]
                    "
                    @click="store.recover(m.run_id)"
                  >
                    恢复连接
                  </button>
                </div>
              </div>
            </template>
            <template v-else>
              <p class="error">
                任务加载失败。
                <button @click="store.recover(m.run_id)">重试恢复</button>
              </p>
            </template>
          </article>
        </template>
      </div>
      <form class="composer" @submit.prevent="send">
        <div v-if="isMock" class="scenario-picker">
          <label for="scenario">演示场景</label>
          <select id="scenario" v-model="scenario">
            <option v-for="s in store.scenarios" :key="s.id" :value="s.id">
              {{ s.name }}
            </option>
          </select>
          <span v-if="store.activeRun" class="caption">
            {{
              store.connections[store.activeRun.run_id] === "disconnected"
                ? "连接已断开，任务仍在运行"
                : "正在生成回答…"
            }}
          </span>
        </div>
        <div class="composer-input">
          <textarea
            v-model="input"
            aria-label="科研问题"
            placeholder="输入科研问题，开始探索…"
            rows="2"
            maxlength="12000"
            :disabled="store.sending || store.loading"
            @keydown="onInputKey"
          ></textarea>
          <button
            v-if="store.activeRun"
            type="button"
            @click="store.cancel(store.activeRun.run_id)"
          >
            停止生成
          </button>
          <button
            v-else
            class="primary"
            :disabled="!input.trim() || store.sending || store.loading"
          >
            {{ store.sending ? "提交中…" : "发送 →" }}
          </button>
        </div>
        <div class="composer-footer">
          <span>演示回答与引用仅用于交互验证</span>
          <span>Enter 发送 · Shift + Enter 换行</span>
        </div>
      </form>
    </section>
    <RunInspector v-if="panel" />
    <DocumentManager v-if="manager" @close="manager = false" />
  </main>
</template>
