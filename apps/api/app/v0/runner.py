from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from threading import Lock
from typing import Literal
from uuid import uuid4

from app.catalog import CourseSummary, write_course
from app.v0 import publishing
from app.v0.agents import AGENT_DEFINITIONS, AgentExecutor
from app.v0.artifact_tools import ArtifactTools
from app.v0.execution import StopRequested
from app.v0.node_inputs import build_node_input_hash
from app.v0.provider import Provider
from app.v0.schemas import (
    STAGES,
    AgentRole,
    ArtifactRecord,
    ArtifactRef,
    ArtifactSummary,
    CourseInput,
    ProducerRole,
    QualitySummary,
    ReleaseDecision,
    GraphState,
    V0Run,
)
from app.v0.storage import FactStore, command_hash

V0_QUALITY_LIMITATIONS = (
    "未核验事实来源",
    "未执行完整课程量规",
    "未执行完整 Humanizer 评分",
)


@dataclass(frozen=True)
class NodeStartDecision:
    action: Literal["execute", "reuse", "blocked"]
    reused_state: GraphState | None = None
    reason: str | None = None


class V0Runner:
    def __init__(
        self,
        provider: Provider,
        store: FactStore | None = None,
        *,
        published_root=None,
        catalog_path=None,
        source_runtime=None,
    ):
        from app.catalog import CATALOG_PATH, PUBLISHED_ROOT

        self.provider = provider
        self.store = store
        self.published_root = published_root or PUBLISHED_ROOT
        self.catalog_path = catalog_path or CATALOG_PATH
        self.source_runtime = source_runtime
        self._runs: dict[str, V0Run] = {}
        self._memory_artifacts: dict[tuple[str, int], ArtifactRecord] = {}
        self._lock = Lock()
        self._execution = None
        self._execution_owner = None
        self._execution_epoch = None
        self._execution_command_id = None
        self._execution_attempt = None
        self._execution_state = None
        self._execution_resume = False
        self._recovery_effect = None
        self._retry_override_node: str | None = None
        self._failure_class: str | None = None
        if store is not None:
            store.migrate()
        self.artifact_tools = ArtifactTools(AGENT_DEFINITIONS, self._load_artifact)
        self.executor = AgentExecutor(provider, self.artifact_tools)

    def create(self, course_input: CourseInput, request_key: str | None = None) -> V0Run:
        return self.create_once(course_input, request_key)[0]

    def create_once(
        self, course_input: CourseInput, request_key: str | None = None,
        *, enqueue_start: bool = False,
    ) -> tuple[V0Run, bool]:
        if self.store is not None:
            run, created = self.store.create_run(
                course_input, request_key or uuid4().hex,
                enqueue_start=enqueue_start,
            )
            with self._lock:
                self._runs[run.id] = run
            return run.model_copy(deep=True), created
        run = V0Run(id=uuid4().hex, course_input=course_input)
        with self._lock:
            self._runs[run.id] = run
        return run.model_copy(deep=True), True

    def get(self, run_id: str) -> V0Run:
        if self.store is not None:
            return self.store.get_run(run_id)
        with self._lock:
            return self._runs[run_id].model_copy(deep=True)

    def _current(self, run_id: str) -> V0Run:
        return (
            self.store.get_run(run_id)
            if self.store
            else self._runs[run_id].model_copy(deep=True)
        )

    def _commit(
        self,
        run: V0Run,
        event_type: str,
        stage: str | None = None,
        artifact=None,
        request_key: str | None = None,
        request_hash: str | None = None,
        producer_role: ProducerRole | None = None,
        source_refs: list[ArtifactRef] | None = None,
        artifact_kind: str | None = None,
        accepted_ref: ArtifactRef | None = None,
    ) -> None:
        references = list(source_refs or [])
        if self.store is not None:
            run = self.store.record(
                run,
                event_type,
                stage,
                artifact,
                request_key,
                request_hash,
                producer_role=producer_role,
                source_refs=references,
                artifact_kind=artifact_kind,
                accepted_ref=accepted_ref,
                lease_owner=self._execution_owner,
                lease_epoch=self._execution_epoch,
                node_execution_id=self._execution_attempt,
                checkpoint_state=self._execution_state,
            )
            if self._execution_state is not None and artifact is not None:
                kind = artifact_kind or ("lesson" if stage == "generation" else stage)
                summary = next(item for item in reversed(run.artifacts) if item.kind == kind)
                key = "candidate" if event_type == "candidate.created" else (
                    f"lesson:{artifact.lesson_id}"
                    if kind == "lesson" and getattr(artifact, "lesson_id", None)
                    else kind
                )
                refs = dict(self._execution_state.artifact_refs)
                refs[key] = ArtifactRef(
                    run_id=run.id, artifact_id=summary.artifact_id,
                    version=summary.version, kind=kind,
                    content_hash=summary.content_hash,
                )
                self._execution_state = self._execution_state.model_copy(
                    update={"artifact_refs": refs}
                )
        elif artifact is not None:
            kind = artifact_kind or ("lesson" if stage == "generation" else stage)
            existing = [item for item in run.artifacts if item.kind == kind]
            artifact_id = existing[-1].artifact_id if existing else uuid4().hex
            version = existing[-1].version + 1 if existing else 1
            content = artifact.model_dump()
            content_hash = sha256(
                json.dumps(
                    content,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            summary = ArtifactSummary(
                artifact_id=artifact_id,
                version=version,
                kind=kind,
                content_hash=content_hash,
                producer_role=producer_role,
                source_refs=references,
            )
            run.artifacts.append(summary)
            self._memory_artifacts[(artifact_id, version)] = ArtifactRecord(
                artifact_id=artifact_id,
                version=version,
                run_id=run.id,
                kind=kind,
                content=content,
                content_hash=content_hash,
                producer_role=producer_role,
                source_refs=references,
            )
        self._runs[run.id] = run

    def _persist_repair_candidate(
        self, run_id: str, lesson, source_refs: list[ArtifactRef]
    ) -> ArtifactRef:
        with self._lock:
            run = self._current(run_id)
            self._commit(
                run,
                "candidate.created",
                "quality",
                artifact=lesson,
                producer_role="repair",
                source_refs=source_refs,
                artifact_kind="lesson",
            )
            return self._source_refs(run_id, ("lesson",))[0]

    def _accept_repair_candidate(self, run_id: str, reference: ArtifactRef) -> None:
        with self._lock:
            record = self._load_artifact(reference.artifact_id, reference.version)
            if (
                record.run_id != run_id
                or record.kind != "lesson"
                or record.content_hash != reference.content_hash
                or record.producer_role != "repair"
            ):
                raise ValueError("Candidate 引用无效")
            from app.v0.schemas import LessonDraft

            run = self._current(run_id)
            run.lesson = LessonDraft.model_validate(record.content)
            self._commit(
                run,
                "candidate.accepted",
                "quality",
                accepted_ref=reference,
            )

    def _reject_repair_candidate(self, run_id: str, reference: ArtifactRef) -> None:
        with self._lock:
            record = self._load_artifact(reference.artifact_id, reference.version)
            if record.run_id != run_id or record.content_hash != reference.content_hash:
                raise ValueError("Candidate 引用无效")
            self._commit(
                self._current(run_id),
                "candidate.rejected",
                "quality",
                accepted_ref=reference,
            )

    def _record_artifact_event(
        self, run_id: str, event_type: str, stage: str, reference: ArtifactRef
    ) -> None:
        if self.store is None or self.store.has_artifact_event(
            run_id, event_type, reference
        ):
            return
        with self._lock:
            self._commit(
                self._current(run_id),
                event_type,
                stage,
                accepted_ref=reference,
            )

    def _has_artifact_event(
        self, run_id: str, event_type: str, reference: ArtifactRef
    ) -> bool:
        return bool(
            self.store
            and self.store.has_artifact_event(run_id, event_type, reference)
        )

    def _load_artifact(self, artifact_id: str, version: int) -> ArtifactRecord:
        if self.store is not None:
            return self.store.get_artifact(artifact_id, version)
        return self._memory_artifacts[(artifact_id, version)].model_copy(deep=True)

    def _source_refs(self, run_id: str, kinds: tuple[str, ...]) -> list[ArtifactRef]:
        run = self._current(run_id)
        refs = []
        for kind in kinds:
            summary = next(item for item in reversed(run.artifacts) if item.kind == kind)
            refs.append(
                ArtifactRef(
                    run_id=run_id,
                    artifact_id=summary.artifact_id,
                    version=summary.version,
                    kind=summary.kind,
                    content_hash=summary.content_hash,
                )
            )
        return refs

    def execute(
        self, run_id: str, *, state: GraphState | None = None,
        execution=None, owner: str | None = None, epoch: int | None = None,
        recovery_effect: dict | None = None,
        command_id: str | None = None,
        retry_override_node: str | None = None,
    ) -> None:
        from app.v0.graph import build_graph

        self._execution = execution
        self._execution_owner = owner
        self._execution_epoch = epoch
        self._execution_command_id = command_id
        self._execution_resume = state is not None
        self._recovery_effect = recovery_effect
        self._retry_override_node = retry_override_node
        try:
            build_graph(self).invoke(
                state or GraphState(run_id=run_id),
                config={"recursion_limit": 100},
            )
        finally:
            self._execution = None
            self._execution_owner = None
            self._execution_epoch = None
            self._execution_command_id = None
            self._execution_attempt = None
            self._execution_state = None
            self._execution_resume = False
            self._recovery_effect = None
            self._retry_override_node = None
            self._failure_class = None

    def _node_started(self, node: str, state: GraphState) -> NodeStartDecision:
        self._failure_class = None
        if self._execution is None:
            return NodeStartDecision(action="execute")
        checkpoint = state.model_copy(
            update={"current_node": node, "last_outcome": "pending", "exit_reason": None}
        )
        if self._recovery_effect and self._recovery_effect["stage"] != (
            "quality" if node in ("repair", "verification") else node
        ):
            self._recovery_effect = None
        run = self.get(state.run_id)
        if run.context_contract_version != 1:
            self._execution_attempt = self._execution.start_node(
                state.run_id, node, checkpoint,
                self._execution_owner, self._execution_epoch,
                self._recovery_effect["id"] if self._recovery_effect else None,
                self._execution_command_id,
            )
            self._bind_node_execution(self._execution_attempt)
            self._execution_state = checkpoint
            return NodeStartDecision(action="execute")
        input_hash = None
        if run.context_contract_version == 1:
            review = (
                self.store.latest_mission_review(state.run_id)
                if self.store is not None else None
            )
            mission_review = (
                {
                    key: review[key]
                    for key in (
                        "action", "feedback", "artifact_id",
                        "artifact_version", "content_hash",
                    )
                }
                if review is not None else None
            )
            source_summary = (
                self.source_runtime.facts.summary_pack(state.run_id)
                if self.source_runtime is not None
                and run.source_evidence_version == 1
                else None
            )
            human_input = (
                self._execution.human_input_state(state.run_id)
                if hasattr(self._execution, "human_input_state") else None
            )
            input_hash = build_node_input_hash(
                node=node, run=run, state=checkpoint,
                mission_review=mission_review,
                source_summary=source_summary,
                human_input=human_input,
                provider=self.provider,
            )
        claim = self._execution.claim_node_execution(
            state.run_id, node, checkpoint,
            self._execution_owner, self._execution_epoch,
            input_hash=input_hash,
            reuse_enabled=(
                run.context_contract_version == 1
                and self._recovery_effect is None
            ),
            retry_override=self._retry_override_node == node,
            recovery_event_id=(
                self._recovery_effect["id"] if self._recovery_effect else None
            ),
            command_id=self._execution_command_id,
        )
        if claim.outcome == "reused":
            return NodeStartDecision(
                action="reuse", reused_state=claim.after_state,
            )
        if claim.outcome == "busy":
            return NodeStartDecision(action="blocked", reason="node_busy")
        if claim.outcome == "blocked":
            if claim.reason == "stop_requested":
                raise StopRequested("STOP 已受理，禁止开始下一节点")
            return NodeStartDecision(
                action="blocked", reason=claim.reason or "node_blocked",
            )
        self._execution_attempt = claim.execution_id
        self._bind_node_execution(self._execution_attempt)
        self._execution_state = checkpoint
        return NodeStartDecision(action="execute")

    def _bind_node_execution(self, execution_id: str | None) -> None:
        if hasattr(self.provider, "node_execution_id"):
            self.provider.node_execution_id = execution_id
        if self.source_runtime is not None:
            self.source_runtime.bind(
                self._execution_owner, self._execution_epoch,
                self._execution_command_id, execution_id,
            )

    def _node_finished(self, state: GraphState, result: dict) -> None:
        if self._execution is None:
            return
        updated = self._execution_state.model_copy(update=result)
        failed = result.get("last_outcome") in ("failed", "unknown")
        failure_class = self._failure_class
        if failed and failure_class is None:
            failure_class = "business"
        self._execution.finish_node(
            self._execution_attempt, updated, self._execution_owner,
            self._execution_epoch, failed=failed,
            error=result.get("exit_reason") if failed else None,
            failure_class=failure_class,
        )
        self._execution_attempt = None
        self._bind_node_execution(None)
        self._execution_state = None
        self._failure_class = None
        self._recovery_effect = None

    @staticmethod
    def stage_index(stage: str) -> int:
        return STAGES.index(stage)

    def _write_role_success(
        self,
        role: AgentRole,
        run_id: str,
        index: int,
        stage: str,
        result,
        summary: str,
        refs: list[ArtifactRef],
    ) -> None:
        self.artifact_tools.write_candidate_artifact(
            role,
            run_id,
            AGENT_DEFINITIONS[role].output_kind,
            result,
            refs,
            lambda candidate: self._mark_succeeded(
                run_id,
                index,
                stage,
                candidate.content,
                summary,
                candidate.producer_role,
                candidate.source_refs,
            ),
        )

    def decide(
        self, run_id: str, decision: ReleaseDecision, request_key: str | None = None
    ) -> V0Run:
        if self.store is not None and request_key:
            replay = self.store.release_replay(run_id, request_key, decision)
            if replay is not None:
                return replay
        from app.v0.graph import build_graph

        build_graph(self, release_decision=decision, request_key=request_key).invoke(
            GraphState(
                run_id=run_id,
                current_node="release",
                approval_status=decision.action,
            )
        )
        return self.get(run_id)

    def publish(self, run_id: str, request_key: str | None = None) -> V0Run:
        """Materialize a prepared Run into an explicit published course."""
        if self.store is None:
            raise ValueError("发布需要持久化事实库")
        if request_key:
            replay = self.store.publication_replay(run_id, request_key)
            if replay is not None:
                return replay
        run = self.store.get_run(run_id)
        if run.status != "ready_for_release":
            raise ValueError("只有已准备发布的 Run 才能发布")
        content = self.store.get_run_content(run_id)
        slug = self._unique_slug(publishing.slugify(run.course_input.topic))
        entry = publishing.materialize(run, content, slug, self.published_root)
        write_course(CourseSummary.model_validate(entry), self.catalog_path)
        return self.store.record_publication(
            run,
            slug=slug,
            href=entry["href"],
            entry=entry,
            request_key=request_key or uuid4().hex,
            request_hash=command_hash("PUBLISH", {}),
        )

    def _unique_slug(self, base: str) -> str:
        slug, suffix = base, 1
        while self.store.publication_slug_exists(slug) or (
            self.published_root / slug
        ).exists():
            suffix += 1
            slug = f"{base}-{suffix}"
        return slug

    def _record_release_decision(
        self,
        run_id: str,
        decision: ReleaseDecision,
        request_key: str | None,
    ) -> None:
        with self._lock:
            run = self._current(run_id)
            if (
                run.status != "waiting_for_human"
                or run.stages[-1].status != "waiting_for_human"
                or run.quality is None
                or run.quality.status != "ready"
            ):
                raise ValueError("release 尚未等待人工决定或已经处理")
            run.release_decision = decision
            run.stages[-1].output_summary = (
                "人工选择准备发布；V0 未执行发布"
                if decision.action == "prepare"
                else "人工选择停止"
            )
            if decision.action == "prepare":
                run.status = "ready_for_release"
                run.stages[-1].status = "succeeded"
            else:
                run.status = "stopped"
                run.stages[-1].status = "stopped"
            self._commit(
                run,
                "release.decided",
                "release",
                request_key=request_key,
                request_hash=self.store.decision_hash(decision)
                if self.store is not None and request_key
                else None,
            )

    @staticmethod
    def _input_summary(stage: str, run: V0Run) -> str:
        if stage in ("intake", "mission"):
            return f"主题：{run.course_input.topic}；受众：{run.course_input.audience}"
        if stage == "blueprint" and run.mission:
            return f"学习目标：{run.mission.learning_goal}"
        if stage in ("batch_plan", "generation") and run.blueprint:
            return f"章节：{run.blueprint.lessons[0].title}"
        if run.lesson:
            return f"候选正文：{run.lesson.title}，{len(run.lesson.markdown)} 字符"
        return "等待前置 Artifact"

    def _mark_running(self, run_id: str, index: int, summary: str) -> None:
        with self._lock:
            run = self._current(run_id)
            record = run.stages[index]
            record.status = "running"
            record.input_summary = summary[:200]
            self._commit(run, "stage.started", STAGES[index])

    def _mark_succeeded(
        self,
        run_id,
        index,
        stage,
        result,
        summary,
        producer_role=None,
        source_refs=None,
    ) -> None:
        with self._lock:
            run = self._current(run_id)
            if stage != "intake":
                attribute = "lesson" if stage == "generation" else stage
                setattr(run, attribute, result)
            record = run.stages[index]
            record.status = "succeeded"
            record.output_summary = summary[:200]
            self._commit(
                run,
                "stage.succeeded",
                stage,
                artifact=result if stage != "intake" else None,
                producer_role=producer_role,
                source_refs=source_refs,
            )

    def _persist_candidate(self, run_id: str, stage: str, candidate) -> None:
        with self._lock:
            run = self._current(run_id)
            attribute = "lesson" if stage == "generation" else stage
            setattr(run, attribute, candidate.content)
            self._commit(
                run,
                "artifact.created",
                stage,
                artifact=candidate.content,
                producer_role=candidate.producer_role,
                source_refs=candidate.source_refs,
            )

    def _persist_system_artifact(
        self,
        run_id: str,
        stage: str,
        artifact,
        source_refs: list[ArtifactRef],
    ) -> None:
        with self._lock:
            run = self._current(run_id)
            setattr(run, stage, artifact)
            self._commit(
                run,
                "artifact.created",
                stage,
                artifact=artifact,
                producer_role="system",
                source_refs=source_refs,
            )

    def _mark_stage_succeeded(self, run_id: str, index: int, summary: str) -> None:
        with self._lock:
            run = self._current(run_id)
            record = run.stages[index]
            record.status = "succeeded"
            record.output_summary = summary[:200]
            self._commit(run, "stage.succeeded", STAGES[index])

    def _mark_failed(
        self,
        run_id: str,
        index: int,
        reason: str,
        quality: QualitySummary | None = None,
        producer_role: ProducerRole | None = None,
        source_refs: list[ArtifactRef] | None = None,
    ) -> None:
        with self._lock:
            run = self._current(run_id)
            if quality is not None:
                run.quality = quality
            run.status = "failed"
            record = run.stages[index]
            record.status = "failed"
            record.failure_reason = reason[:200]
            self._commit(
                run,
                "stage.failed",
                STAGES[index],
                artifact=quality,
                producer_role=producer_role,
                source_refs=source_refs,
            )

    def _mark_waiting(
        self,
        run_id: str,
        index: int,
        reason: str,
        quality: QualitySummary | None = None,
        producer_role: ProducerRole | None = None,
        source_refs: list[ArtifactRef] | None = None,
    ) -> None:
        with self._lock:
            run = self._current(run_id)
            if quality is not None:
                run.quality = quality
            run.status = "waiting_for_human"
            record = run.stages[index]
            record.status = "waiting_for_human"
            record.failure_reason = reason[:200]
            self._commit(
                run,
                "stage.waiting",
                STAGES[index],
                artifact=quality,
                producer_role=producer_role,
                source_refs=source_refs,
            )
