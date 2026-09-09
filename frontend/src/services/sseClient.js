import { API_BASE } from "./apiClient";
import { EVENTS, TERMINAL } from "../constants/contracts";
import { checkEvent } from "./validation";
/** EventSource 负责同一实例的 Last-Event-ID 重试。新实例使用建议的游标查询参数。 */
export function subscribeSSE(
  run_id,
  { onEvent, onConnection, onError },
  lastEventId = "",
) {
  const url = new URL(
    `${API_BASE}/api/runs/${encodeURIComponent(run_id)}/events`,
    window.location.origin,
  );
  if (lastEventId) url.searchParams.set("last_event_id", lastEventId);
  const source = new EventSource(url, { withCredentials: true });
  let timer;
  let closed = false;
  const close = () => {
    closed = true;
    source.close();
    clearTimeout(timer);
  };
  const arm = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      close();
      onConnection("disconnected");
      onError(new Error("连接长时间无响应，请恢复连接以查询任务状态。"));
    }, 45000);
  };
  const receive = (message) => {
    if (closed) return;
    arm();
    try {
      const event = JSON.parse(message.data);
      if (!checkEvent(event) || event.run_id !== run_id) {
        onError(
          new Error("收到未知或不完整的事件，已忽略；可恢复连接查询最终状态。"),
        );
        return;
      }
      onEvent(event);
      if (TERMINAL.includes(event.type)) {
        close();
        onConnection("closed");
      }
    } catch {
      onError(new Error("事件内容无法解析，已忽略；可恢复连接重新查询。"));
    }
  };
  source.onmessage = receive;
  for (const type of EVENTS) source.addEventListener(type, receive);
  source.onopen = () => {
    if (closed) return;
    onConnection("connected");
    arm();
  };
  source.onerror = () => {
    if (!closed) onConnection("reconnecting");
  };
  arm();
  return close;
}
