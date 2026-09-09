# 视研前端 · 阶段 3

Vue 3、Pinia 与 Vite 前端。默认适配器连接 `http://localhost:8000`，也可在 `.env.local` 设置 `VITE_API_BASE_URL`。只有显式配置 `VITE_MOCK=true` 才使用本地模拟服务。

```powershell
npm ci
npm run dev
npm run lint
npm test
npm run build
```

前端支持 `FinalAnswer` 的 `status`、`summary`、`claims`、`hypotheses`、`experiments` 和 `missing_information` 字段，并保留字符串历史回答的兼容渲染。运行时会检查核心字段和引用归属，忽略未知扩展字段。收到 `completed` 后才把结构化对象作为正式回答；格式修复期间显示修复状态，最终失败时不会保留未验证 JSON。

执行时间线支持参数与权限校验、工具成功或失败、缓存命中、最终输出校验和一次修复事件。SSE 事件按 `event_id` 和 `sequence` 去重，刷新与重连只回放既有运行，不会重新创建任务或执行工具。

真实后端模式中的资料管理界面仍是本地元数据演示，不上传后端，也不参与模型回答。API Key 只能保存在后端环境变量中。
