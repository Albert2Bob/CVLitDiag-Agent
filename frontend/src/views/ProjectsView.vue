<script setup>
import { onMounted, ref } from "vue";
import { useWorkspace } from "../stores/workspace";
import { service, isMock } from "../services";
const store = useWorkspace(),
  name = ref(""),
  busy = ref(false);
onMounted(() => store.loadProjects());
async function create() {
  if (!name.value.trim() || busy.value) return;
  busy.value = true;
  await store.attempt(async () => {
    await service.createProject({
      name: name.value.trim(),
      user_id: store.user.user_id,
    });
    name.value = "";
    await store.loadProjects();
  });
  busy.value = false;
}
</script>
<template>
  <main class="projects-page">
    <header>
      <div class="brand">
        <span>视研</span>
        Research
      </div>
      <RouterLink to="/login" @click="store.logout">退出原型登录</RouterLink>
    </header>
    <section>
      <p class="muted">你的科研空间</p>
      <h1>从一个项目开始</h1>
      <p class="muted">
        每个项目独立保存资料、会话与任务，让研究上下文保持清晰。
      </p>
      <p class="notice">
        {{
          isMock
            ? "演示模式 · 资料、回答和解析过程均为模拟数据。"
            : "阶段 4 · 开发模式 · 登录仅为开发占位；支持真实文档入库、检索与引用。"
        }}
      </p>
      <p v-if="store.error" class="error" role="alert">
        {{ store.error }}
        <button @click="store.loadProjects">重试加载</button>
      </p>
      <div class="project-list">
        <RouterLink
          v-for="p in store.projects"
          :key="p.project_id"
          :to="`/chat/${p.project_id}`"
          class="project-row"
        >
          <span class="project-initial">{{ p.name.slice(0, 1) }}</span>
          <div>
            <h2>{{ p.name }}{{ isMock ? " · 演示项目" : "" }}</h2>
            <p>{{ p.description || "独立科研项目" }}</p>
          </div>
          <span class="go">进入项目 →</span>
        </RouterLink>
        <p v-if="!store.projects.length && !store.error">
          正在加载项目，或创建你的第一个项目。
        </p>
      </div>
      <form class="project-form" @submit.prevent="create">
        <label for="project-name">新建项目</label>
        <input
          id="project-name"
          v-model="name"
          maxlength="60"
          placeholder="例如：小样本图像分类"
          required
        />
        <button class="primary" :disabled="busy || !name.trim()">
          {{ busy ? "创建中…" : "创建项目" }}
        </button>
      </form>
    </section>
  </main>
</template>
