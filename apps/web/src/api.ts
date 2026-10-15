export type Health = {
  status: "ok";
  service: string;
};

export type LlmConfigStatus = {
  provider: "deepseek";
  model: "deepseek-flash" | "deepseek-v4-pro";
  configured: boolean;
  error: string | null;
};

export class ApiError extends Error {
  code?: string;

  constructor(message: string, code?: string) {
    super(message);
    this.code = code;
  }
}

export type Course = {
  slug: string;
  title: string;
  description: string;
  href: string;
  chapters: number;
  duration: string;
  status: string;
};

export type CourseInput = {
  topic: string;
  audience: string;
  goal: string;
  language: "zh";
  source_policy: string;
  expected_chapters: number;
  min_effective_chars: number;
  token_limit: number | null;
};

export type StageRecord = {
  name: "intake" | "mission" | "blueprint" | "batch_plan" | "generation" | "quality" | "release";
  status: "pending" | "running" | "succeeded" | "failed" | "waiting_for_human" | "stopped";
  input_summary: string;
  output_summary: string;
  failure_reason: string | null;
};

export type V0Run = {
  id: string;
  course_id: string | null;
  constraints_version: number;
  revision: number;
  artifacts: ArtifactSummary[];
  course_input: CourseInput;
  status: "running" | "failed" | "waiting_for_human" | "ready_for_release" | "stopped" | "published";
  stages: StageRecord[];
  mission: { audience: string; learning_goal: string; scope: string; stop_conditions: string[] } | null;
  blueprint: {
    lessons: {
      title: string;
      learning_goal: string;
      evidence: string;
      lesson_id: string | null;
      batch_id: string | null;
    }[];
  } | null;
  batch_plan: BatchPlan | null;
  lesson: {
    title: string;
    markdown: string;
    lesson_id: string | null;
    batch_id: string | null;
    continuity_summary: string;
    terminology: string[];
    next_promises: string[];
  } | null;
  quality: {
    status: "ready" | "manual_review";
    checks: string[];
    findings: ReviewFinding[];
    language_risk: string;
    limitations: string[];
    gate_results?: GateResult[];
    evidence_findings?: Finding[];
    repair_tasks?: RepairTask[];
    verification_results?: GateResult[];
    verification_links?: {
      finding_id: string;
      candidate_ref: ArtifactRef;
      result_start: number;
      result_count: number;
    }[];
    resolved_finding_ids?: string[];
  } | null;
  release_decision: { action: "prepare" | "stop"; reason: string } | null;
  publication: { slug: string; href: string; published_at: string } | null;
};

export type AgentRole = "mission" | "blueprint" | "writer" | "reviewer" | "repair";

export type ArtifactRef = {
  run_id: string;
  artifact_id: string;
  version: number;
  kind: "mission" | "blueprint" | "batch_plan" | "lesson" | "quality";
  content_hash: string;
};

export type ArtifactSummary = {
  artifact_id: string;
  version: number;
  kind: "mission" | "blueprint" | "batch_plan" | "lesson" | "quality";
  content_hash: string;
  producer_role: AgentRole | "system" | null;
  source_refs: ArtifactRef[];
};

export type ContinuityEntry = {
  batch_id: string;
  lesson_id: string;
  lesson_ref: ArtifactRef;
  summary: string;
  terminology: string[];
  next_promises: string[];
};

export type BatchPlan = {
  batches: number[][];
  batch_ids?: string[];
  lesson_ids?: string[][];
  continuity_ledger?: ContinuityEntry[];
};

export type ReviewFinding = {
  code: string;
  category: "structure" | "teaching" | "language" | "fact";
  severity: "blocker" | "major" | "minor";
  evidence: string;
  recommendation: string;
};

export type GateResult = {
  gate: "deterministic" | "rubric" | "humanizer";
  status: "pass" | "fail" | "error" | "not_applicable";
  rule_id: string;
  evidence: string;
  artifact_ref: ArtifactRef;
};

