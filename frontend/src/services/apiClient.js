export const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"
).replace(/\/$/, "");
/** JSON 传输采用有限超时；变更请求绝不会自动重试。 */
export async function request(path, { method = "GET", body } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method,
      credentials: "include",
      signal: controller.signal,
      headers:
        body && !(body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {},
      body:
        body instanceof FormData
          ? body
          : body
            ? JSON.stringify(body)
            : undefined,
    });
    if (!response.ok) {
      let payload;
      try {
        payload = await response.json();
      } catch {
        /* 非 JSON 的代理错误使用状态回退信息。 */
      }
      throw new Error(
        typeof (payload?.message || payload?.detail) === "string" &&
          (payload.message || payload.detail).trim()
          ? payload.message || payload.detail
          : `请求失败（${response.status}），请稍后重试。`,
      );
    }
    if (response.status === 204) return null;
    return await response.json();
  } catch (e) {
    throw new Error(
      e.name === "AbortError"
        ? "请求超时，请检查连接。"
        : e.message || "无法连接服务。",
    );
  } finally {
    clearTimeout(timer);
  }
}
