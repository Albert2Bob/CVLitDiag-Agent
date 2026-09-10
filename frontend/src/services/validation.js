import { ANSWER_STATUSES, EVENTS, RUN_STATUSES } from "../constants/contracts";
const strings = (v) =>
  Array.isArray(v) && v.every((x) => typeof x === "string");
const text = (v) => typeof v === "string" && v.length > 0;
export function checkAnswer(a) {
  if (typeof a === "string") return true;
  return (
    !!a &&
    ANSWER_STATUSES.includes(a.status) &&
    typeof a.summary === "string" &&
    Array.isArray(a.claims) &&
    a.claims.every((c) => c && text(c.statement) && strings(c.evidence_ids)) &&
    Array.isArray(a.hypotheses) &&
    a.hypotheses.every(
      (h) =>
        h &&
        text(h.hypothesis) &&
        Number.isFinite(h.confidence) &&
        h.confidence >= 0 &&
        h.confidence <= 1 &&
        text(h.validation_method),
    ) &&
    Array.isArray(a.experiments) &&
    a.experiments.every(
      (e) =>
        e &&
        text(e.objective) &&
        text(e.change) &&
        strings(e.metrics) &&
        text(e.success_criteria),
    ) &&
    strings(a.missing_information)
  );
}
export function checkEvent(e) {
  if (
    !e ||
    !text(e.event_id) ||
    !text(e.run_id) ||
    !Number.isInteger(e.sequence) ||
    e.sequence < 1 ||
    !Number.isFinite(Date.parse(e.timestamp)) ||
    !EVENTS.includes(e.type) ||
    !e.payload ||
    typeof e.payload !== "object"
  )
    return false;
  if (e.type === "answer_delta") return typeof e.payload.delta === "string";
  if (e.type === "completed")
    return checkAnswer(e.payload.answer) && Array.isArray(e.payload.evidence);
  return true;
}
export function assertRun(r) {
  if (
    !r ||
    !text(r.run_id) ||
    !text(r.thread_id) ||
    !text(r.project_id) ||
    !RUN_STATUSES.includes(r.status) ||
    !Array.isArray(r.events) ||
    !Array.isArray(r.evidence) ||
    (r.status === "completed" && !checkAnswer(r.answer))
  )
    throw new Error("任务响应格式不完整，请重试或联系接口维护者。");
  return r;
}
export function assertList(v, keys) {
  if (!Array.isArray(v) || !v.every((x) => x && keys.every((k) => text(x[k]))))
    throw new Error("列表响应格式不完整。");
  return v;
}
export function validEvidence(items, run) {
  return Array.isArray(items)
    ? items.filter(
        (e) =>
          e &&
          text(e.evidence_id) &&
          text(e.document_id) &&
          text(e.document_name) &&
          typeof e.snippet === "string" &&
          (e.page_number === null ||
            (Number.isInteger(e.page_number) && e.page_number > 0)) &&
          e.run_id === run.run_id &&
          e.project_id === run.project_id &&
          (e.page_end == null ||
            (Number.isInteger(e.page_end) && e.page_end > 0)),
      )
    : [];
}
