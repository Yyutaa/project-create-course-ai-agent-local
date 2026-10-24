from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


STAGES = (
    "intake",
    "mission",
    "blueprint",
    "batch_plan",
    "generation",
    "quality",
    "release",
)
BLUEPRINT_CHAPTER_DEVIATION_REASON = "blueprint_chapter_deviation"
StageName = Literal[
    "intake", "mission", "blueprint", "batch_plan", "generation", "quality", "release"
]
StageStatus = Literal[
    "pending", "running", "succeeded", "failed", "waiting_for_human", "stopped"
]
AgentRole = Literal["mission", "blueprint", "writer", "reviewer", "repair"]
RunStatus = Literal[
    "running", "failed", "waiting_for_human", "ready_for_release", "stopped",
    "published",
]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SourcePolicy = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
]
DEFAULT_SOURCE_POLICY = "仅允许使用公开官方资料"
ContextTerm = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
ContextPromise = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
BatchIndex = Annotated[int, Field(ge=0)]
ArtifactKind = Literal["mission", "blueprint", "batch_plan", "lesson", "quality"]
ProducerRole = AgentRole | Literal["system"]
GraphNode = StageName | Literal["repair", "verification", "route_error"]
GraphOutcome = Literal[
    "pending", "succeeded", "failed", "waiting_for_human", "stopped", "unknown"
]
ApprovalStatus = Literal["not_requested", "waiting_for_human", "prepare", "stop"]


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: NonEmptyText
    artifact_id: NonEmptyText
    version: int = Field(ge=1)
    kind: ArtifactKind
    content_hash: NonEmptyText


class LoopCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_iterations: int = Field(default=0, ge=0)
    blueprint_replans: int = Field(default=0, ge=0, le=1)
    repair_attempts: int = Field(default=0, ge=0)
    finding_attempts: dict[str, int] = Field(default_factory=dict)


class GraphState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: NonEmptyText
    current_node: GraphNode = "intake"
    artifact_refs: dict[str, ArtifactRef] = Field(default_factory=dict)
    batch_cursor: int = Field(default=0, ge=0)
    quality_cursor: int = Field(default=0, ge=0)
    active_finding_id: str | None = None
    approval_status: ApprovalStatus = "not_requested"
    loop_counts: LoopCounts = Field(default_factory=LoopCounts)
    last_outcome: GraphOutcome = "pending"
    exit_reason: str | None = None


class CourseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: NonEmptyText
    audience: NonEmptyText
    goal: NonEmptyText
    language: Literal["zh"]
    source_policy: SourcePolicy = DEFAULT_SOURCE_POLICY
    expected_chapters: int = Field(default=12, ge=1, le=100)
    min_effective_chars: int = Field(default=12_000, gt=0)
    token_limit: int | None = Field(default=None, gt=0)


class StageRecord(BaseModel):
    name: StageName
    status: StageStatus = "pending"
    input_summary: str = ""
    output_summary: str = ""
    failure_reason: str | None = None


class MissionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audience: NonEmptyText
    learning_goal: NonEmptyText
    scope: NonEmptyText
    stop_conditions: list[NonEmptyText] = Field(min_length=1)


