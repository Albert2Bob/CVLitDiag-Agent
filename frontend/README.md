# 视研 · Vue 前端原型

对应 `docs/开发计划.md` 阶段 1。仅实现前端，默认完全独立的 Mock 模式。没有后端、模型调用、真实认证或文件分析。所有演示论文片段均为人工编写，不是论文原文。

## 启动与检查

Node.js `>=20.19 <25`，npm。

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1
npm run lint
npm test
npm run build
npm run preview -- --host 127.0.0.1
```

打开终端显示的地址（通常为 http://127.0.0.1:5173）。生产部署需将未知页面路径回退到 `index.html`，以支持 Vue Router history 路由。

纯 JavaScript、Vue 3 Composition API / script setup、Vite、Vue Router、Pinia、markdown-it。使用原生表单控件与共享 CSS，未引入大型组件库。没有 TypeScript 源码或配置。

## 环境变量

复制 `.env.example` 为 `.env.local`，修改后重启开发服务器。

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| VITE_MOCK | true | 仅设为 `false` 时使用真实 HTTP/SSE 适配器 |
| VITE_API_BASE_URL | http://localhost:8000 | API 服务地址，不带末尾 `/api` |

`VITE_` 变量公开进入浏览器构建产物，不得放置 DeepSeek 或其他模型 API Key。真实模式只请求 FastAPI 入口，认证拟采用后端安全会话 Cookie；模拟登录不是安全边界，后端必须独立验证用户及项目权限。

## 已实现的交互

- 原型登录、项目列表与新建、项目切换、会话新建与历史。
- 七个显式演示场景：单篇论文、多论文比较、训练诊断、实验规划、证据不足、任务失败、部分回答。选择场景决定演示内容，不执行问题语义推理。
- 逐步回答、停止生成、重新生成、运行时间线、模拟断线与恢复。取消可在任意运行场景演示。
- Markdown、代码块、表格；关闭原始 HTML，拒绝危险链接协议，禁用外部图片。引用由结构化 `claims.evidence_ids` 渲染为按钮，不从未经校验的 Markdown 中提取 HTML 控件。
- 文件名、类型、上传与解析状态、详情及删除。支持 PDF / MD / TXT / CSV / JSON，单文件 20 MB；空文件自动模拟失败，也可勾选失败场景。解析失败后删除并重新上传即可重试。
- 用户上传仅保存元数据，不保存或解析内容，不能生成伪造的文件证据。预置 PDF / CSV 才有演示证据。删除资料影响后续任务，历史任务保留不可变的证据快照。
- 引用定位到当前任务内的详情，展示文档名称、PDF 页码（非 PDF 为 null）与片段；没有无效 PDF 跳转按钮。
- 桌面三栏布局、可折叠详情栏、窄屏浮层。长表格和代码块独立横向滚动。

## 目录与边界

```text
src/
  views/       登录、项目、科研对话
  components/  结构化回答、引用/时间线、资料管理
  stores/      Pinia 工作区与按 run_id 归属的任务状态
  services/    统一入口、运行时校验、HTTP、EventSource
  mocks/       示例资料、场景、持久化服务与事件调度
  constants/   任务/回答状态、事件、JSDoc 数据结构
  utils/       事件归约与恢复、安全 Markdown、本地存储
  assets/      共享样式
