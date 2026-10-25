"""Validated transient context shapes for runs using contract version 1."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.v0.schemas import ArtifactRef, ContinuityNoteV1


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class _StrictPack(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BriefV1(_StrictPack):
    title: ShortText
    learning_goal: Text
    evidence: Text
    lesson_id: Text | None = None
    batch_id: Text | None = None


class SourceSummaryV1(_StrictPack):
    document_id: Text
    url: Text
    title: ShortText
    excerpt: Annotated[str, StringConstraints(min_length=1, max_length=1500)]
    content_hash: Text


class WriterPackV1(_StrictPack):
    chapter_number: int = Field(ge=1)
    min_effective_chars: int = Field(ge=1)
    brief: BriefV1
    mission_ref: ArtifactRef
    blueprint_ref: ArtifactRef
    batch_plan_ref: ArtifactRef
    source_policy: Text
    source_summaries: list[SourceSummaryV1] = Field(max_length=3)
    source_evidence_status: Literal["missing", "eligible_documents"]
    rule_ids: list[Text] = Field(min_length=1, max_length=30)
    previous_summary: str | None = Field(default=None, max_length=800)
    continuity_ledger: list[ContinuityNoteV1] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_evidence_and_refs(self):
        if self.chapter_number > 1 and not self.previous_summary:
            raise ValueError("非首章必须提供上一章事实摘要")
        if self.source_evidence_status == "eligible_documents" and not self.source_summaries:
            raise ValueError("已准入资料状态必须有来源摘要")
        if self.source_evidence_status == "missing" and self.source_summaries:
            raise ValueError("无来源状态不能包含来源摘要")
        for reference, kind in (
            (self.mission_ref, "mission"),
            (self.blueprint_ref, "blueprint"),
            (self.batch_plan_ref, "batch_plan"),
        ):
            if reference.kind != kind:
                raise ValueError(f"{kind} 引用类型错误")
            if reference.run_id != self.mission_ref.run_id:
                raise ValueError("Writer 引用跨 Run")
        return self


class ReviewerPackV1(_StrictPack):
    chapter_number: int = Field(ge=1)
    brief: BriefV1
    lesson_ref: ArtifactRef
    candidate_markdown: Text
    gate: Literal["rubric", "humanizer"]
    rule_ids: list[Text] = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_lesson_ref(self):
        if self.lesson_ref.kind != "lesson":
            raise ValueError("Reviewer 候选引用必须为 Lesson")
        return self


class RepairPackV1(_StrictPack):
    finding_id: Text
    lesson_ref: ArtifactRef
    quality_ref: ArtifactRef
    line_number: int = Field(ge=1)
    excerpt: Text
    excerpt_hash: Text
    rule_id: Text
    target: Text

    @model_validator(mode="after")
    def validate_refs(self):
        if self.lesson_ref.kind != "lesson" or self.quality_ref.kind != "quality":
            raise ValueError("Repair 引用类型错误")
        if self.lesson_ref.run_id != self.quality_ref.run_id:
            raise ValueError("Repair 引用跨 Run")
        return self
