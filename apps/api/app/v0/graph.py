"""Explicit LangGraph control flow for the seven-stage course workflow."""

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.v0.batching import assign_blueprint_ids, build_batch_plan, complete_batch
from app.v0.context import ContextBudgetError, ContextPackBuilder
from app.v0.budget import BudgetExceeded
from app.v0.sensitive import safe_error
from app.v0.provider import AgentInput, ProviderError
from app.v0.quality_loop import (
    GateReport,
    apply_repair,
    check_markdown,
    make_repair_task,
    review_gate,
)
from app.v0.runner import V0_QUALITY_LIMITATIONS
from app.v0.schemas import (
    BLUEPRINT_CHAPTER_DEVIATION_REASON,
    GraphState,
    QualitySummary,
    ReleaseDecision,
    VerificationLink,
)


class GraphRouteError(ValueError):
    """State or persisted plan violates a control-flow invariant."""


def _route_standard(state: GraphState, success_target: str) -> str:
    if state.last_outcome == "succeeded":
        return success_target
    if state.last_outcome in ("failed", "waiting_for_human"):
        return END
    return "route_error"


def route_start(state: GraphState) -> str:
    if state.current_node == "intake" and state.approval_status == "not_requested":
        return "intake"
    if state.current_node == "release" and state.approval_status in ("prepare", "stop"):
        return "release"
    return "route_error"


def route_after_intake(state: GraphState) -> str:
    return _route_standard(state, "mission")


def route_after_mission(state: GraphState) -> str:
    return _route_standard(state, "blueprint")


def route_after_blueprint(state: GraphState) -> str:
    return _route_standard(state, "batch_plan")


def route_after_batch_plan(state: GraphState) -> str:
    return _route_standard(state, "generation")


def route_after_generation(state: GraphState) -> str:
    if state.last_outcome == "succeeded":
        if state.exit_reason == "more_batches":
            return "generation"
        if state.exit_reason == "all_batches_complete":
            return "quality"
        return "route_error"
    if state.last_outcome in ("failed", "waiting_for_human"):
        return END
    return "route_error"


def route_after_quality(state: GraphState) -> str:
    if state.last_outcome == "succeeded":
        return {
            "all_lessons_ready": "release",
            "more_lessons": "quality",
            "repair_needed": "repair",
        }.get(state.exit_reason or "", "route_error")
    if state.last_outcome in ("failed", "waiting_for_human"):
        return END
    return "route_error"


def route_after_repair(state: GraphState) -> str:
    return _route_standard(state, "verification")


def route_after_verification(state: GraphState) -> str:
    if state.last_outcome == "succeeded":
        return {
            "candidate_accepted": "quality",
            "all_lessons_ready": "release",
            "repair_needed": "repair",
        }.get(state.exit_reason or "", "route_error")
    if state.last_outcome in ("failed", "waiting_for_human"):
        return END
    return "route_error"


def route_after_release(state: GraphState) -> str:
    if state.last_outcome in (
        "succeeded",
        "failed",
        "waiting_for_human",
        "stopped",
    ):
        return END
    return "route_error"


