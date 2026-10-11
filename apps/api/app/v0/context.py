"""Role-scoped, transient context packs built from exact Artifact references."""

import json
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field

from app.v0.provider import AgentInput
from app.v0.schemas import AgentRole, ArtifactRecord, ArtifactRef, CourseInput


CONTEXT_BUDGETS: dict[AgentRole, int] = {
    "mission": 4_000,
    "blueprint": 8_000,
    "writer": 12_000,
    "reviewer": 24_000,
    "repair": 4_000,
}


class ContextBudgetError(ValueError):
    code = "context_budget_exceeded"


class ContextPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AgentRole
    inputs: list[AgentInput] = Field(min_length=1)
    budget: int = Field(gt=0)
    total_chars: int = Field(ge=0)
    truncated: bool = False


class ContextPackBuilder:
    def __init__(self, loader: Callable[[str, int], ArtifactRecord]):
        self.loader = loader

    def for_mission(self, course_input: CourseInput) -> ContextPack:
        return self._pack(
            "mission",
            [AgentInput(kind="intake", content=course_input.model_dump())],
        )

    def for_mission_revision(
        self, run_id: str, course_input: CourseInput,
        prior_ref: ArtifactRef, feedback: str,
    ) -> ContextPack:
        prior = self._load(run_id, prior_ref)
        if prior_ref.kind != "mission":
            raise ValueError("Mission 修订来源必须是 Mission Artifact")
        return self._pack(
            "mission",
            [AgentInput(kind="intake", content={
                **course_input.model_dump(),
                "revision_request": {
                    "feedback": feedback,
                    "prior_ref": prior_ref.model_dump(),
                    "prior_mission": prior.content,
                },
            })],
        )

    def for_blueprint(self, run_id: str, mission_ref: ArtifactRef) -> ContextPack:
        mission = self._load(run_id, mission_ref)
        return self._pack(
            "blueprint",
            [
                AgentInput(
                    kind="mission",
                    reference=mission_ref,
                    content={
                        "mission": mission.content,
                        "source_summaries": [],
                        "source_limitations": ["当前 Run 未提供已批准来源摘要"],
                    },
                )
            ],
        )

    def for_writer(
        self,
        run_id: str,
        mission_ref: ArtifactRef,
        blueprint_ref: ArtifactRef,
        batch_plan_ref: ArtifactRef,
        *,
        lesson_index: int,
        previous_lesson_ref: ArtifactRef | None = None,
    ) -> ContextPack:
        self._load(run_id, mission_ref)
        blueprint = self._load(run_id, blueprint_ref)
        plan = self._load(run_id, batch_plan_ref)
        try:
            brief = blueprint.content["lessons"][lesson_index]
        except (IndexError, KeyError, TypeError) as error:
            raise ValueError("Writer 章节索引不在 Blueprint 中") from error

        previous_summary = ""
        if previous_lesson_ref is not None:
            previous = self._load(run_id, previous_lesson_ref)
            previous_summary = str(previous.content.get("continuity_summary", ""))
        ledger = [
            {
                "lesson_id": entry.get("lesson_id"),
                "summary": entry.get("summary", ""),
                "terminology": entry.get("terminology", []),
                "next_promises": entry.get("next_promises", []),
            }
            for entry in plan.content.get("continuity_ledger", [])
        ]
        inputs = self._writer_inputs(
            mission_ref,
            blueprint_ref,
            batch_plan_ref,
            brief,
            previous_summary,
            ledger,
        )
        truncated = False
        for field, empty in (
            ("summary", ""),
            ("terminology", []),
            ("next_promises", []),
        ):
            for entry in ledger[:-1]:
                if self._length(inputs) <= CONTEXT_BUDGETS["writer"]:
                    break
                if entry[field]:
                    entry[field] = empty
                    truncated = True
                    inputs = self._writer_inputs(
                        mission_ref,
                        blueprint_ref,
                        batch_plan_ref,
                        brief,
                        previous_summary,
                        ledger,
                    )
        return self._pack("writer", inputs, truncated=truncated)

    def for_reviewer(
        self,
        run_id: str,
        mission_ref: ArtifactRef,
        blueprint_ref: ArtifactRef,
        lesson_ref: ArtifactRef,
        *,
        lesson_index: int,
    ) -> ContextPack:
        self._load(run_id, mission_ref)
        blueprint = self._load(run_id, blueprint_ref)
        lesson = self._load(run_id, lesson_ref)
        try:
            brief = blueprint.content["lessons"][lesson_index]
        except (IndexError, KeyError, TypeError) as error:
            raise ValueError("Reviewer 章节索引不在 Blueprint 中") from error
        return self._pack(
            "reviewer",
            [
                AgentInput(kind="mission", reference=mission_ref, content={}),
                AgentInput(
                    kind="blueprint",
                    reference=blueprint_ref,
                    content={"current_lesson_brief": brief},
                ),
                AgentInput(
                    kind="lesson",
                    reference=lesson_ref,
                    content={
                        "candidate": lesson.content,
                        "minimum_rubric": [
                            "结构完整且学习目标可观察",
                            "中文表达风险必须披露",
                            "不得把语言判断当成事实核验",
                        ],
                    },
                ),
            ],
        )

    def _load(self, run_id: str, reference: ArtifactRef) -> ArtifactRecord:
        record = self.loader(reference.artifact_id, reference.version)
        if record.run_id != run_id or reference.run_id != run_id:
            raise ValueError("Context Artifact 与当前 Run 不一致")
        if record.kind != reference.kind or record.content_hash != reference.content_hash:
            raise ValueError("Context Artifact 引用与事实不一致")
        return record

    @staticmethod
    def _writer_inputs(
        mission_ref: ArtifactRef,
        blueprint_ref: ArtifactRef,
        batch_plan_ref: ArtifactRef,
        brief: dict,
        previous_summary: str,
        ledger: list[dict],
    ) -> list[AgentInput]:
        return [
            AgentInput(kind="mission", reference=mission_ref, content={}),
            AgentInput(
                kind="blueprint",
                reference=blueprint_ref,
                content={"current_lesson_brief": brief},
            ),
            AgentInput(
                kind="batch_plan",
                reference=batch_plan_ref,
                content={
                    "batch_id": brief.get("batch_id"),
                    "previous_lesson_summary": previous_summary,
                    "continuity_ledger": ledger,
                },
            ),
        ]

    def _pack(
        self,
        role: AgentRole,
        inputs: list[AgentInput],
        *,
        truncated: bool = False,
    ) -> ContextPack:
        total = self._length(inputs)
        budget = CONTEXT_BUDGETS[role]
        if total > budget:
            raise ContextBudgetError(f"{role} Context Pack 超过 {budget} 字符预算")
        return ContextPack(
            role=role,
            inputs=inputs,
            budget=budget,
            total_chars=total,
            truncated=truncated,
        )

    @staticmethod
    def _length(inputs: list[AgentInput]) -> int:
        return len(
            json.dumps(
                [item.model_dump(mode="json") for item in inputs],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
