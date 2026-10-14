import type { ArtifactSummary, BatchPlan, CourseInput, CourseProgress, ExecutionReadModel, Finding, GateResult, LlmConfigStatus, ReviewFinding, V0Run } from "./api";

const STAGES = ["intake", "mission", "blueprint", "batch_plan", "generation", "quality", "release"];
const STAGE_STATUS_LABELS = {
  pending: "待执行", running: "执行中", succeeded: "已完成", failed: "失败",
  waiting_for_human: "等待人工", stopped: "已停止",
};

export function runPath(id: string): string {
  return `/run/${encodeURIComponent(id)}`;
}

export function courseProgressLabel(course: Pick<CourseProgress, "current_stage" | "stage_status">): string {
  return `第 ${STAGES.indexOf(course.current_stage) + 1}/7 步 · ${course.current_stage} · ${STAGE_STATUS_LABELS[course.stage_status]}`;
}

export function canStartRun(config?: Pick<LlmConfigStatus, "configured">): boolean {
  return config?.configured === true;
}

export function courseCreationAction(
  config: Pick<LlmConfigStatus, "configured"> | undefined,
  busy: boolean,
): { disabled: boolean; label: string } {
  if (!canStartRun(config)) {
    return { disabled: true, label: "配置 DeepSeek 后执行" };
  }
  if (busy) {
    return { disabled: true, label: "正在创建课程…" };
  }
  return { disabled: false, label: "创建课程并执行 Run" };
}

export function generationConstraintLabels(
  input: Pick<CourseInput, "expected_chapters" | "min_effective_chars" | "token_limit">,
): string[] {
  return [
    `期望章节：${input.expected_chapters.toLocaleString("en-US")}（允许 ±1 章偏差）`,
    `单章下限：${input.min_effective_chars.toLocaleString("en-US")} 有效字符`,
    `Token 阈值：${input.token_limit === null
      ? "不限制" : input.token_limit.toLocaleString("en-US")}`,
  ];
}

export function budgetTokenLabel(
  budget: Pick<ExecutionReadModel["budget"],
    "tokens_used" | "token_limit" | "token_usage_unknown" | "token_exhausted">,
): string {
  const used = budget.tokens_used.toLocaleString("en-US");
  const limit = budget.token_limit === null
    ? "；不限制" : `/${budget.token_limit.toLocaleString("en-US")}`;
  const unknown = budget.token_usage_unknown > 0
    ? `；${budget.token_usage_unknown} 次用量未知` : "";
  return `Token：${used}${limit}${unknown}${budget.token_exhausted ? "；已达阈值" : ""}`;
}

export function canResumeRun(
  run: Pick<V0Run, "status"> & {
    stages: Pick<V0Run["stages"][number], "failure_reason">[];
  },
  execution?: { budget: Pick<ExecutionReadModel["budget"], "token_exhausted"> } | null,
): boolean {
  const resumable = run.status === "stopped" || run.status === "waiting_for_human";
  const tokenStopped = execution?.budget.token_exhausted
    || run.stages.some((stage) => stage.failure_reason === "token_limit_reached");
  return resumable && !tokenStopped;
}

export function shouldPoll(status: V0Run["status"]): boolean {
  return status === "running" || status === "waiting_for_human" || status === "stopped";
}

export function pollInterval(run?: Pick<V0Run, "status">): number | false {
  if (!run || !shouldPoll(run.status)) return false;
  return run.status === "running" ? 1000 : 5000;
}

function progress(run: V0Run): number {
  const stageScore = run.stages.reduce((score, stage) => {
    if (stage.status === "pending") return score;
    if (stage.status === "running") return score + 1;
    return score + 2;
  }, 0);
  return stageScore + (run.status === "ready_for_release" || run.status === "stopped" ? 1 : 0);
}

export function preferNewerRun(current: V0Run | null, next: V0Run): V0Run {
  if (current && current.id === next.id && current.revision !== undefined && next.revision !== undefined) {
    return next.revision >= current.revision ? next : current;
  }
  if (!current || current.id !== next.id || progress(next) > progress(current)) return next;
  return current;
}

export function artifactHandoffLabel(artifact: ArtifactSummary): string {
  const producer = artifact.producer_role ?? "unknown";
  const sources = artifact.source_refs.length
    ? artifact.source_refs.map((source) => `${source.kind} v${source.version}`).join("、")
    : "无";
  return `${producer} · ${artifact.kind} v${artifact.version} · 来源 ${sources}`;
}

export function reviewFindingLabel(finding: ReviewFinding): string {
  return `[${finding.severity}/${finding.category}] ${finding.evidence}；建议：${finding.recommendation}`;
}

export function qualityGateLabels(quality: {
  gate_results?: GateResult[];
  evidence_findings?: Finding[];
}): string[] {
  const gates = (quality.gate_results ?? []).map((result) =>
    `${result.gate} · ${result.status} · ${result.artifact_ref.kind} v${result.artifact_ref.version} · ${result.rule_id}：${result.evidence}`,
  );
  const findings = (quality.evidence_findings ?? []).map((finding) =>
    `${finding.severity}/${finding.category} · ${finding.location.lesson_id} 第 ${finding.location.line_start} 行 · ${finding.evidence}`,
  );
  return [...gates, ...findings];
}

export function batchProgressLabel(plan: BatchPlan): string {
  const completedLessons = new Set(
    (plan.continuity_ledger ?? []).map((entry) => entry.lesson_id),
  );
  const completedBatches = (plan.lesson_ids ?? []).filter(
    (lessonIds) => lessonIds.length > 0 && lessonIds.every((id) => completedLessons.has(id)),
  ).length;
  const batchIds = plan.batch_ids?.length ? ` · ${plan.batch_ids.join("、")}` : "";
  return `${plan.batches.length} 个批次，已完成 ${completedBatches} 个${batchIds}`;
}

export function continuityLedgerLabels(plan: BatchPlan): string[] {
  return (plan.continuity_ledger ?? []).map(
    (entry) => `${entry.lesson_id}：${entry.summary}`,
  );
}

export function canDecideRelease(run: Pick<V0Run, "status" | "stages">): boolean {
  return run.status === "waiting_for_human"
    && run.stages.find((stage) => stage.name === "release")?.status === "waiting_for_human";
}

export function canReviewMission(
  run: Pick<V0Run, "status" | "stages">,
  execution: Pick<ExecutionReadModel, "checkpoint" | "commands" | "mission_review"> | null | undefined,
): boolean {
  return run.status === "waiting_for_human"
    && run.stages.find((stage) => stage.name === "mission")?.status === "waiting_for_human"
    && execution?.mission_review?.status === "pending"
    && Boolean(execution.mission_review.checkpoint_id)
    && execution.mission_review.checkpoint_id === execution.checkpoint?.id
    && !execution.commands.some((command) =>
      command.kind === "MISSION_REVIEW" && (command.status === "ACCEPTED" || command.status === "CLAIMED"));
}

export function canReviewQuality(
  run: Pick<V0Run, "status" | "stages">,
  execution: Pick<ExecutionReadModel, "checkpoint" | "commands" | "quality_review"> | null | undefined,
): boolean {
  return run.status === "waiting_for_human"
    && run.stages.find((stage) => stage.name === "quality")?.status === "waiting_for_human"
    && execution?.quality_review?.status === "pending"
    && execution.quality_review.checkpoint_id === execution.checkpoint?.id
    && !execution.commands.some((command) =>
      command.kind === "QUALITY_REVIEW"
      && (command.status === "ACCEPTED" || command.status === "CLAIMED"));
}
