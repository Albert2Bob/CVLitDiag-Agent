import { TERMINAL } from "../constants/contracts";
export function eventStatus(event, index, timeline, runStatus) {
  if (
    [
      "failed",
      "validation_failed",
      "tool_failed",
      "tool_validation_failed",
      "output_validation_failed",
    ].includes(event.type) ||
    event.payload.status === "failed"
  )
    return "failed";
  if (event.type === "cancelled") return "cancelled";
  const endings = {
    model_started: ["model_finished"],
    tool_started: ["tool_finished", "tool_failed"],
    tool_validation_started: [
      "tool_started",
      "tool_validation_failed",
      "tool_failed",
    ],
    output_validation_started: [
      "output_validation_failed",
      "answer_delta",
      "completed",
      "output_repair_finished",
    ],
    output_repair_started: ["output_repair_finished"],
    retrieval_started: ["retrieval_finished"],
    skill_selected: ["skill_loaded"],
  }[event.type];
  if (endings) {
    const finish = timeline
      .slice(index + 1)
      .find(
        (item) =>
          endings.includes(item.type) &&
          (!event.type.startsWith("tool_") ||
            (event.payload.tool_call_id
              ? item.payload.tool_call_id === event.payload.tool_call_id
              : true)) &&
          (event.type !== "model_started" ||
            item.payload.iteration === event.payload.iteration),
      );
    if (finish)
      return finish.type === "tool_failed" || finish.payload.status === "failed"
        ? "failed"
        : "completed";
    return TERMINAL.includes(runStatus) ? runStatus : "running";
  }
  return event.type === "run_started" && !TERMINAL.includes(runStatus)
    ? "running"
    : "completed";
}