export type Finding = {
  finding_id: string;
  run_id: string;
  gate: GateResult["gate"];
  rule_id: string;
  artifact_ref: ArtifactRef;
  location: { lesson_id: string; line_start: number; line_end: number; excerpt_hash: string };
  category: ReviewFinding["category"];
  severity: ReviewFinding["severity"];
  evidence: string;
  expected: string;
};

export type RepairTask = {
  finding_id: string;
  source_ref: ArtifactRef;
  line_start: number;
  excerpt: string;
  excerpt_hash: string;
  rule_id: string;
  objective: string;
};

export type CourseFact = { id: string; title: string; workspace_key: string };
export type CourseProgress = CourseFact & {
  run_id: string;
  current_stage: StageRecord["name"];
  stage_status: StageRecord["status"];
};
export type RunContent = {
  run_id: string;
  title: string;
  chapters: {
    lesson_id: string | null;
    title: string;
    status: "pending" | "generated";
    markdown: string | null;
    version: number | null;
  }[];
};
export type ArtifactFact = ArtifactSummary & {
  run_id: string;
  content: Record<string, unknown>;
  workspace_relpath: string | null;
};

export type ExecutionCommand = {
  id: string;
  run_id: string;
  kind: "START" | "STOP" | "RESUME" | "REVISE" | "MISSION_REVIEW" | "QUALITY_REVIEW";
  status: "ACCEPTED" | "CLAIMED" | "APPLIED" | "FAILED" | "REJECTED";
  error: string | null;
};

export type ExecutionReadModel = {
  run_id: string;
  commands: ExecutionCommand[];
  current_node: string | null;
  node_status: string | null;
  checkpoint: { id: string; position: string; node_execution_id: string | null } | null;
  stop_requested: boolean;
  human_input_revision: number;
  waiting_reason: string | null;
  mission_review: {
    status: "pending" | "approved";
    mission_ref: ArtifactRef;
    checkpoint_id: string | null;
  } | null;
  quality_review: {
    status: "pending";
    quality_ref: ArtifactRef;
    lesson_ref: ArtifactRef;
    checkpoint_id: string;
  } | null;
  budget: {
    used: number; limit: number; warning_at: number;
    warning: boolean; requires_human: boolean; unknown: number;
    repair_used: number; repair_limit: number; repair_exhausted: boolean;
    tokens_used: number; token_limit: number | null;
    token_usage_unknown: number; token_exhausted: boolean;
  };
};

export type DeliveryEvidence = {
  trace_id: string;
  run_status: string;
  commands: { id: string; kind: string; status: string }[];
  nodes: { id: string; command_id: string | null; node: string; attempt: number; lease_epoch: number; status: string }[];
  artifacts: { id: string; version: number; kind: string; content_hash: string }[];
  provider_calls: { id: string; command_id: string | null; node_execution_id: string | null; role: string; status: string; duration_ms: number | null; input_tokens: number | null; output_tokens: number | null }[];
  findings: {
    id: string; gate: string; rule_id: string;
    artifact_id: string; artifact_version: number;
    expected_value: number | null; actual_value: number | null;
  }[];
  verifications: { id: string; gate: string; status: string; candidate_id: string; candidate_version: number; finding_id: string | null }[];
  decisions: { event_id: number; kind: string; action: string | null }[];
  constraint_events: {
    event_id: number; kind: string; status: string | null;
    artifact_id: string | null; artifact_version: number | null;
    expected_value: number | null; actual_value: number | null;
  }[];
  paths: { scenario: "normal" | "recovery" | "human"; status: "observed" | "not_observed"; evidence_ids: string[] }[];
  integrity_issues: string[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null) as {
      detail?: string | { loc?: (string | number)[]; msg?: string }[]
        | { code?: string; message?: string };
    } | null;
    const detail = body?.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => `${item.loc?.slice(1).join(".") || "输入"}：${item.msg || "无效"}`).join("；")
      : typeof detail === "string" ? detail
        : detail?.message || `请求失败：${response.status}`;
    throw new ApiError(message, !Array.isArray(detail) && typeof detail === "object"
      ? detail?.code : undefined);
  }
  return response.json() as Promise<T>;
}

