<script setup>
import { renderMarkdown } from "../utils/markdown";
import { LABELS } from "../constants/contracts";
import { computed } from "vue";
import { checkAnswer } from "../services/validation";
const props = defineProps({ run: { type: Object, required: true } });
const structured = computed(
  () => typeof props.run.answer === "object" && checkAnswer(props.run.answer),
);
defineEmits(["citation"]);
</script>
<template>
  <div class="answer-content">
    <h3>
      {{
        run.status === "completed"
          ? "最终回答"
          : ["queued", "running"].includes(run.status)
            ? "回答生成中"
            : "未完成回答"
      }}
    </h3>
    <!-- 在唯一的 Markdown 渲染器中设置 html:false 并执行安全 URL 校验。 -->
    <!-- eslint-disable vue/no-v-html -->
    <div
      class="markdown"
      v-html="
        renderMarkdown(
          typeof run.answer === 'string'
            ? run.answer
            : structured
              ? run.answer.summary
              : run.draft,
        )
      "
    ></div>
    <!-- eslint-enable vue/no-v-html -->
    <p v-if="run.outputPhase === 'repairing'" class="notice" role="status">
      正在修复回答格式（仅一次）…
    </p>
    <template v-if="structured">
      <div class="answer-status">{{ LABELS[run.answer.status] }}</div>
      <section v-if="run.answer.claims.length" class="claims">
        <h3>结论与陈述</h3>
        <p v-for="(claim, i) in run.answer.claims" :key="i">
          {{ claim.statement }}
          <button
            v-for="id in claim.evidence_ids"
            :key="id"
            class="citation"
            :aria-label="`查看引用 ${run.evidence.findIndex((e) => e.evidence_id === id) + 1}`"
            @click="$emit('citation', id)"
          >
            [{{ run.evidence.findIndex((e) => e.evidence_id === id) + 1 }}]
          </button>
        </p>
      </section>
      <section v-for="(h, i) in run.answer.hypotheses" :key="`h${i}`">
        <h3>
          待验证假设
          <small>置信度 {{ Math.round(h.confidence * 100) }}%</small>
        </h3>
        <p>{{ h.hypothesis }}</p>
        <p class="muted">验证方法：{{ h.validation_method }}</p>
      </section>
      <section v-for="(e, i) in run.answer.experiments" :key="`e${i}`">
        <h3>{{ e.objective }}</h3>
        <p>{{ e.change }}</p>
        <p>观察指标：{{ e.metrics.join("、") }}</p>
        <p class="muted">成功标准：{{ e.success_criteria }}</p>
      </section>
      <section v-if="run.answer.missing_information.length">
        <h3>还需要的信息</h3>
        <ul>
          <li v-for="item in run.answer.missing_information" :key="item">
            {{ item }}
          </li>
        </ul>
      </section>
    </template>
    <p
      v-if="
        !run.answer && !run.draft && ['queued', 'running'].includes(run.status)
      "
      class="muted pulse"
    >
      正在阅读问题、整理回答…
    </p>
    <p
      v-if="run.error"
      :class="run.status === 'failed' ? 'error' : 'notice'"
      role="status"
    >
      {{ run.error }}
    </p>
  </div>
</template>
