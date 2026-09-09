<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { useWorkspace } from "../stores/workspace";
import { service, isMock } from "../services";
import { LABELS } from "../constants/contracts";
const store = useWorkspace(),
  fail = ref(false),
  busy = ref(false),
  detail = ref(null);
const modal = ref(null);
let previousFocus;
defineEmits(["close"]);
let timer,
  disposed = false;
async function poll() {
  try {
    await store.refreshDocuments();
  } catch (error) {
    store.error = error.message;
  }
  if (!disposed) timer = setTimeout(poll, 650);
}
onMounted(() => {
  previousFocus = document.activeElement;
  modal.value?.querySelector("button")?.focus();
  poll();
});
onUnmounted(() => {
  disposed = true;
  clearTimeout(timer);
  previousFocus?.focus();
});
function trapFocus(event) {
  if (event.key !== "Tab") return;
  const items = [
    ...modal.value.querySelectorAll("button, input, select, textarea, a[href]"),
  ].filter((el) => !el.disabled);
  const first = items[0],
    last = items.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last?.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first?.focus();
  }
}
async function upload(event) {
  const files = [...event.target.files],
    pid = store.projectId;
  busy.value = true;
  await store.attempt(async () => {
    for (const file of files)
      await service.uploadDocument(pid, file, fail.value);
    await store.refreshDocuments();
  });
  busy.value = false;
  event.target.value = "";
}
async function remove(id) {
  await store.attempt(async () => {
    await service.deleteDocument(id);
    if (detail.value?.document_id === id) detail.value = null;
    await store.refreshDocuments();
  });
}
async function view(id) {
  await store.attempt(async () => {
    detail.value = await service.getDocument(id);
  });
}
</script>
<template>
  <div
    class="modal-backdrop"
    @click.self="$emit('close')"
    @keydown.esc="$emit('close')"
  >
    <section
      ref="modal"
      class="document-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="documents-title"
      @keydown="trapFocus"
    >
      <header>
        <div>
          <h2 id="documents-title">项目资料库 · 本地演示</h2>
          <p class="muted">{{ store.project?.name }}</p>
        </div>
        <button aria-label="关闭资料库" autofocus @click="$emit('close')">
          关闭
        </button>
      </header>
      <p class="notice">
        {{
          isMock
            ? "仅模拟上传与解析，不读取或分析文件内容。上传资料不会生成真实引用。"
            : "资料功能为本地演示，仅保存元数据，不上传后端或参与真实回答。"
        }}
      </p>
      <label class="upload-zone">
        <strong>{{ busy ? "正在添加资料…" : "选择论文或实验资料" }}</strong>
        <span>PDF / Markdown / TXT / CSV / JSON · 单文件不超过 20 MB</span>
        <input
          type="file"
          multiple
          accept=".pdf,.md,.txt,.csv,.json"
          :disabled="busy"
          aria-label="选择上传文件"
          @change="upload"
        />
      </label>
      <label v-if="isMock" class="checkbox">
        <input v-model="fail" type="checkbox" />
        模拟解析失败（可删除后重新上传重试）
      </label>
      <p v-if="store.error" class="error" role="alert">{{ store.error }}</p>
      <div class="document-list">
        <p v-if="!store.documents.length" class="muted">
          暂无资料，选择文件开始模拟上传。
        </p>
        <div
          v-for="doc in store.documents"
          :key="doc.document_id"
          class="document-row"
        >
          <span class="file-icon">{{ doc.type.toUpperCase() }}</span>
          <button class="document-name" @click="view(doc.document_id)">
            {{ doc.name }}
          </button>
          <span :class="['status', doc.status]">
            {{ LABELS[doc.status] || doc.status }}
          </span>
          <button
            :aria-label="`删除 ${doc.name}`"
            @click="remove(doc.document_id)"
          >
            删除
          </button>
        </div>
      </div>
      <div v-if="detail" class="evidence-quote">
        <strong>{{ detail.name }}</strong>
        <p>
          {{ LABELS[detail.status] || detail.status }} ·
          {{ detail.type?.toUpperCase() }}
        </p>
        <p class="muted">
          {{
            detail.seeded
              ? "预置演示资料，引用片段为人工编写。"
              : "只保存文件元数据，内容未在本原型中被真实解析。"
          }}
        </p>
      </div>
      <p class="caption">此处操作仅影响本地演示资料。</p>
    </section>
  </div>
</template>
