# 视研 · 阶段 2

阶段 2 实现本地文本问答、只读时间工具、SQLite 会话与任务持久化，以及可恢复的 SSE 事件。前端使用 Vue 3 / Pinia / Vite，后端使用 FastAPI 与 LangChain。详细协议、实现边界和演示步骤见 [阶段 2 API 与 SSE](docs/阶段2-API与SSE.md)。

## 本地启动

2026-09-08 当前工作区实际解释器为 **Python 3.14.6**，Node 为 **24.19.0**。以下 PowerShell 命令从仓库根目录执行；已有虚拟环境可直接使用。解释器版本核对不代表依赖或功能测试通过。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-stage2.lock.txt
```

推荐使用已通过 `pip freeze` 生成的 `requirements-stage2.lock.txt` 固定版本复现；其中包含 LangChain 1.4.0、langchain-core 1.6.2、langchain-deepseek 1.1.0、LangGraph 1.2.11、FastAPI 0.141.1。`requirements-stage2.txt` 是阶段 2 最小依赖范围入口，重新解析依赖时可使用它。原有 `requirements.txt` 保留未来阶段的 MCP、RAG、MySQL、Chroma 等依赖规划，其中旧 Python 范围注释不代表阶段 2 当前环境；不要据此一次安装全部未来依赖。

首次配置时将根目录 `.env.example` 复制为 `.env`，在服务端填写 `DEEPSEEK_API_KEY`，已有 `.env` 则直接编辑，避免覆盖。默认模型是 `deepseek-v4-flash`，运行时显式关闭 thinking。不要把密钥放入 `VITE_*` 变量。

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

必须从根目录以**单 worker、单服务进程**启动；不要添加多 worker，也不要让多个实例共享该数据库。默认数据库路径是 `data/agent.sqlite3`。阶段 2 不恢复正在执行的 Agent：停止或重启服务会将未完成任务持久化为失败，用户可重新生成。

在另一个终端启动前端：

```powershell
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

浏览器打开 `http://127.0.0.1:5173`。前端默认使用真实 API；可在 `frontend/.env.local` 设置 `VITE_API_BASE_URL=http://127.0.0.1:8000` 和 `VITE_MOCK=false`，修改后重启 Vite。显式设置 `VITE_MOCK=true` 才使用纯前端模拟问答。

## 当前边界与验证状态

- 项目、会话、消息、任务和事件走真实后端。开发登录为固定演示身份，尚无真实认证或用户权限隔离。
- 资料上传、解析、删除、引用及结构化科研回答仍属于前端演示；资料不会进入真实模型上下文，真实回答是文本，`evidence` 为 `[]`。
- SSE 支持持久事件回放、游标续传、取消和终态恢复；连接恢复不会创建新任务，终态不会重新打开。
- 为排除所有中间文字，每轮仅执行一次框架模型请求并缓冲该轮文本，确认没有工具调用后立即发布最终文本块；首个答案增量必须等待该轮模型结束。模型与工具生命周期事件仍实时发送；这不是提供商 token 到达即推送，没有额外最终模型请求或 sleep 动画。
- 自动测试共通过后端 24 项、前端 38 项，前端 lint 与生产构建通过。另以本地 OpenAI 兼容流式服务完成浏览器联调，覆盖直接回答、工具循环、事件关联、断线恢复、刷新、取消与隐藏推理过滤。未提供 API Key，因此没有执行真实 DeepSeek 提供商调用；本地可控传输验证不等同于真实提供商验证。

模型名依据 2026-09-08 查阅的 [DeepSeek 官方首页](https://api-docs.deepseek.com/)；LangChain 集成页的 `deepseek-chat` 示例不作为当前别名可用性的验证依据。
