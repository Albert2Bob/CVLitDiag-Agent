export const RUN_STATUSES = [
  "queued",
  "running",
  "completed",
  "failed",
  "cancelled",
];
export const ANSWER_STATUSES = ["complete", "partial", "insufficient_evidence"];
export const TERMINAL = ["completed", "failed", "cancelled"];
export const EVENTS = [
  "run_started",
  "skill_selected",
  "skill_loaded",
  "retrieval_started",
  "retrieval_finished",
  "tool_started",
  "tool_finished",
  "answer_delta",
  "validation_failed",
  "completed",
  "failed",
  "cancelled",
  "heartbeat",
];
export const LABELS = {
  queued: "等待中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  complete: "完整回答",
  partial: "部分回答",
  insufficient_evidence: "证据不足",
  uploading: "模拟上传中",
  parsing: "模拟解析中",
  ready: "模拟解析成功",
  run_started: "任务开始",
  skill_selected: "选择技能",
  skill_loaded: "技能加载",
  retrieval_started: "开始检索",
  retrieval_finished: "检索完成",
  tool_started: "工具调用",
  tool_finished: "工具完成",
  validation_failed: "校验未通过",
  heartbeat: "连接正常",
};
export const FILE_TYPES = ["pdf", "md", "txt", "csv", "json"];
/** @typedef {{status: 'complete'|'partial'|'insufficient_evidence', summary: string, claims: {statement:string,evidence_ids:string[]}[], hypotheses: {hypothesis:string,confidence:number,validation_method:string}[], experiments: {objective:string,change:string,metrics:string[],success_criteria:string}[], missing_information:string[]}} Answer */
/** @typedef {{evidence_id:string,document_id:string,document_name:string,page_number:number|null,snippet:string,project_id:string,run_id:string}} Evidence */
/** @typedef {{event_id:string,run_id:string,sequence:number,timestamp:string,type:string,payload:object}} RunEvent */
/** @typedef {{run_id:string,thread_id:string,project_id:string,status:string,answer:Answer|null,evidence:Evidence[],events:RunEvent[]}} Run */
