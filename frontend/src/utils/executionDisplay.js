export function briefSummary(value, limit = 120) {
  const text = String(value).replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}
export function formatDuration(ms) {
  if (ms < 1) return "<1 ms";
  if (ms < 1000) return `${Number(ms.toFixed(1))} ms`;
  return `${Number((ms / 1000).toFixed(2))} 秒`;
}