function post<T>(path: string, body: unknown, idempotencyKey: string): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(body),
  });
}

export const api = {
  health: () => request<Health>("/api/health"),
  getLlmConfig: () => request<LlmConfigStatus>("/api/v0/llm-config"),
  saveLlmConfig: (model: LlmConfigStatus["model"], apiKey?: string) =>
    request<LlmConfigStatus>("/api/v0/llm-config", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, ...(apiKey ? { api_key: apiKey } : {}) }),
    }),
  clearLlmConfig: () => request<LlmConfigStatus>("/api/v0/llm-config", {
    method: "DELETE",
  }),
  courses: () => request<{ items: Course[] }>("/api/courses"),
  startRun: (input: CourseInput, key: string) => post<V0Run>("/api/v0/runs", input, key),
  run: (id: string) => request<V0Run>(`/api/v0/runs/${encodeURIComponent(id)}`),
  runContent: (id: string) => request<RunContent>(`/api/v0/runs/${encodeURIComponent(id)}/content`),
  decideRelease: (id: string, action: "prepare" | "stop", reason: string, key: string) =>
    post<V0Run>(`/api/v0/runs/${encodeURIComponent(id)}/release`, { action, reason }, key),
  publishRun: (id: string, key: string) =>
    post<V0Run>(`/api/v0/runs/${encodeURIComponent(id)}/publish`, {}, key),
  courseFacts: () => request<{ items: CourseProgress[] }>("/api/v0/courses"),
  courseFact: (id: string) => request<CourseFact>(`/api/v0/courses/${encodeURIComponent(id)}`),
  snapshot: (id: string) => request<{ run_id: string; revision: number; run: V0Run }>(`/api/v0/runs/${encodeURIComponent(id)}/snapshot`),
  artifacts: (id: string) => request<{ items: ArtifactSummary[] }>(`/api/v0/runs/${encodeURIComponent(id)}/artifacts`),
  artifact: (id: string, version: number) => request<ArtifactFact>(`/api/v0/artifacts/${encodeURIComponent(id)}/versions/${version}`),
  execution: (id: string) => request<ExecutionReadModel>(`/api/v0/runs/${encodeURIComponent(id)}/execution`),
  evidence: (id: string) => request<DeliveryEvidence>(`/api/v0/runs/${encodeURIComponent(id)}/evidence`),
  stopRun: (id: string, key: string) => post<ExecutionCommand>(`/api/v0/runs/${encodeURIComponent(id)}/stop`, {}, key),
  resumeRun: (id: string, key: string) => post<ExecutionCommand>(`/api/v0/runs/${encodeURIComponent(id)}/resume`, {}, key),
  reviseRun: (id: string, text: string, checkpoint: string, key: string, providerLimit?: number) =>
    post<ExecutionCommand>(`/api/v0/runs/${encodeURIComponent(id)}/revise`, {
      text, expected_checkpoint_id: checkpoint,
      ...(providerLimit === undefined ? {} : { provider_limit: providerLimit }),
    }, key),
  reviewMission: (id: string, action: "approve" | "revise", missionRef: ArtifactRef,
    checkpoint: string, feedback: string | undefined, key: string) =>
    post<ExecutionCommand>(`/api/v0/runs/${encodeURIComponent(id)}/mission-review`, {
      action, mission_ref: missionRef, expected_checkpoint_id: checkpoint,
      ...(action === "revise" ? { feedback } : {}),
    }, key),
  reviewQuality: (id: string, action: "retry" | "accept", qualityRef: ArtifactRef,
    lessonRef: ArtifactRef, checkpoint: string, reason: string | undefined, key: string) =>
    post<ExecutionCommand>(`/api/v0/runs/${encodeURIComponent(id)}/quality-review`, {
      action, quality_ref: qualityRef, lesson_ref: lessonRef,
      expected_checkpoint_id: checkpoint,
      ...(action === "accept" ? { reason } : {}),
    }, key),
};
