# 视研 · Phase 2 frontend

Vue 3 / Pinia / Vite. The default adapter uses the backend at `http://localhost:8000`.
Copy `.env.example` to `.env.local` to configure `VITE_API_BASE_URL`. Set
`VITE_MOCK=true` explicitly for the standalone structured-answer demo.

```sh
npm install
npm run dev
npm test
npm run build
npm run lint
```

Node.js >=20.19 <25. Production hosting must fall back to index.html for client routes.

## Integration

- GET/POST `/api/projects`; GET `/api/projects/{id}/threads`; POST `/api/threads`.
- GET `/api/threads/{id}/messages`: user/assistant messages with string content and run_id.
- POST `/api/runs`, GET `/api/runs/{id}`, POST `/api/runs/{id}/cancel` return full snapshots:
  `{run_id,thread_id,project_id,status,question,answer,evidence,events,error}`.
- Real answers are strings (null before completion); structured mock answers remain supported.
- GET `/api/runs/{id}/events` uses EventSource. Saved events replay on refresh; IDs and
  sequences deduplicate resumed events. A new connection supplies `last_event_id` as a query cursor.
- Model events show iteration/status/duration. Tool events show call ID, safe arguments,
  summary/status/duration/message. Tool failures need not terminate the run.
- Active threads persist per project and adapter. URL `thread_id` and `run_id` support restoration,
  including empty threads. Request revision guards prevent stale navigation results.
- Markdown disables raw HTML and unsafe links. Structured citations remain validated.

Project creation and chat use the real backend in default mode. Login remains a demo identity,
not authentication. Document controls are explicitly local demos: metadata only, no backend
upload, parsing, or effect on real answers. API keys must never be placed in VITE variables.

Tests cover text completion/replay, mock compatibility, event ordering, overlapping tool/model
calls, thread persistence, delayed navigation and creation, cancellation/recovery races,
HTTP routes, local documents, SSE handling, and Markdown safety.
