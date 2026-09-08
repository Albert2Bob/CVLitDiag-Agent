export const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"
).replace(/\/$/, "");
/** JSON transport, bounded timeout; mutations are never retried automatically. */
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
    if (!response.ok)
      throw new Error(`请求失败（${response.status}），请稍后重试。`);
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
