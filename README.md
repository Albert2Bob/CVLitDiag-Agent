# 视研 · 阶段 3

本仓库已完成 Function Calling 与结构化输出阶段：FastAPI 后端保留阶段 2 的 LangChain Agent、DeepSeek、SQLite、SSE 回放与取消能力，并增加 Pydantic 工具契约、确定性权限检查、统一工具结果、运行级只读缓存、最终回答校验和一次定向修复。Vue 3 前端可直接渲染结构化回答，并继续兼容阶段 2 的文本历史消息。

详细设计、接口变化和新增工具说明见 [阶段 3：Function Calling 与结构化输出](docs/阶段3-Function-Calling与结构化输出.md)。阶段 2 的协议仍保存在 [阶段 2：API 与 SSE](docs/阶段2-API与SSE.md)。

## 环境与安装

当前工作区使用 Python 3.14.6、Node 24.19.0。运行时依赖仍由阶段 2 锁文件固定；开发检查额外安装 Ruff：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
cd frontend
npm ci
```

将根目录 `.env.example` 复制为 `.env`，只在服务端填写 `DEEPSEEK_API_KEY`。`DEVELOPMENT_USER_ID` 是当前无正式认证系统时的可信服务端开发身份；客户端传入的 `user_id` 不参与授权。不要将任何密钥写入 `VITE_*` 变量。

## 启动

从仓库根目录以单进程启动后端：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

在另一个终端启动前端：

```powershell
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

浏览器打开 `http://127.0.0.1:5173`。前端默认连接 `http://localhost:8000`；如需覆盖，在 `frontend/.env.local` 配置 `VITE_API_BASE_URL`。设置 `VITE_MOCK=true` 可使用同步了阶段 3 数据结构的纯前端演示。

## 验证

```powershell
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm run lint
npm test
npm run build
```

当前阶段的文档资料是明确标记为 `development_fixture` 的模拟元数据，只用于验证工具参数与项目权限；没有解析正文、向量索引或 RAG 证据。正式认证、真实文档入库与引用生成属于后续阶段。
