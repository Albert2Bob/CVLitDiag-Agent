# 视研前端 · 阶段 4

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

真实后端模式使用 multipart API 上传文件，轮询恢复 parsing/indexing/ready/failed/unsupported 状态，并支持查看详情和删除。引用面板显示后端保存的文档名、章节、页码范围或结构定位符以及真实 chunk 片段；回答引用仍需通过运行 evidence 集合的前端二次校验。Mock 模式继续明确标为演示。API Key 和模型配置只能保存在后端环境变量中。