class BlueprintLesson(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NonEmptyText
    learning_goal: NonEmptyText
    evidence: NonEmptyText
    lesson_id: NonEmptyText | None = None
    batch_id: NonEmptyText | None = None


class BlueprintDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lessons: list[BlueprintLesson] = Field(min_length=1, max_length=100)


class ContinuityEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: NonEmptyText
    lesson_id: NonEmptyText
    lesson_ref: ArtifactRef
    summary: str = Field(max_length=800)
    terminology: list[ContextTerm] = Field(default_factory=list, max_length=20)
    next_promises: list[ContextPromise] = Field(default_factory=list, max_length=10)


class BatchPlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batches: list[list[BatchIndex]] = Field(min_length=1, max_length=100)
    batch_ids: list[NonEmptyText] = Field(default_factory=list)
    lesson_ids: list[list[NonEmptyText]] = Field(default_factory=list)
    continuity_ledger: list[ContinuityEntry] = Field(default_factory=list)


class LessonDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NonEmptyText
    markdown: NonEmptyText
    lesson_id: NonEmptyText | None = None
    batch_id: NonEmptyText | None = None
    continuity_summary: str = Field(default="", max_length=800)
    terminology: list[ContextTerm] = Field(default_factory=list, max_length=20)
    next_promises: list[ContextPromise] = Field(default_factory=list, max_length=10)


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: NonEmptyText
    category: Literal["structure", "teaching", "language", "fact"]
    severity: Literal["blocker", "major", "minor"]
    evidence: NonEmptyText = Field(
        description=(
            "必须逐字复制当前 Lesson 单个物理行中的连续文本；不得概括、拼接多行或"
            "使用省略号。无法提供精确摘录时不要生成 Finding。"
        )
    )
    recommendation: NonEmptyText


class GateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate: Literal["deterministic", "source", "rubric", "humanizer"]
    status: Literal["pass", "fail", "error", "not_applicable"]
    rule_id: NonEmptyText
    evidence: NonEmptyText
    artifact_ref: ArtifactRef


class FindingLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lesson_id: NonEmptyText
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    excerpt_hash: NonEmptyText

    @model_validator(mode="after")
    def valid_range(self) -> "FindingLocation":
        if self.line_end < self.line_start:
            raise ValueError("Finding 行区间无效")
        return self


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: NonEmptyText
    run_id: NonEmptyText
    gate: Literal["deterministic", "source", "rubric", "humanizer"]
    rule_id: NonEmptyText
    artifact_ref: ArtifactRef
    location: FindingLocation
    category: Literal["structure", "teaching", "language", "fact"]
    severity: Literal["blocker", "major", "minor"]
    evidence: NonEmptyText
    expected: NonEmptyText

    @model_validator(mode="after")
    def valid_source(self) -> "Finding":
        if self.run_id != self.artifact_ref.run_id or self.artifact_ref.kind != "lesson":
            raise ValueError("Finding 必须关联当前 Run 的 Lesson 版本")
        if self.gate == "humanizer" and self.category != "language":
            raise ValueError("Humanizer 只能产生表达类 Finding")
        return self


class RepairTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: NonEmptyText
    source_ref: ArtifactRef
    line_start: int = Field(ge=1)
    excerpt: NonEmptyText
    excerpt_hash: NonEmptyText
    rule_id: NonEmptyText
    objective: NonEmptyText


class VerificationLink(BaseModel):
    finding_id: NonEmptyText
    candidate_ref: ArtifactRef
    result_start: int = Field(ge=0)
    result_count: int = Field(ge=1)


class QualitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "manual_review"]
    checks: list[NonEmptyText] = Field(min_length=1)
    findings: list[ReviewFinding] = Field(default_factory=list)
    language_risk: NonEmptyText
    limitations: list[NonEmptyText] = Field(min_length=1)
    gate_results: list[GateResult] = Field(default_factory=list)
    evidence_findings: list[Finding] = Field(default_factory=list)
    repair_tasks: list[RepairTask] = Field(default_factory=list)
    verification_results: list[GateResult] = Field(default_factory=list)
    verification_links: list[VerificationLink] = Field(default_factory=list)
    resolved_finding_ids: list[NonEmptyText] = Field(default_factory=list)


class ReleaseDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["prepare", "stop"]
    reason: NonEmptyText


class Publication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: NonEmptyText
    href: NonEmptyText
    published_at: NonEmptyText


class CourseRecord(BaseModel):
    id: NonEmptyText
    title: NonEmptyText
    workspace_key: NonEmptyText


class CourseProgress(CourseRecord):
    run_id: NonEmptyText
    current_stage: StageName
    stage_status: StageStatus


class CourseChapter(BaseModel):
    lesson_id: str | None
    title: NonEmptyText
    status: Literal["pending", "generated"]
    markdown: str | None = None
    version: int | None = None


class RunContent(BaseModel):
    run_id: NonEmptyText
    title: NonEmptyText
    chapters: list[CourseChapter]


class RunRecord(BaseModel):
    id: NonEmptyText
    course_id: NonEmptyText
    status: RunStatus


class IntakeRecord(BaseModel):
    run_id: NonEmptyText
    course_input: CourseInput


class ArtifactRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: NonEmptyText
    version: int = Field(ge=1)
    run_id: NonEmptyText
    kind: ArtifactKind
    content: dict
    content_hash: NonEmptyText
    producer_role: ProducerRole | None = None
    source_refs: list[ArtifactRef] = Field(default_factory=list)
    workspace_relpath: str | None = None


class ArtifactSummary(BaseModel):
    artifact_id: str
    version: int
    kind: ArtifactKind
    content_hash: str
    producer_role: ProducerRole | None = None
    source_refs: list[ArtifactRef] = Field(default_factory=list)


class EventRecord(BaseModel):
    id: int = Field(ge=1)
    run_id: NonEmptyText
    type: NonEmptyText
    stage: StageName | None = None


class WorkspaceRecord(BaseModel):
    course_id: NonEmptyText
    relative_path: NonEmptyText


class V0Run(BaseModel):
    id: str
    course_id: str | None = None
    course_input: CourseInput
    constraints_version: int = Field(default=0, ge=0, le=1)
    source_evidence_version: int = Field(default=0, ge=0, le=1)
    planning_loop_version: int = Field(default=0, ge=0, le=1)
    revision: int = 0
    artifacts: list[ArtifactSummary] = Field(default_factory=list)
    status: RunStatus = "running"
    stages: list[StageRecord] = Field(
        default_factory=lambda: [StageRecord(name=name) for name in STAGES]
    )
    mission: MissionDraft | None = None
    blueprint: BlueprintDraft | None = None
    batch_plan: BatchPlanDraft | None = None
    lesson: LessonDraft | None = None
    quality: QualitySummary | None = None
    release_decision: ReleaseDecision | None = None
    publication: Publication | None = None

    @model_validator(mode="after")
    def validate_stages(self) -> "V0Run":
        if [stage.name for stage in self.stages] != list(STAGES):
            raise ValueError("阶段必须按固定七步排列")
        return self


class SnapshotRecord(BaseModel):
    run_id: NonEmptyText
    revision: int = Field(ge=0)
    run: V0Run
