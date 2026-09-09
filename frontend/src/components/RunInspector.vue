<script setup>
import { computed, ref, watch } from "vue";
import { useWorkspace } from "../stores/workspace";
import { LABELS, TERMINAL } from "../constants/contracts";
import { briefSummary, formatDuration } from "../utils/executionDisplay";
import { eventStatus } from "../utils/eventStatus";
import { isMock } from "../services";
const store = useWorkspace(),
  tab = ref(isMock ? "evidence" : "timeline");
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
        执行过程
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
      <template v-if="tab === 'timeline'">
        <h3 class="timeline-heading">执行过程</h3>
        <p class="caption">
          {{
            isMock ? "演示执行事件摘要" : "真实执行事件摘要，不是模型隐藏思维链"
          }}
        </p>
        <p v-if="!store.currentRun" class="muted">
          发送一个问题，观察研究过程。
        </p>
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
              :class="eventStatus(e, i, timeline, store.currentRun.status)"
            >
              <span class="timeline-dot"></span>
              <div>
                <strong>{{ LABELS[e.type] || e.type }}</strong>
                <small>{{ e.payload.name || "处理当前科研问题" }}</small>
                <small v-if="e.payload.summary || e.payload.message">
                  {{ briefSummary(e.payload.summary || e.payload.message) }}
                </small>
                <details v-if="e.type.startsWith('tool_')">
                  <summary>参数与结果</summary>
                  <small v-if="e.payload.tool_call_id">
                    调用 ID：{{ e.payload.tool_call_id }}
                  </small>
                  <pre v-if="e.payload.arguments != null">{{
                    JSON.stringify(e.payload.arguments, null, 2)
                  }}</pre>
                  <p v-if="e.payload.summary">{{ e.payload.summary }}</p>
                  <p v-if="e.payload.message">{{ e.payload.message }}</p>
                </details>
                <small v-if="e.payload.iteration != null">
                  轮次 {{ e.payload.iteration }}
                </small>
                <small v-if="e.payload.status">
                  {{ LABELS[e.payload.status] || e.payload.status }}
                </small>
                <small v-if="Number.isFinite(e.payload.duration_ms)">
                  {{ formatDuration(e.payload.duration_ms) }}
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
                  !TERMINAL.includes(store.currentRun.status) &&
                  ['connected', 'connecting', 'reconnecting'].includes(
                    store.connections[store.currentRun.run_id],
                  )
                "
                @click="store.disconnect(store.currentRun.run_id)"
              >
                {{ isMock ? "模拟断线" : "断开连接" }}
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
      </template>
    </div>
  </aside>
</template>
