import { TERMINAL } from "../constants/contracts";
import { checkAnswer, checkEvent, validEvidence } from "../services/validation";
/** 幂等事件归并器。延迟事件无法重新打开终止状态。 */
export function applyEvent(run, event) {
  if (!checkEvent(event) || event.run_id !== run.run_id) return false;
  run.events ||= [];
  if (
    run.events.some((e) => e.event_id === event.event_id) ||
    TERMINAL.includes(run.status)
  )
    return false;
  if (event.sequence <= (run.sequence || 0)) return false;
  run.sequence = event.sequence;
  run.last_event_id = event.event_id;
  run.events.push(event);
  if (event.type === "output_repair_started") {
    run.outputPhase = "repairing";
    run.draft = "";
  }
  if (event.type === "output_repair_finished") run.outputPhase = "validated";
  if (event.type === "run_started") run.status = "running";
  if (event.type === "answer_delta")
    run.draft = (run.draft || "") + event.payload.delta;
  if (TERMINAL.includes(event.type)) {
    run.outputPhase = "";
    run.draft = "";
    run.status = event.type;
    if (event.type === "completed") {
      const evidence = validEvidence(event.payload.evidence, run);
      const ids = new Set(evidence.map((e) => e.evidence_id));
      if (
        typeof event.payload.answer !== "string" &&
        event.payload.answer.claims.some((c) =>
          c.evidence_ids.some((id) => !ids.has(id)),
        )
      ) {
        run.status = "failed";
        run.error = "回答引用校验失败，请重新生成。";
      } else {
        run.answer = event.payload.answer;
        run.evidence = evidence;
        run.draft = "";
      }
    } else
      run.error =
        event.payload.message ||
        (event.type === "cancelled"
          ? "生成已停止，以上为未完成内容。"
          : "任务失败，请重新生成。");
  }
  return true;
}
/** 恢复权威快照；重放绝不会创建另一个任务。 */
export function restoreRun(snapshot) {
  const run = {
    ...snapshot,
    events: [],
    evidence: [],
    answer: null,
    status: "queued",
    draft: "",
    sequence: 0,
    last_event_id: "",
  };
  for (const e of snapshot.events
    .filter(checkEvent)
    .sort((a, b) => a.sequence - b.sequence))
    applyEvent(run, e);
  if (!TERMINAL.includes(run.status)) run.status = snapshot.status;
  if (TERMINAL.includes(snapshot.status)) {
    run.outputPhase = "";
    run.draft = "";
    run.status = snapshot.status;
    run.answer = snapshot.answer;
    run.evidence = validEvidence(snapshot.evidence, snapshot);
    run.error = snapshot.error;
    if (snapshot.status === "completed") {
      const ids = new Set(run.evidence.map((e) => e.evidence_id));
      if (
        !checkAnswer(run.answer) ||
        (typeof run.answer !== "string" &&
          run.answer.claims.some((c) =>
            c.evidence_ids.some((id) => !ids.has(id)),
          ))
      ) {
        run.status = "failed";
        run.answer = null;
        run.error = "恢复结果的引用校验失败，请重新生成。";
      } else run.draft = "";
    }
  }
  return run;
}
