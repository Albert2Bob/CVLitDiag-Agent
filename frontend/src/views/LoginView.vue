<script setup>
import { isMock } from "../services";
import { useRouter } from "vue-router";
import { useWorkspace } from "../stores/workspace";
const store = useWorkspace(),
  router = useRouter();
async function enter() {
  const ok = await store.attempt(async () => {
    store.login();
    return true;
  });
  if (ok) router.push("/projects");
}
</script>
<template>
  <main class="entry-page">
    <div class="entry-content">
      <div class="brand">
        <span>视研</span>
        Research
      </div>
      <h1>
        让每一个科研问题，
        <br />
        都有据可循。
      </h1>
      <p>
        面向计算机视觉与深度学习的科研问答工作台。
        <br />
        连接文献阅读、训练诊断与下一步实验。
      </p>
      <div class="login-box">
        <h2>{{ isMock ? "进入原型工作台" : "进入开发工作台" }}</h2>
        <p>
          {{
            isMock
              ? "这是模拟登录，不提供真实身份认证。"
              : "登录仅为开发占位，不提供真实身份认证。"
          }}
          <br />
          {{
            isMock
              ? "所有回答、资料解析与引用均为演示。"
              : "真实模型问答；资料解析与引用为演示。"
          }}
        </p>
        <button class="primary" @click="enter">
          {{ isMock ? "以演示研究员身份进入" : "以开发占位身份进入" }}
          <span>→</span>
        </button>
        <p v-if="store.error" role="alert" class="error">{{ store.error }}</p>
      </div>
      <small>
        {{ isMock ? "阶段 1 · 前端交互原型" : "阶段 2 · 开发模式" }}
      </small>
    </div>
    <div class="entry-art" aria-hidden="true">
      <div class="research-symbol">F(x) + x</div>
      <p>阅读 · 求证 · 探索</p>
      <div class="art-line"></div>
      <p>从一个问题，到一个可验证的实验。</p>
    </div>
  </main>
</template>