class WorkflowNodes:
    def __init__(
        self,
        runner: Any,
        release_decision: ReleaseDecision | None = None,
        request_key: str | None = None,
    ):
        self.runner = runner
        self.context = ContextPackBuilder(runner._load_artifact)
        self.release_decision = release_decision
        self.request_key = request_key

    def intake(self, state: GraphState) -> dict:
        return self._stage(state, "intake", self._intake)

    def mission(self, state: GraphState) -> dict:
        return self._stage(state, "mission", self._mission)

    def blueprint(self, state: GraphState) -> dict:
        return self._stage(state, "blueprint", self._blueprint)

    def batch_plan(self, state: GraphState) -> dict:
        return self._stage(state, "batch_plan", self._batch_plan)

    def generation(self, state: GraphState) -> dict:
        return self._stage(state, "generation", self._generation)

    def quality(self, state: GraphState) -> dict:
        return self._stage(state, "quality", self._quality)

    def repair(self, state: GraphState) -> dict:
        return self._stage(state, "quality", self._repair)

    def verification(self, state: GraphState) -> dict:
        return self._stage(state, "quality", self._verification)

    def release(self, state: GraphState) -> dict:
        if state.approval_status == "not_requested":
            with self.runner._lock:
                run = self.runner._current(state.run_id)
                run.status = "waiting_for_human"
                release = run.stages[-1]
                release.status = "waiting_for_human"
                release.input_summary = "最小质量检查已达到人工决定条件"
                self.runner._commit(run, "release.waiting", "release")
            return {
                "current_node": "release",
                "approval_status": "waiting_for_human",
                "last_outcome": "waiting_for_human",
                "exit_reason": "release_waiting",
            }
        if (
            state.approval_status in ("prepare", "stop")
            and self.release_decision is not None
            and self.release_decision.action == state.approval_status
        ):
            self.runner._record_release_decision(
                state.run_id,
                self.release_decision,
                self.request_key,
            )
            return {
                "current_node": "release",
                "last_outcome": (
                    "succeeded" if state.approval_status == "prepare" else "stopped"
                ),
                "exit_reason": f"release_{state.approval_status}",
            }
        return {"current_node": "release", "last_outcome": "unknown"}

    def route_error(self, state: GraphState) -> dict:
        run = self.runner.get(state.run_id)
        active = next(
            (
                index
                for index, stage in enumerate(run.stages)
                if stage.status in ("running", "pending")
            ),
            len(run.stages) - 1,
        )
        self.runner._mark_failed(state.run_id, active, "未知 Graph 路由状态")
        return {
            "current_node": "route_error",
            "last_outcome": "failed",
            "exit_reason": "unknown_route_state",
        }

    def _stage(self, state: GraphState, stage: str, action) -> dict:
        index = self.runner.stage_index(stage)
        if not (
            self.runner._recovery_effect
            and self.runner._recovery_effect["stage"] == stage
        ):
            current = self.runner.get(state.run_id)
            self.runner._mark_running(
                state.run_id,
                index,
                self.runner._input_summary(stage, current),
            )
        try:
            return action(state, index)
        except GraphRouteError:
            return {
                "current_node": stage,
                "last_outcome": "unknown",
                "exit_reason": "invalid_graph_state",
            }
        except (ContextBudgetError, BudgetExceeded) as error:
            self.runner._mark_waiting(state.run_id, index, str(error))
            return {
                "current_node": stage,
                "last_outcome": "waiting_for_human",
                "exit_reason": error.code,
            }
        except (ProviderError, ValueError) as error:
            self.runner._mark_failed(state.run_id, index, safe_error(error))
        except Exception:
            self.runner._mark_failed(
                state.run_id,
                index,
                "阶段执行失败；请检查服务端日志",
            )
        return {"current_node": stage, "last_outcome": "failed"}

    def _intake(self, state: GraphState, index: int) -> dict:
        run = self.runner.get(state.run_id)
        self.runner._mark_succeeded(
            state.run_id,
            index,
            "intake",
            run.course_input,
            f"已接收主题「{run.course_input.topic}」",
            None,
            [],
        )
        return {"current_node": "intake", "last_outcome": "succeeded"}

    def _mission(self, state: GraphState, index: int) -> dict:
        run = self.runner.get(state.run_id)
        prior_ref = state.artifact_refs.get("mission")
        review = (
            self.runner.store.latest_mission_review(state.run_id)
            if self.runner.store and self.runner.store.mission_review_required(state.run_id)
            else None
        )
        if prior_ref is not None and (
            review is None or review["artifact_id"] != prior_ref.artifact_id
            or review["artifact_version"] != prior_ref.version
            or review["content_hash"] != prior_ref.content_hash
        ):
            self.runner.artifact_tools.read_artifact(
                "mission", state.run_id, prior_ref
            )
            self.runner._mark_waiting(state.run_id, index, "Mission 待人工确认")
            return {
                "current_node": "mission", "artifact_refs": state.artifact_refs,
                "last_outcome": "waiting_for_human",
                "exit_reason": "mission_review_required",
            }
        if review and review["action"] == "revise" and prior_ref:
            pack = self.context.for_mission_revision(
                state.run_id, run.course_input, prior_ref, review["feedback"]
            )
            sources = [prior_ref]
        else:
            pack = self.context.for_mission(run.course_input)
            sources = []
        result = self.runner.executor.invoke("mission", state.run_id, inputs=pack.inputs)
        self.runner._write_role_success(
            "mission",
            state.run_id,
            index,
            "mission",
            result,
            result.learning_goal,
            sources,
        )
        reference = self.runner._source_refs(state.run_id, ("mission",))[0]
        if self.runner.store and self.runner.store.mission_review_required(state.run_id):
            self.runner._mark_waiting(
                state.run_id, index, "Mission 待人工确认"
            )
            return {
                "current_node": "mission",
                "artifact_refs": {**state.artifact_refs, "mission": reference},
                "last_outcome": "waiting_for_human",
                "exit_reason": "mission_review_required",
            }
        return {
            "current_node": "mission",
            "artifact_refs": {**state.artifact_refs, "mission": reference},
            "last_outcome": "succeeded",
        }

    def _blueprint(self, state: GraphState, index: int) -> dict:
        run = self.runner.get(state.run_id)
        mission_ref = self._ref(state, "mission")
        if self.runner.store and self.runner.store.mission_review_required(state.run_id):
            review = self.runner.store.latest_mission_review(state.run_id)
            if not review or review["action"] != "approve" or (
                review["artifact_id"] != mission_ref.artifact_id
                or review["artifact_version"] != mission_ref.version
                or review["content_hash"] != mission_ref.content_hash
            ):
                raise GraphRouteError("Blueprint 缺少当前 Mission 版本的人工确认")
        pack = self.context.for_blueprint(
            state.run_id,
            mission_ref,
            expected_chapters=(
                run.course_input.expected_chapters
                if run.constraints_version == 1
                else None
            ),
        )
        candidate = self.runner.executor.invoke(
            "blueprint", state.run_id, inputs=pack.inputs
        )
        result = assign_blueprint_ids(candidate)
        self.runner._write_role_success(
            "blueprint",
            state.run_id,
            index,
            "blueprint",
            result,
            result.lessons[0].title,
            [mission_ref],
        )
        reference = self.runner._source_refs(state.run_id, ("blueprint",))[0]
        return {
            "current_node": "blueprint",
            "artifact_refs": {**state.artifact_refs, "blueprint": reference},
            "last_outcome": "succeeded",
        }

    def _batch_plan(self, state: GraphState, index: int) -> dict:
        blueprint_ref = self._ref(state, "blueprint")
        run = self.runner.get(state.run_id)
        blueprint = run.blueprint
        if blueprint is None:
            raise ValueError("Batch Plan 缺少 Blueprint")
        if run.constraints_version == 1:
            self.runner._record_artifact_event(
                state.run_id,
                "blueprint.chapter_count_observed",
                "batch_plan",
                blueprint_ref,
            )
            outside_tolerance = (
                abs(len(blueprint.lessons) - run.course_input.expected_chapters) > 1
            )
            accepted = self.runner._has_artifact_event(
                state.run_id,
                "blueprint.chapter_deviation_accepted",
                blueprint_ref,
            )
            if outside_tolerance and not accepted:
                self.runner._mark_waiting(
                    state.run_id,
                    index,
                    BLUEPRINT_CHAPTER_DEVIATION_REASON,
                )
                return {
                    "current_node": "batch_plan",
                    "last_outcome": "waiting_for_human",
                    "exit_reason": "blueprint_chapter_deviation",
                }
        result = build_batch_plan(blueprint)
        self.runner._mark_succeeded(
            state.run_id,
            index,
            "batch_plan",
            result,
            f"{len(result.batches)} 个批次，{len(blueprint.lessons)} 章",
            "system",
            [blueprint_ref],
        )
        reference = self.runner._source_refs(state.run_id, ("batch_plan",))[0]
        return {
            "current_node": "batch_plan",
            "artifact_refs": {**state.artifact_refs, "batch_plan": reference},
            "last_outcome": "succeeded",
        }

    def _generation(self, state: GraphState, index: int) -> dict:
        run = self.runner.get(state.run_id)
        if run.batch_plan is None or run.blueprint is None:
            raise ValueError("Generation 缺少 Blueprint 或 Batch Plan")
        if (
            state.batch_cursor >= len(run.batch_plan.batches)
            or state.batch_cursor >= len(run.batch_plan.batch_ids)
            or state.batch_cursor >= len(run.batch_plan.lesson_ids)
        ):
            raise GraphRouteError("Generation batch cursor 越界")
        if state.loop_counts.batch_iterations >= 20:
            self.runner._mark_waiting(
                state.run_id,
                index,
                "批次循环达到 20 次上限，需要人工处理",
            )
            return {
                "current_node": "generation",
                "last_outcome": "waiting_for_human",
                "exit_reason": "batch_limit_exceeded",
            }
        lesson_indexes = run.batch_plan.batches[state.batch_cursor]
        expected_ids = run.batch_plan.lesson_ids[state.batch_cursor]
        batch_id = run.batch_plan.batch_ids[state.batch_cursor]
        if any(entry.batch_id == batch_id for entry in run.batch_plan.continuity_ledger):
            cursor = state.batch_cursor + 1
            if cursor == len(run.batch_plan.batches):
                self.runner._mark_stage_succeeded(
                    state.run_id, index, f"已完成 {cursor} 个批次"
                )
            return {
                "current_node": "generation",
                "artifact_refs": state.artifact_refs,
                "batch_cursor": cursor,
                "loop_counts": state.loop_counts.model_copy(
                    update={"batch_iterations": state.loop_counts.batch_iterations + 1}
                ),
                "last_outcome": "succeeded",
                "exit_reason": (
                    "all_batches_complete" if cursor == len(run.batch_plan.batches)
                    else "more_batches"
                ),
            }
        if len(lesson_indexes) != len(expected_ids):
            raise GraphRouteError("Batch Plan 的索引与 lesson_id 数量不一致")
        for lesson_index, expected_id in zip(lesson_indexes, expected_ids, strict=True):
            if lesson_index < 0 or lesson_index >= len(run.blueprint.lessons):
                raise GraphRouteError("Batch Plan 章节索引越界")
            brief = run.blueprint.lessons[lesson_index]
            if brief.lesson_id != expected_id or brief.batch_id != batch_id:
                raise GraphRouteError("Blueprint 与 Batch Plan 的 ID 不一致")
        mission_ref = self._ref(state, "mission")
        blueprint_ref = self._ref(state, "blueprint")
        batch_plan_ref = self._ref(state, "batch_plan")
        artifact_refs = dict(state.artifact_refs)
        completed = []
        source_refs = [mission_ref, blueprint_ref, batch_plan_ref]
        for lesson_index in lesson_indexes:
            brief = run.blueprint.lessons[lesson_index]
            existing_ref = artifact_refs.get(f"lesson:{brief.lesson_id}")
            if existing_ref is not None:
                from app.v0.schemas import LessonDraft

                existing = self.runner._load_artifact(
                    existing_ref.artifact_id, existing_ref.version
                )
                if existing.run_id != state.run_id or existing.content_hash != existing_ref.content_hash:
                    raise GraphRouteError("已提交 Lesson 引用不匹配")
                completed.append((LessonDraft.model_validate(existing.content), existing_ref))
                continue
            previous_ref = None
            if lesson_index > 0:
                previous_id = run.blueprint.lessons[lesson_index - 1].lesson_id
                previous_ref = artifact_refs.get(f"lesson:{previous_id}")
            pack = self.context.for_writer(
                state.run_id,
                mission_ref,
                blueprint_ref,
                batch_plan_ref,
                lesson_index=lesson_index,
                previous_lesson_ref=previous_ref,
                min_effective_chars=(
                    run.course_input.min_effective_chars
                    if run.constraints_version == 1
                    else None
                ),
            )
            candidate = self.runner.executor.invoke(
                "writer", state.run_id, inputs=pack.inputs
            )
            result = candidate.model_copy(
                update={
                    "lesson_id": brief.lesson_id,
                    "batch_id": brief.batch_id,
                    "continuity_summary": candidate.continuity_summary
                    or candidate.title[:800],
                }
            )
            self.runner.artifact_tools.write_candidate_artifact(
                "writer",
                state.run_id,
                "lesson",
                result,
                source_refs,
                lambda item: self.runner._persist_candidate(
                    state.run_id, "generation", item
                ),
            )
            lesson_ref = self.runner._source_refs(state.run_id, ("lesson",))[0]
            artifact_refs[f"lesson:{brief.lesson_id}"] = lesson_ref
            completed.append((result, lesson_ref))

        updated_plan = complete_batch(run.batch_plan, batch_id, completed)
        self.runner._persist_system_artifact(
            state.run_id,
            "batch_plan",
            updated_plan,
            [batch_plan_ref, *[reference for _, reference in completed]],
        )
        batch_plan_ref = self.runner._source_refs(state.run_id, ("batch_plan",))[0]
        artifact_refs["batch_plan"] = batch_plan_ref
        cursor = state.batch_cursor + 1
        reason = (
            "all_batches_complete"
            if cursor == len(run.batch_plan.batches)
            else "more_batches"
        )
        if reason == "all_batches_complete":
            self.runner._mark_stage_succeeded(
                state.run_id,
                index,
                f"已完成 {cursor} 个批次",
            )
        return {
            "current_node": "generation",
            "artifact_refs": artifact_refs,
            "batch_cursor": cursor,
            "loop_counts": state.loop_counts.model_copy(
                update={"batch_iterations": state.loop_counts.batch_iterations + 1}
            ),
            "last_outcome": "succeeded",
            "exit_reason": reason,
        }

    def _quality(self, state: GraphState, index: int) -> dict:
        run = self.runner.get(state.run_id)
        if run.blueprint is None or state.quality_cursor >= len(run.blueprint.lessons):
            raise ValueError("Quality 缺少 Blueprint")
        brief = run.blueprint.lessons[state.quality_cursor]
        lesson_ref = self._ref(state, f"lesson:{brief.lesson_id}")
        quality_sources = [
            self._ref(state, "mission"),
            self._ref(state, "blueprint"),
            lesson_ref,
        ]
        report = self._evaluate(state, lesson_ref)
        summary = self._quality_summary(run.quality, report)
        if any(item.status != "pass" for item in report.results):
            finding = report.findings[0] if report.findings else None
            if finding is None or finding.category == "fact":
                self.runner._mark_waiting(
                    state.run_id,
                    index,
                    "质量证据需要人工复核",
                    summary,
                    "system",
                    quality_sources,
                )
                return {"current_node": "quality", "last_outcome": "waiting_for_human"}
            if not self._has_repair_budget(state, finding.finding_id):
                self.runner._mark_waiting(
                    state.run_id,
                    index,
                    "返工预算耗尽，需要人工处理",
                    summary,
                    "system",
                    quality_sources,
                )
                return {"current_node": "quality", "last_outcome": "waiting_for_human"}
            self.runner._persist_system_artifact(
                state.run_id, "quality", summary, quality_sources
            )
            quality_ref = self.runner._source_refs(state.run_id, ("quality",))[0]
            return {
                "current_node": "quality",
                "artifact_refs": {**state.artifact_refs, "quality": quality_ref},
                "active_finding_id": finding.finding_id,
                "last_outcome": "succeeded",
                "exit_reason": "repair_needed",
            }
        self.runner._persist_system_artifact(
            state.run_id, "quality", summary, quality_sources
        )
        quality_ref = self.runner._source_refs(state.run_id, ("quality",))[0]
        cursor = state.quality_cursor + 1
        if cursor == len(run.blueprint.lessons):
            self.runner._mark_stage_succeeded(
                state.run_id, index, f"{cursor} 章分层质量 Gate 已通过"
            )
        return {
            "current_node": "quality",
            "quality_cursor": cursor,
            "artifact_refs": {**state.artifact_refs, "quality": quality_ref},
            "last_outcome": "succeeded",
            "exit_reason": (
                "all_lessons_ready"
                if cursor == len(run.blueprint.lessons)
                else "more_lessons"
            ),
        }

    def recover_quality(self, state: GraphState, effect: dict) -> dict:
        """Finish a quality iteration whose result Artifact already committed."""
        run = self.runner.get(state.run_id)
        reference = state.artifact_refs.get("quality")
        if run.quality is None or reference is None:
            raise GraphRouteError("Quality checkpoint 缺少已提交 Artifact")
        if effect["type"] == "artifact.created" and (
            reference.artifact_id != effect["artifact_id"]
            or reference.version != effect["artifact_version"]
        ):
            raise GraphRouteError("Quality checkpoint 的 Artifact 不匹配")
        if run.quality.status == "ready":
            cursor = state.quality_cursor + 1
            if cursor == len(run.blueprint.lessons) and run.stages[5].status != "succeeded":
                self.runner._mark_stage_succeeded(
                    state.run_id, 5, f"{cursor} 章分层质量 Gate 已通过"
                )
            return {
                "current_node": "quality",
                "artifact_refs": state.artifact_refs,
                "quality_cursor": cursor,
                "last_outcome": "succeeded",
                "exit_reason": (
                    "all_lessons_ready"
                    if cursor == len(run.blueprint.lessons) else "more_lessons"
                ),
            }
        finding = run.quality.evidence_findings[-1] if run.quality.evidence_findings else None
        if finding is None or not self._has_repair_budget(state, finding.finding_id):
            raise GraphRouteError("Quality checkpoint 缺少可恢复 Finding")
        return {
            "current_node": "quality",
            "artifact_refs": state.artifact_refs,
            "active_finding_id": finding.finding_id,
            "last_outcome": "succeeded",
            "exit_reason": "repair_needed",
        }

    def _evaluate(self, state: GraphState, lesson_ref) -> GateReport:
        run = self.runner.get(state.run_id)
        brief = run.blueprint.lessons[state.quality_cursor]
        lesson = self.runner._load_artifact(lesson_ref.artifact_id, lesson_ref.version)
        markdown = str(lesson.content["markdown"])
        reports = [check_markdown(markdown, lesson_ref, brief.lesson_id)]
        if reports[-1].findings:
            return reports[-1]
        pack = self.context.for_reviewer(
            state.run_id,
            self._ref(state, "mission"),
            self._ref(state, "blueprint"),
            lesson_ref,
            lesson_index=state.quality_cursor,
        )
        reports.append(
            review_gate(
                self.runner,
                "rubric",
                lesson_ref,
                brief.lesson_id,
                markdown,
                pack.inputs,
            )
        )
        if reports[-1].results[0].status != "pass":
            return GateReport(
                [result for report in reports for result in report.results],
                [finding for report in reports for finding in report.findings],
            )
        reports.append(
            review_gate(
                self.runner,
                "humanizer",
                lesson_ref,
                brief.lesson_id,
                markdown,
                [],
            )
        )
        return GateReport(
            [result for report in reports for result in report.results],
            [finding for report in reports for finding in report.findings],
        )

    @staticmethod
    def _quality_summary(previous: QualitySummary | None, report: GateReport):
        status = (
            "ready"
            if all(item.status == "pass" for item in report.results)
            else "manual_review"
        )
        return QualitySummary(
            status=status,
            checks=[f"{item.gate}:{item.rule_id}:{item.status}" for item in report.results],
            findings=[],
            language_risk=(
                "表达 Gate 已通过"
                if report.results[-1].gate == "humanizer"
                and report.results[-1].status == "pass"
                else "表达 Gate 尚未通过"
            ),
            limitations=list(V0_QUALITY_LIMITATIONS),
            gate_results=[*(previous.gate_results if previous else []), *report.results],
            evidence_findings=[
                *(previous.evidence_findings if previous else []),
                *report.findings,
            ],
            repair_tasks=list(previous.repair_tasks if previous else []),
            verification_results=list(previous.verification_results if previous else []),
            verification_links=list(previous.verification_links if previous else []),
            resolved_finding_ids=list(previous.resolved_finding_ids if previous else []),
        )

    @staticmethod
    def _has_repair_budget(state: GraphState, finding_id: str) -> bool:
        return (
            state.loop_counts.repair_attempts < 3
            and state.loop_counts.finding_attempts.get(finding_id, 0) < 2
        )

    def _repair(self, state: GraphState, index: int) -> dict:
        run = self.runner.get(state.run_id)
        if run.quality is None or state.active_finding_id is None:
            raise GraphRouteError("Repair 缺少 Finding")
        finding = next(
            (
                item
                for item in reversed(run.quality.evidence_findings)
                if item.finding_id == state.active_finding_id
            ),
            None,
        )
        if finding is None or not self._has_repair_budget(state, finding.finding_id):
            self.runner._mark_waiting(state.run_id, index, "返工预算耗尽，需要人工处理")
            return {"current_node": "repair", "last_outcome": "waiting_for_human"}
        source_ref = finding.artifact_ref
        source = self.runner._load_artifact(source_ref.artifact_id, source_ref.version)
        effect = self.runner._recovery_effect
        if effect and effect["type"] == "artifact.created" and effect["stage"] == "quality":
            quality_ref = self._ref(state, "quality")
            if (
                quality_ref.artifact_id != effect["artifact_id"]
                or quality_ref.version != effect["artifact_version"]
                or not run.quality.repair_tasks
                or run.quality.repair_tasks[-1].finding_id != finding.finding_id
            ):
                raise GraphRouteError("Repair checkpoint 的任务 Artifact 不匹配")
            task = run.quality.repair_tasks[-1]
        else:
            task = make_repair_task(finding, str(source.content["markdown"]))
            quality = run.quality.model_copy(deep=True)
            quality.repair_tasks.append(task)
            self.runner._persist_system_artifact(
                state.run_id, "quality", quality, [source_ref, self._ref(state, "quality")]
            )
            quality_ref = self.runner._source_refs(state.run_id, ("quality",))[0]
        blueprint_ref = self._ref(state, "blueprint")
        inputs = [
            AgentInput(kind="blueprint", reference=blueprint_ref, content={}),
            AgentInput(
                kind="lesson", reference=source_ref, content={"excerpt": task.excerpt}
            ),
            AgentInput(
                kind="quality",
                reference=quality_ref,
                content={"repair_task": task.model_dump(mode="json")},
            ),
        ]
        self.context._pack("repair", inputs)
        patch = self.runner.executor.invoke("repair", state.run_id, inputs=inputs)
        from app.v0.schemas import LessonDraft

        original = LessonDraft.model_validate(source.content)
        candidate = apply_repair(task, patch.markdown, original)
        candidate_ref = self.runner.artifact_tools.write_candidate_artifact(
            "repair",
            state.run_id,
            "lesson",
            candidate,
            [blueprint_ref, source_ref, quality_ref],
            lambda item: self.runner._persist_repair_candidate(
                state.run_id, item.content, item.source_refs
            ),
        )
        counts = dict(state.loop_counts.finding_attempts)
        counts[finding.finding_id] = counts.get(finding.finding_id, 0) + 1
        return {
            "current_node": "repair",
            "last_outcome": "succeeded",
            "artifact_refs": {
                **state.artifact_refs,
                "quality": quality_ref,
                "candidate": candidate_ref,
            },
            "loop_counts": state.loop_counts.model_copy(
                update={
                    "repair_attempts": state.loop_counts.repair_attempts + 1,
                    "finding_attempts": counts,
                }
            ),
        }

    def recover_repair(self, state: GraphState, effect: dict) -> dict:
        candidate_ref = self._ref(state, "candidate")
        record = self.runner._load_artifact(
            candidate_ref.artifact_id, candidate_ref.version
        )
        if (
            candidate_ref.artifact_id != effect["artifact_id"]
            or candidate_ref.version != effect["artifact_version"]
            or record.run_id != state.run_id
            or record.content_hash != candidate_ref.content_hash
            or record.producer_role != "repair"
        ):
            raise GraphRouteError("Repair checkpoint 的 Candidate 不匹配")
        counts = dict(state.loop_counts.finding_attempts)
        finding_id = state.active_finding_id
        counts[finding_id] = counts.get(finding_id, 0) + 1
        return {
            "current_node": "repair",
            "last_outcome": "succeeded",
            "artifact_refs": state.artifact_refs,
            "loop_counts": state.loop_counts.model_copy(update={
                "repair_attempts": state.loop_counts.repair_attempts + 1,
                "finding_attempts": counts,
            }),
        }

    def _verification(self, state: GraphState, index: int) -> dict:
        candidate_ref = self._ref(state, "candidate")
        effect = self.runner._recovery_effect
        prior_decision = (
            effect["type"]
            if effect and effect["type"] in ("candidate.accepted", "candidate.rejected")
            else None
        )
        if prior_decision and (
            candidate_ref.artifact_id != effect["artifact_id"]
            or candidate_ref.version != effect["artifact_version"]
        ):
            raise GraphRouteError("Verification checkpoint 的 Candidate 不匹配")
        report = self._evaluate(state, candidate_ref)
        run = self.runner.get(state.run_id)
        summary = self._quality_summary(run.quality, report)
        result_start = len(summary.verification_results)
        summary.verification_results.extend(report.results)
        if state.active_finding_id and report.results:
            summary.verification_links.append(VerificationLink(
                finding_id=state.active_finding_id,
                candidate_ref=candidate_ref,
                result_start=result_start,
                result_count=len(report.results),
            ))
        verification_sources = [
            self._ref(state, "mission"),
            self._ref(state, "blueprint"),
            candidate_ref,
            self._ref(state, "quality"),
        ]
        passed = all(item.status == "pass" for item in report.results)
        if prior_decision and prior_decision != (
            "candidate.accepted" if passed else "candidate.rejected"
        ):
            self.runner._mark_waiting(
                state.run_id, index, "接管后验证结论与已提交决定不一致，需要人工处理",
                summary, "system", verification_sources,
            )
            return {"current_node": "verification", "last_outcome": "waiting_for_human"}
        if passed:
            if prior_decision != "candidate.accepted":
                self.runner._accept_repair_candidate(state.run_id, candidate_ref)
            summary.resolved_finding_ids.append(state.active_finding_id)
            self.runner._persist_system_artifact(
                state.run_id, "quality", summary, verification_sources
            )
            brief = run.blueprint.lessons[state.quality_cursor]
            refs = dict(state.artifact_refs)
            refs[f"lesson:{brief.lesson_id}"] = candidate_ref
            refs["quality"] = self.runner._source_refs(state.run_id, ("quality",))[0]
            cursor = state.quality_cursor + 1
            if cursor == len(run.blueprint.lessons):
                self.runner._mark_stage_succeeded(
                    state.run_id,
                    index,
                    f"{cursor} 章分层质量 Gate 已通过独立验证",
                )
            return {
                "current_node": "verification",
                "last_outcome": "succeeded",
                "exit_reason": (
                    "all_lessons_ready"
                    if cursor == len(run.blueprint.lessons)
                    else "candidate_accepted"
                ),
                "artifact_refs": refs,
                "quality_cursor": cursor,
                "active_finding_id": None,
            }
        if prior_decision != "candidate.rejected":
            self.runner._reject_repair_candidate(state.run_id, candidate_ref)
        finding = report.findings[0] if report.findings else None
        if finding is None or not self._has_repair_budget(state, state.active_finding_id):
            self.runner._mark_waiting(
                state.run_id,
                index,
                "Candidate 未通过独立验证，需人工处理",
                summary,
                "system",
                verification_sources,
            )
            return {"current_node": "verification", "last_outcome": "waiting_for_human"}
        self.runner._persist_system_artifact(
            state.run_id, "quality", summary, verification_sources
        )
        return {
            "current_node": "verification",
            "last_outcome": "succeeded",
            "exit_reason": "repair_needed",
            "artifact_refs": {
                **state.artifact_refs,
                "quality": self.runner._source_refs(state.run_id, ("quality",))[0],
            },
        }

    def recover_verification(self, state: GraphState, effect: dict) -> dict:
        run = self.runner.get(state.run_id)
        quality_ref = self._ref(state, "quality")
        candidate_ref = self._ref(state, "candidate")
        if run.quality is None or (
            effect["type"] == "artifact.created" and (
                quality_ref.artifact_id != effect["artifact_id"]
                or quality_ref.version != effect["artifact_version"]
            )
        ):
            raise GraphRouteError("Verification checkpoint 的 Quality 不匹配")
        if state.active_finding_id in run.quality.resolved_finding_ids:
            brief = run.blueprint.lessons[state.quality_cursor]
            refs = dict(state.artifact_refs)
            refs[f"lesson:{brief.lesson_id}"] = candidate_ref
            cursor = state.quality_cursor + 1
            if cursor == len(run.blueprint.lessons) and run.stages[5].status != "succeeded":
                self.runner._mark_stage_succeeded(
                    state.run_id, 5,
                    f"{cursor} 章分层质量 Gate 已通过独立验证",
                )
            return {
                "current_node": "verification",
                "last_outcome": "succeeded",
                "exit_reason": (
                    "all_lessons_ready"
                    if cursor == len(run.blueprint.lessons) else "candidate_accepted"
                ),
                "artifact_refs": refs,
                "quality_cursor": cursor,
                "active_finding_id": None,
            }
        return {
            "current_node": "verification",
            "last_outcome": "succeeded",
            "exit_reason": "repair_needed",
            "artifact_refs": state.artifact_refs,
        }

    @staticmethod
    def _ref(state: GraphState, key: str):
        try:
            return state.artifact_refs[key]
        except KeyError as error:
            raise ValueError(f"Graph State 缺少 {key} Artifact 引用") from error