```

组件只通过 `services` 或 Pinia 访问数据，不导入 Mock。服务入口验证列表关键字段、任务 ID/状态及最终回答；事件归约器检查公共字段、类型、任务归属、序号和引用归属。未知或缺失字段事件不会使页面崩溃；真实 SSE 提示异常，允许重新查询快照恢复。

## 已预留的计划内 API

下列均为前端适配入口，不代表后端已实现。当前适配器约定直接返回 JSON 对象或数组，无 `{data: ...}` 包装；若后端采用包装格式，在服务层统一调整。

| API | 请求与响应约定 |
| --- | --- |
| POST /api/projects | `{user_id,name}` → `{project_id,name,description?}` |
| POST /api/projects/{project_id}/documents | multipart `file` → Document |
| GET /api/documents/{document_id} | → Document |
| DELETE /api/documents/{document_id} | → 204 |
| POST /api/threads | `{user_id,project_id}` → `{thread_id,project_id,title}` |
| GET /api/threads/{thread_id}/messages | → Message[]，含用户与助手占位、run_id |
| POST /api/runs | `{user_id,project_id,thread_id,question}` → RunSnapshot；不把 Mock 场景发送给后端 |
| GET /api/runs/{run_id} | → RunSnapshot |
| GET /api/runs/{run_id}/events | → text/event-stream |
| POST /api/runs/{run_id}/cancel | → 最新 RunSnapshot（若完成先发生则返回 completed） |

Document: `{document_id,project_id,name,type,status}`；原型解析状态 `uploading|parsing|ready|failed`，需与后端确认。

Message: `{message_id,thread_id,project_id,run_id,role:'user'|'assistant',content}`。

RunSnapshot 至少包含 `{run_id,thread_id,project_id,status,events,evidence,answer}`；恢复、重生成还需 `question`。`events` 为按序完整已发生事件，回答未完成时 `answer:null`，证据为空数组。原型附带 `started_at` 毫秒时间、`draft`、`sequence`、`last_event_id`、`error`。后端可以改成有 checkpoint 的增量恢复方案，但需要同时约定快照水位、草稿和事件游标，不能只返回状态字符串。

## 待后端确认的建议接口

这些页面必需的列表能力尚未出现在开发计划中，集中在 `httpService.js` 预留：

- `GET /api/projects` → 当前授权用户的项目数组。
- `GET /api/projects/{project_id}/threads` → 会话数组。
- `GET /api/projects/{project_id}/documents` → 文档数组（用于资料状态轮询）。

还需确认：分页/排序、统一错误响应、消息 ID、文件状态与限制、Cookie/CORS、取消响应、证据快照保留与删除语义、事件历史保留期限及事件游标过期响应。真实认证为后续任务，不在本次实现范围内。

## SSE、去重与刷新恢复契约

公共对象：

```json
{"event_id":"run_1:8","run_id":"run_1","sequence":8,"timestamp":"2026-09-08T08:00:00.000Z","type":"answer_delta","payload":{"delta":"临时回答文本"}}
```

支持事件：`run_started`、`skill_selected`、`skill_loaded`、`retrieval_started`、`retrieval_finished`、`tool_started`、`tool_finished`、`answer_delta`、`validation_failed`、`completed`、`failed`、`cancelled`、`heartbeat`。

- `answer_delta.payload.delta`：临时显示内容。
- `completed.payload`：`{answer,evidence,name?,duration_ms?}`。经结构和引用检查后替换临时回答。
- `failed/cancelled.payload`：`{message}`；过程事件可含 `name,duration_ms`。
- 状态严格区分：任务 `queued|running|completed|failed|cancelled`；回答 `complete|partial|insufficient_evidence`。
- Answer 字段为 `status,summary,claims[{statement,evidence_ids}],hypotheses[{hypothesis,confidence,validation_method}],experiments[{objective,change,metrics,success_criteria}],missing_information`，confidence 为 0–1 数值，metrics / missing_information 为字符串数组。
- Evidence 字段为 `evidence_id,document_id,document_name,page_number,snippet,project_id,run_id`。引用必须在当前任务的 evidence 列表中；页面不会展示其他项目的证据。

后端应给每个 SSE 帧设置 `id: <event_id>`，并使用 `event: <type>` 或普通 message。`data` 为完整公共事件 JSON。同一 run 的 sequence 严格递增、事件 ID 稳定唯一，断线回放保持原值和原顺序。接收端按 ID 去重并忽略旧序号；传输必须可靠有序，后端不能跳过缺失事件。

同一个原生 EventSource 连接重试时，浏览器自动发送 `Last-Event-ID`。代码没有设置原生 EventSource 不支持的自定义请求头。刷新或手动新建 EventSource 时，无法自行设置此头，因此当前入口使用待后端确认的 `?last_event_id=...` 查询参数；后端必须实现该参数或协商等效 cursor 方案。跨域使用 `withCredentials`，需指定允许的前端 origin 与 credentials；不把令牌放入 URL。

刷新流程：URL 保存 `run_id` → GET 快照 → 验证项目/会话 → 重建已发生事件及草稿 → 非终止状态继续订阅。任何重连或刷新都不 POST 新任务；重新生成才 POST 并产生新 run_id。终止后连接与计时器关闭，延迟事件不能复活任务。连接错误由 EventSource 自动重连；45 秒无事件/心跳则关闭并提示手动恢复，可避免永久无响应。建议后端心跳周期小于 30 秒。未知命名事件可能不会被原生 EventSource 通知，心跳超时和快照恢复作为兜底。

Mock 把事件计划及开始时间存入 `localStorage`，轮询时按真实时间推进；刷新后重放确定性前缀，即使关闭页面再打开也可完成。取消原子持久化终止状态并清空后续计划。会话切换保持任务按 run_id 更新；页面卸载释放订阅。存储键为 `vision-research.mock.v1` 与 `vision-research.user`；仅用于本机单浏览器演示，不提供多标签页并发事务或真实用户隔离。可在浏览器开发者工具中删除这两个键重置演示。

## 验证

`npm test` 共 15 项测试，覆盖事件去重、乱序/异常/跨任务事件、三种终止状态、确定性回放与恢复、跨项目引用拒绝、证据不足、安全 Markdown、取消持久化、计时器释放、重生成 ID、EventSource 游标与无响应超时。

浏览器已通过登录、项目切换、新会话、流式回答、刷新恢复、取消后刷新、重新生成、模拟断线恢复、两项目同时运行、多篇引用、五种格式上传、解析失败、无效文件、文件详情与删除、任务失败提示验证。检查过 1440×900、1100×768 和 390×844 布局，无全页横向溢出。使用 Playwright + 本机 Chrome（当前会话未提供 Browser 技能），不将临时截图和浏览器脚本放入工程。真实 HTTP/SSE 后端尚不存在，适配器仅完成单元级契约验证，未声称联调通过。

真实后端联调、PDF 预览、真实文件提取/RAG、身份认证和模型能力留待后续阶段。
