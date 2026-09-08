<script setup>
import { computed, ref, watch } from "vue";
import { useWorkspace } from "../stores/workspace";
import { LABELS, TERMINAL } from "../constants/contracts";
import { isMock } from "../services";
const store = useWorkspace(),
  tab = ref("evidence");
watch(
  () => [store.evidenceId, store.selectedRunId],
  () => {
    if (store.evidenceId) tab.value = "evidence";
  },
);
const evidence = computed(() => store.currentRun?.evidence || []);
const selected = computed(
  () =>
    evidence.value.find((e) => e.evidence_id === store.evidenceId) ||
    evidence.value[0],
);
const timeline = computed(
  () =>
    store.currentRun?.events.filter(
      (e) => !["answer_delta", "heartbeat"].includes(e.type),
    ) || [],
);
function stepStatus(e, index) {
  if (["failed", "validation_failed"].includes(e.type)) return "failed";
  if (e.type === "cancelled") return "cancelled";
  const endType = {
    retrieval_started: "retrieval_finished",
    tool_started: "tool_finished",
    skill_selected: "skill_loaded",
  }[e.type];
  if (
    endType &&
    !timeline.value.slice(index + 1).some((item) => item.type === endType)
  ) {
    return ["failed", "cancelled"].includes(store.currentRun.status)
      ? store.currentRun.status
      : "running";
  }
  if (
    index === timeline.value.length - 1 &&
    !TERMINAL.includes(store.currentRun.status)
  )
    return "running";
  return "completed";
}
</script>
<template>
  <aside class="inspector">
    <div class="inspector-tabs">
      <button
        :class="{ selected: tab === 'evidence' }"
        @click="tab = 'evidence'"
      >
        引用与证据
      </button>
      <button
        :class="{ selected: tab === 'timeline' }"
        @click="
          tab = 'timeline';
          store.evidenceId = '';
        "
      >
        运行详情
      </button>
    </div>
    <div class="inspector-body">
      <template v-if="tab === 'evidence'">
        <h3>关联文档</h3>
        <p v-if="!evidence.length" class="muted">
          {{
            store.currentRun?.status === "completed"
              ? "本次回答没有可用引用。"
              : "回答完成后，在这里查看引用与证据。"
          }}
        </p>
        <button
          v-for="(e, i) in evidence"
          :key="e.evidence_id"
          class="evidence-file"
          :class="{ active: selected?.evidence_id === e.evidence_id }"
          @click="store.evidenceId = e.evidence_id"
        >
          <span class="file-icon">{{ e.page_number ? "PDF" : "TXT" }}</span>
          <span>
            {{ e.document_name }}
            <small>演示资料 · 引用 {{ i + 1 }}</small>
          </span>
        </button>
        <template v-if="selected">
          <h3>证据片段</h3>
          <div class="evidence-quote">
            <strong>
              {{
                selected.page_number
                  ? `第 ${selected.page_number} 页`
                  : "文本记录 · 无 PDF 页码"
              }}
            </strong>
            <p>{{ selected.snippet }}</p>
          </div>
          <p class="caption">
            引用已定位至本任务的证据详情。原型不提供 PDF
            预览；片段为人工编写的演示数据。
          </p>
        </template>
      </template>
      <h3 class="timeline-heading">Agent 运行时间线</h3>
      <p v-if="!store.currentRun" class="muted">发送一个问题，观察研究过程。</p>
      <template v-else>
        <div class="run-summary">
          <span :class="['status', store.currentRun.status]">
            {{ LABELS[store.currentRun.status] }}
          </span>
          <small>{{ store.currentRun.question }}</small>
        </div>
        <ol class="timeline">
          <li
            v-for="(e, i) in timeline"
            :key="e.event_id"
            :class="stepStatus(e, i)"
          >
            <span class="timeline-dot"></span>
            <div>
              <strong>{{ LABELS[e.type] || e.type }}</strong>
              <small>
                {{ e.payload.name || e.payload.message || "处理当前科研问题" }}
              </small>
              <small v-if="Number.isFinite(e.payload.duration_ms)">
                {{ (e.payload.duration_ms / 1000).toFixed(1) }} 秒
              </small>
            </div>
          </li>
        </ol>
        <template v-if="tab === 'timeline'">
          <p class="caption">
            连接：{{
              {
                connected: "已连接",
                connecting: "连接中",
                reconnecting: "连接中断，正在重连",
                disconnected: "已断开",
                closed: "已结束",
              }[store.connections[store.currentRun.run_id]] || "待连接"
            }}
          </p>
          <p v-if="store.warnings[store.currentRun.run_id]" class="error">
            {{ store.warnings[store.currentRun.run_id] }}
          </p>
          <div class="row-actions">
            <button
              v-if="
                isMock &&
                  !TERMINAL.includes(store.currentRun.status) &&
                  store.connections[store.currentRun.run_id] === 'connected'
              "
              @click="store.disconnect(store.currentRun.run_id)"
            >
              模拟断线
            </button>
            <button
              v-if="
                !TERMINAL.includes(store.currentRun.status) ||
                  store.warnings[store.currentRun.run_id]
              "
              @click="store.recover(store.currentRun.run_id)"
            >
              恢复连接
            </button>
          </div>
        </template>
      </template>
    </div>
  </aside>
</template>