def build_graph(
    runner: Any,
    *,
    release_decision: ReleaseDecision | None = None,
    request_key: str | None = None,
):
    nodes = WorkflowNodes(runner, release_decision, request_key)
    builder = StateGraph(GraphState)
    def instrument(name, action):
        def invoke(state: GraphState) -> dict:
            runner._node_started(name, state)
            effect = runner._recovery_effect
            if name == "quality" and effect and effect["type"] in (
                "artifact.created", "stage.succeeded"
            ):
                result = nodes.recover_quality(state, effect)
            elif name == "repair" and effect and effect["type"] == "candidate.created":
                result = nodes.recover_repair(state, effect)
            elif name == "verification" and effect and effect["type"] in (
                "artifact.created", "stage.succeeded"
            ):
                result = nodes.recover_verification(state, effect)
            elif name in ("intake", "mission", "blueprint", "batch_plan") and (
                runner.get(state.run_id).stages[runner.stage_index(name)].status
                == "succeeded"
                and not (
                    name == "mission" and runner.store
                    and runner.store.mission_review_required(state.run_id)
                    and not (
                        (review := runner.store.latest_mission_review(state.run_id))
                        and review["action"] == "approve"
                    )
                )
            ):
                refs = dict(state.artifact_refs)
                if name != "intake" and name not in refs:
                    refs[name] = runner._source_refs(state.run_id, (name,))[0]
                result = {
                    "current_node": name,
                    "artifact_refs": refs,
                    "last_outcome": "succeeded",
                }
            else:
                result = action(state)
            runner._node_finished(state, result)
            return result
        return invoke

    builder.add_node("intake", instrument("intake", nodes.intake))
    builder.add_node("mission", instrument("mission", nodes.mission))
    builder.add_node("blueprint", instrument("blueprint", nodes.blueprint))
    builder.add_node("batch_plan", instrument("batch_plan", nodes.batch_plan))
    builder.add_node("generation", instrument("generation", nodes.generation))
    builder.add_node("quality", instrument("quality", nodes.quality))
    builder.add_node("repair", instrument("repair", nodes.repair))
    builder.add_node("verification", instrument("verification", nodes.verification))
    builder.add_node("release", instrument("release", nodes.release))
    builder.add_node("route_error", instrument("route_error", nodes.route_error))

    builder.add_conditional_edges(
        START,
        lambda state: state.current_node
        if runner._execution_resume and state.current_node != "release"
        else route_start(state),
    )
    builder.add_conditional_edges("intake", route_after_intake)
    builder.add_conditional_edges("mission", route_after_mission)
    builder.add_conditional_edges("blueprint", route_after_blueprint)
    builder.add_conditional_edges("batch_plan", route_after_batch_plan)
    builder.add_conditional_edges("generation", route_after_generation)
    builder.add_conditional_edges("quality", route_after_quality)
    builder.add_conditional_edges("repair", route_after_repair)
    builder.add_conditional_edges("verification", route_after_verification)
    builder.add_conditional_edges("release", route_after_release)
    builder.add_edge("route_error", END)
    return builder.compile()
