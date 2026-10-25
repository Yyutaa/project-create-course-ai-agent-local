"""SQLite command inbox and fenced local Worker execution facts."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from app.v0.storage import FactStore, command_hash
from app.v0.schemas import (
    BLUEPRINT_CHAPTER_DEVIATION_REASON,
    ArtifactRef,
    GraphState,
    LessonDraft,
)
from app.v0.sensitive import (
    HIDDEN_PROVIDER_ERROR,
    is_reviewer_schema_error,
    safe_recorded_error,
    safe_waiting_reason,
)
from app.v0.budget import BudgetStore, BudgetSummary, TokenLimitReached
from app.v0.source_facts import SourceFacts
from app.v0.source_tools import is_direct_document_host
from app.v0.source_tools import canonical_public_url

CommandKind = Literal[
    "START", "STOP", "RESUME", "REVISE", "MISSION_REVIEW", "QUALITY_REVIEW",
    "SOURCE_REVIEW",
]
CommandStatus = Literal["ACCEPTED", "CLAIMED", "APPLIED", "FAILED", "REJECTED"]
MAX_NODE_INPUT_FAILURES = 3


def _utc() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    run_id: str
    kind: CommandKind
    payload: dict
    status: CommandStatus
    idempotency_key: str
    claimed_by: str | None = None
    error: str | None = None


class CommandView(BaseModel):
    id: str
    run_id: str
    kind: CommandKind
    status: CommandStatus
    error: str | None = None


class NodeClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["reused", "busy", "claimed", "blocked"]
    execution_id: str | None = None
    attempt: int | None = None
    checkpoint_id: str | None = None
    lease_epoch: int | None = None
    source_execution_id: str | None = None
    source_checkpoint_id: str | None = None
    after_state: GraphState | None = None
    reason: str | None = None


class CheckpointView(BaseModel):
    id: str
    position: str
    node_execution_id: str | None = None


class MissionReviewView(BaseModel):
    status: Literal["pending", "approved"]
    mission_ref: ArtifactRef
    checkpoint_id: str | None = None


class QualityReviewView(BaseModel):
    status: Literal["pending", "retry_only"]
    quality_ref: ArtifactRef | None = None
    lesson_ref: ArtifactRef
    checkpoint_id: str


class SourceCandidateView(BaseModel):
    id: str
    url: str
    title: str
    status: str
    metadata_hash: str


class SourceReviewView(BaseModel):
    checkpoint_id: str
    candidates: list[SourceCandidateView]
    hidden_candidate_count: int
    retry_remaining: int


class ExecutionReadModel(BaseModel):
    run_id: str
    commands: list[CommandView]
    current_node: str | None
    node_status: str | None
    checkpoint: CheckpointView | None
    stop_requested: bool
    human_input_revision: int
    waiting_reason: str | None
    budget: BudgetSummary
    mission_review: MissionReviewView | None = None
    quality_review: QualityReviewView | None = None
    source_review: SourceReviewView | None = None


class ExecutionStore:
    def __init__(self, path: Path):
        self.facts = FactStore(path)
        self.facts.migrate()

    @staticmethod
    def _command(row) -> Command:
        return Command(
            id=row["id"], run_id=row["run_id"], kind=row["kind"],
            payload=json.loads(row["payload_json"]), status=row["status"],
            idempotency_key=row["idempotency_key"],
            claimed_by=row["claimed_by"], error=row["error"],
        )

    def accept(
        self, run_id: str, kind: CommandKind, payload: dict, key: str
    ) -> Command:
        if not key:
            raise ValueError("Idempotency-Key 不能为空")
        if kind not in (
            "START", "STOP", "RESUME", "REVISE", "MISSION_REVIEW",
            "QUALITY_REVIEW", "SOURCE_REVIEW",
        ):
            raise ValueError("未知 Command 类型")
        encoded = _json(payload)
        digest = command_hash(kind, payload)
        now = _utc().isoformat()
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM commands WHERE run_id=? AND idempotency_key=?",
                (run_id, key),
            ).fetchone()
            if existing:
                if existing["payload_hash"] != digest:
                    raise ValueError("Idempotency-Key 已用于不同 Command")
                return self._command(existing)
            run = connection.execute(
                "SELECT status FROM runs WHERE id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise KeyError(run_id)
            command_id = uuid4().hex
            connection.execute(
                "INSERT INTO commands(id, run_id, kind, payload_json, payload_hash, "
                "idempotency_key, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'ACCEPTED', ?, ?)",
                (command_id, run_id, kind, encoded, digest, key, now, now),
            )
            connection.execute(
                "INSERT OR IGNORE INTO run_controls(run_id) VALUES (?)", (run_id,)
            )
            if kind == "START" and connection.execute(
                "SELECT 1 FROM checkpoints WHERE run_id=? LIMIT 1", (run_id,)
            ).fetchone() is None:
                self._checkpoint(
                    connection, run_id, None, "before_node", GraphState(run_id=run_id)
                )
            if kind == "STOP" and run["status"] in ("running", "waiting_for_human"):
                connection.execute(
                    "UPDATE run_controls SET stop_requested=1, revision=revision+1 "
                    "WHERE run_id=?", (run_id,)
                )
            row = connection.execute(
                "SELECT * FROM commands WHERE id=?", (command_id,)
            ).fetchone()
            return self._command(row)

    def list_commands(self, run_id: str) -> list[Command]:
        with self.facts.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM commands WHERE run_id=? ORDER BY created_at, rowid",
                (run_id,),
            ).fetchall()
            return [self._command(row) for row in rows]

    def claim(self, owner: str, ttl_seconds: int = 60) -> Command | None:
        now = _utc()
        until = (now + timedelta(seconds=ttl_seconds)).isoformat()
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT c.* FROM commands AS c LEFT JOIN run_leases AS l "
                "ON l.run_id=c.run_id WHERE "
                "(c.status='ACCEPTED' OR "
                "(c.status='CLAIMED' AND c.claimed_until<?)) AND "
                "(l.run_id IS NULL OR l.expires_at<=? OR l.owner=?) "
                "ORDER BY c.created_at, c.rowid LIMIT 1",
                (now.isoformat(), now.isoformat(), owner),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE commands SET status='CLAIMED', claimed_by=?, "
                "claimed_until=?, updated_at=? WHERE id=?",
                (owner, until, now.isoformat(), row["id"]),
            )
            return self._command(connection.execute(
                "SELECT * FROM commands WHERE id=?", (row["id"],)
            ).fetchone())

    def defer_claim(self, command_id: str, owner: str) -> None:
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE commands SET status='ACCEPTED', claimed_by=NULL, "
                "claimed_until=NULL, updated_at=? WHERE id=? AND "
                "status='CLAIMED' AND claimed_by=?",
                (_utc().isoformat(), command_id, owner),
            )

    def acquire(self, run_id: str, owner: str, ttl_seconds: int = 60) -> int | None:
        now = _utc()
        until = (now + timedelta(seconds=ttl_seconds)).isoformat()
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM run_leases WHERE run_id=?", (run_id,)
            ).fetchone()
            if row and row["expires_at"] > now.isoformat() and row["owner"] != owner:
                return None
            epoch = (row["epoch"] + 1) if row else 1
            connection.execute(
                "INSERT INTO run_leases VALUES (?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET owner=excluded.owner, "
                "epoch=excluded.epoch, expires_at=excluded.expires_at",
                (run_id, owner, epoch, until),
            )
            return epoch

    def is_owner(self, run_id: str, owner: str, epoch: int) -> bool:
        with self.facts.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM run_leases WHERE run_id=? AND owner=? AND epoch=? "
                "AND expires_at>?", (run_id, owner, epoch, _utc().isoformat()),
            ).fetchone()
            return row is not None

    @staticmethod
    def _require_lease(connection, run_id: str, owner: str, epoch: int) -> None:
        row = connection.execute(
            "SELECT 1 FROM run_leases WHERE run_id=? AND owner=? AND epoch=? "
            "AND expires_at>?", (run_id, owner, epoch, _utc().isoformat()),
        ).fetchone()
        if row is None:
            raise PermissionError("lease 已失效，禁止提交")

    @staticmethod
    def _retryable_reviewer_failure(connection, run, checkpoint, state: GraphState) -> bool:
        if not (
            run.status == "failed" and run.stages[5].status == "failed"
            and checkpoint is not None and checkpoint["position"] == "after_node"
            and state.current_node == "quality" and state.last_outcome == "failed"
            and run.blueprint is not None
            and state.quality_cursor < len(run.blueprint.lessons)
        ):
            return False
        reason = run.stages[5].failure_reason or ""
        if not (is_reviewer_schema_error(reason) or reason == HIDDEN_PROVIDER_ERROR):
            return False
        # Older runs stored only the generic safe error. A successful Reviewer
        # response in this failed node is the narrow recoverable legacy signal.
        call = connection.execute(
            "SELECT role, status FROM provider_calls WHERE run_id=? "
            "AND node_execution_id=? ORDER BY started_at DESC, rowid DESC LIMIT 1",
            (run.id, checkpoint["node_execution_id"]),
        ).fetchone()
        return bool(call and call["role"] == "reviewer" and call["status"] == "SUCCEEDED")

    def heartbeat(
        self, run_id: str, owner: str, epoch: int,
        *, command_id: str | None = None, ttl_seconds: int = 60,
    ) -> None:
        now = _utc()
        until = (now + timedelta(seconds=ttl_seconds)).isoformat()
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_lease(connection, run_id, owner, epoch)
            connection.execute(
                "UPDATE run_leases SET expires_at=? WHERE run_id=?", (until, run_id)
            )
            if command_id:
                connection.execute(
                    "UPDATE commands SET claimed_until=? WHERE id=? AND "
                    "status='CLAIMED' AND claimed_by=?",
                    (until, command_id, owner),
                )

    def finish_command(
        self, command_id: str, owner: str, epoch: int,
        status: Literal["APPLIED", "FAILED", "REJECTED"], error: str | None = None,
    ) -> None:
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT run_id, claimed_by, status FROM commands WHERE id=?",
                (command_id,),
            ).fetchone()
            if row is None or row["claimed_by"] != owner or row["status"] != "CLAIMED":
                raise PermissionError("Command 已被其他 Worker 接管")
            self._require_lease(connection, row["run_id"], owner, epoch)
            connection.execute(
                "UPDATE commands SET status=?, error=?, updated_at=? WHERE id=?",
                (status, error[:200] if error else None, _utc().isoformat(), command_id),
            )

    def apply_mission_review(
        self, command: Command, owner: str, epoch: int
    ) -> dict:
        if command.kind != "MISSION_REVIEW":
            raise ValueError("Command 不是 Mission 审批")
        action = command.payload.get("action")
        if action not in ("approve", "revise"):
            raise ValueError("Mission 审批动作无效")
        feedback = command.payload.get("feedback")
        if action == "revise" and (
            not isinstance(feedback, str) or not feedback.strip()
            or len(feedback) > 2000
        ):
            raise ValueError("Mission 修订意见必须为 1 至 2000 字符")
        if action == "approve" and feedback is not None:
            raise ValueError("Mission 确认不接受修订意见")
        try:
            reference = ArtifactRef.model_validate(command.payload["mission_ref"])
            expected = command.payload["expected_checkpoint_id"]
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Mission 审批引用不完整") from error
        if not isinstance(expected, str) or not expected:
            raise ValueError("Mission 审批 checkpoint 缺失")
        now = _utc().isoformat()
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_lease(connection, command.run_id, owner, epoch)
            claim = connection.execute(
                "SELECT status, claimed_by FROM commands WHERE id=?", (command.id,)
            ).fetchone()
            if claim is None or claim["status"] != "CLAIMED" or claim["claimed_by"] != owner:
                raise PermissionError("Command 已被其他 Worker 接管")
            replay = connection.execute(
                "SELECT * FROM mission_reviews WHERE command_id=?", (command.id,)
            ).fetchone()
            if replay:
                return dict(replay)
            run = self.facts._get_run(connection, command.run_id)
            policy = connection.execute(
                "SELECT mission_review_required FROM runs WHERE id=?", (command.run_id,)
            ).fetchone()
            if not policy or not policy[0] or run.status != "waiting_for_human" or (
                run.stages[1].status != "waiting_for_human"
            ):
                raise ValueError("Run 未等待 Mission 人工确认")
            checkpoint = connection.execute(
                "SELECT id, position FROM checkpoints WHERE run_id=? "
                "ORDER BY rowid DESC LIMIT 1", (command.run_id,),
            ).fetchone()
            if (
                checkpoint is None or checkpoint["id"] != expected
                or checkpoint["position"] != "after_node"
            ):
                raise ValueError("Mission 审批 checkpoint 已过期")
            artifact = connection.execute(
                "SELECT artifact_id, version, content_hash FROM artifacts "
                "WHERE run_id=? AND kind='mission' ORDER BY version DESC LIMIT 1",
                (command.run_id,),
            ).fetchone()
            if (
                reference.run_id != command.run_id or reference.kind != "mission"
                or artifact is None or artifact["artifact_id"] != reference.artifact_id
                or artifact["version"] != reference.version
                or artifact["content_hash"] != reference.content_hash
            ):
                raise ValueError("Mission 审批 Artifact 引用已过期")
            existing = connection.execute(
                "SELECT 1 FROM mission_reviews WHERE run_id=? AND artifact_id=? "
                "AND artifact_version=?",
                (command.run_id, reference.artifact_id, reference.version),
            ).fetchone()
            if existing:
                raise ValueError("当前 Mission 版本已有人工决定")
            decision_id = uuid4().hex
            connection.execute(
                "INSERT INTO mission_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (decision_id, command.run_id, command.id, reference.artifact_id,
                 reference.version, reference.content_hash, expected, action,
                 feedback.strip() if isinstance(feedback, str) else None, now),
            )
            event_type = (
                "mission.approved" if action == "approve" else "mission.revision_requested"
            )
            run.status = "running"
            run.stages[1].status = "succeeded" if action == "approve" else "pending"
            run.stages[1].failure_reason = None
            event_id = connection.execute(
                "INSERT INTO events(run_id, stage, type, status, artifact_id, "
                "artifact_version, created_at) VALUES (?, 'mission', ?, ?, ?, ?, ?)",
                (command.run_id, event_type, run.stages[1].status,
                 reference.artifact_id, reference.version, now),
            ).lastrowid
            run.revision = event_id
            connection.execute(
                "UPDATE runs SET status='running', updated_at=? WHERE id=?",
                (now, command.run_id),
            )
            connection.execute(
                "UPDATE snapshots SET revision=?, projection_json=?, updated_at=? "
                "WHERE run_id=?",
                (event_id, run.model_dump_json(), now, command.run_id),
            )
            return dict(connection.execute(
                "SELECT * FROM mission_reviews WHERE id=?", (decision_id,)
            ).fetchone())

    def apply_source_review(
        self, command: Command, owner: str, epoch: int,
    ) -> dict:
        if command.kind != "SOURCE_REVIEW":
            raise ValueError("Command 不是来源审批")
        payload = command.payload
        action = payload.get("action")
        reason = payload.get("reason")
        expected = payload.get("expected_checkpoint_id")
        if action not in ("approve", "reject", "propose_url", "retry_search"):
            raise ValueError("来源审批动作无效")
        if action == "approve" and (
            not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 2000
        ):
            raise ValueError("来源审批说明必须为 1 至 2000 字符")
        if reason is not None and (
            not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 2000
        ):
            raise ValueError("来源审批说明必须为 1 至 2000 字符")
        if action == "retry_search" and (
            reason is not None or payload.get("candidate_id")
            or payload.get("metadata_hash") or payload.get("url")
        ):
            raise ValueError("继续查找不接受候选或人工说明")
        if not isinstance(expected, str) or not expected:
            raise ValueError("来源审批 checkpoint 缺失")
        proposed_url = None
        if action == "propose_url":
            proposed_url = canonical_public_url(str(payload.get("url") or ""))
            if not is_direct_document_host(proposed_url):
                raise ValueError("共享托管地址不能作为官方文档站点")
            if payload.get("candidate_id") or payload.get("metadata_hash"):
                raise ValueError("提供 URL 时不能同时审批旧候选")
        elif action != "retry_search" and payload.get("url") is not None:
            raise ValueError("审批候选时不能提交新 URL")
        now = _utc().isoformat()
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_lease(connection, command.run_id, owner, epoch)
            claim = connection.execute(
                "SELECT status, claimed_by FROM commands WHERE id=?",
                (command.id,),
            ).fetchone()
            if claim is None or claim["status"] != "CLAIMED" or (
                claim["claimed_by"] != owner
            ):
                raise PermissionError("Command 已被其他 Worker 接管")
            replay = connection.execute(
                "SELECT id, action FROM source_decisions WHERE command_id=?",
                (command.id,),
            ).fetchone()
            if replay:
                return {
                    "id": replay["id"],
                    "resume": replay["action"] in ("approve", "retry_search"),
                    "replayed": True,
                }
            run = self.facts._get_run(connection, command.run_id)
            checkpoint = connection.execute(
                "SELECT id, position, state_json FROM checkpoints WHERE run_id=? "
                "ORDER BY rowid DESC LIMIT 1", (command.run_id,),
            ).fetchone()
            if (
                checkpoint is None or checkpoint["id"] != expected
                or checkpoint["position"] != "after_node"
            ):
                raise ValueError("来源审批 checkpoint 已过期")
            state = GraphState.model_validate_json(checkpoint["state_json"])
            if state.current_node not in ("blueprint", "generation"):
                raise ValueError("当前节点不支持来源审批")
            stage_index = 2 if state.current_node == "blueprint" else 4
            stage = run.stages[stage_index]
            if (
                run.source_evidence_version != 1
                or run.status != "waiting_for_human"
                or stage.status != "waiting_for_human"
                or stage.failure_reason not in (
                    "source_evidence_insufficient", "source_review_required",
                )
            ):
                raise ValueError("Run 未等待来源人工确认")
            if action == "retry_search":
                attempts = connection.execute(
                    "SELECT COUNT(*) FROM source_decisions "
                    "WHERE run_id=? AND action='retry_search'", (command.run_id,),
                ).fetchone()[0]
                if attempts >= 2:
                    raise ValueError("自动继续查找次数已用尽")
                candidate_id = None
                reason = "要求继续自动查找公开官方资料"
            elif proposed_url is not None:
                reason = reason or "人工补充公开官方资料候选地址"
                candidate_id = sha256(
                    f"{command.run_id}:{proposed_url}".encode("utf-8")
                ).hexdigest()[:32]
                metadata_hash = sha256(
                    _json({"proposed_url": proposed_url}).encode("utf-8")
                ).hexdigest()
                connection.execute(
                    "INSERT OR IGNORE INTO source_candidates "
                    "(id, run_id, url, title, status, metadata_hash, created_at) "
                    "VALUES (?, ?, ?, '人工提供的候选地址', 'needs_human', ?, ?)",
                    (candidate_id, command.run_id, proposed_url, metadata_hash, now),
                )
            else:
                if action == "reject":
                    reason = reason or "人工排除该来源候选"
                candidate_id = payload.get("candidate_id")
                metadata_hash = payload.get("metadata_hash")
                candidate = connection.execute(
                    "SELECT id, url, metadata_hash, status FROM source_candidates "
                    "WHERE id=? AND run_id=?", (candidate_id, command.run_id),
                ).fetchone()
                if (
                    candidate is None or candidate["metadata_hash"] != metadata_hash
                    or candidate["status"] not in ("candidate", "needs_human")
                ):
                    raise ValueError("来源候选引用已过期或不可审批")
                if action == "approve" and not is_direct_document_host(
                    candidate["url"]
                ):
                    raise ValueError("共享托管地址不能作为官方文档站点")
                prior = connection.execute(
                    "SELECT 1 FROM source_decisions WHERE run_id=? "
                    "AND candidate_id=? AND action IN ('approve','reject') LIMIT 1",
                    (command.run_id, candidate_id),
                ).fetchone()
                if prior:
                    raise ValueError("当前候选版本已有人工决定")
                connection.execute(
                    "UPDATE source_candidates SET status=? WHERE id=?",
                    ("human_approved" if action == "approve" else "rejected",
                     candidate_id),
                )
            decision_id = uuid4().hex
            connection.execute(
                "INSERT INTO source_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (decision_id, command.run_id, candidate_id, expected, action,
                 reason.strip(), command.id, now),
            )
            resumed = action in ("approve", "retry_search")
            if resumed:
                run.status = "running"
                stage.status = "pending"
                stage.failure_reason = None
                connection.execute(
                    "UPDATE runs SET status='running', updated_at=? WHERE id=?",
                    (now, command.run_id),
                )
            event_id = connection.execute(
                "INSERT INTO events(run_id, stage, type, status, request_key, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (command.run_id, state.current_node, f"source.{action}",
                 run.status, command.id, now),
            ).lastrowid
            run.revision = event_id
            connection.execute(
                "UPDATE snapshots SET revision=?, projection_json=?, updated_at=? "
                "WHERE run_id=?",
                (event_id, run.model_dump_json(), now, command.run_id),
            )
            return {"id": decision_id, "resume": resumed, "replayed": False}

    def apply_quality_review(
        self, command: Command, owner: str, epoch: int
    ) -> dict:
        if command.kind != "QUALITY_REVIEW":
            raise ValueError("Command 不是 Quality 审批")
        action = command.payload.get("action")
        reason = command.payload.get("reason")
        if action not in ("retry", "accept"):
            raise ValueError("Quality 审批动作无效")
        if action == "accept" and (
            not isinstance(reason, str) or not reason.strip() or len(reason) > 2000
        ):
            raise ValueError("Quality 风险接受说明必须为 1 至 2000 字符")
        if action == "retry" and reason is not None:
            raise ValueError("Quality 重新检查不接受说明")
        try:
            raw_quality_ref = command.payload.get("quality_ref")
            quality_ref = (
                ArtifactRef.model_validate(raw_quality_ref)
                if raw_quality_ref is not None else None
            )
            lesson_ref = ArtifactRef.model_validate(command.payload["lesson_ref"])
            expected = command.payload["expected_checkpoint_id"]
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Quality 审批引用不完整") from error
        if not isinstance(expected, str) or not expected:
            raise ValueError("Quality 审批 checkpoint 缺失")
        now = _utc().isoformat()
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_lease(connection, command.run_id, owner, epoch)
            claim = connection.execute(
                "SELECT status, claimed_by FROM commands WHERE id=?", (command.id,)
            ).fetchone()
            if claim is None or claim["status"] != "CLAIMED" or (
                claim["claimed_by"] != owner
            ):
                raise PermissionError("Command 已被其他 Worker 接管")
            replay = connection.execute(
                "SELECT id, type FROM events WHERE run_id=? AND request_key=?",
                (command.run_id, command.id),
            ).fetchone()
            if replay:
                return {**dict(replay), "replayed": True}
            run = self.facts._get_run(connection, command.run_id)
            checkpoint = connection.execute(
                "SELECT id, node_execution_id, position, state_json FROM checkpoints "
                "WHERE run_id=? "
                "ORDER BY rowid DESC LIMIT 1",
                (command.run_id,),
            ).fetchone()
            if (
                checkpoint is None or checkpoint["id"] != expected
                or checkpoint["position"] != "after_node"
            ):
                raise ValueError("Quality 审批 checkpoint 已过期")
            state = GraphState.model_validate_json(checkpoint["state_json"])
            technical_retry = self._retryable_reviewer_failure(
                connection, run, checkpoint, state
            )
            if technical_retry:
                if action != "retry" or quality_ref is not None:
                    raise ValueError("Reviewer 格式失败只能重新检查当前章节")
            elif run.status != "waiting_for_human" or (
                run.stages[5].status != "waiting_for_human"
            ):
                raise ValueError("Run 未等待 Quality 人工处理")
            if state.current_node not in ("quality", "verification"):
                raise ValueError("当前等待节点不支持 Quality 审批")
            if not technical_retry:
                quality = connection.execute(
                    "SELECT artifact_id, version, content_hash FROM artifacts "
                    "WHERE run_id=? AND kind='quality' AND artifact_id=? AND version=?",
                    (command.run_id, quality_ref.artifact_id, quality_ref.version),
                ).fetchone() if quality_ref is not None else None
                if (
                    quality_ref is None or quality_ref.run_id != command.run_id
                    or quality_ref.kind != "quality"
                    or state.artifact_refs.get("quality") != quality_ref
                    or quality is None or quality["content_hash"] != quality_ref.content_hash
                ):
                    raise ValueError("Quality 审批 Artifact 引用已过期")
            if lesson_ref.run_id != command.run_id or lesson_ref.kind != "lesson":
                raise ValueError("Quality 审批 Lesson 引用无效")
            if run.blueprint is None or state.quality_cursor >= len(run.blueprint.lessons):
                raise ValueError("Quality 审批缺少当前章节")
            lesson_id = run.blueprint.lessons[state.quality_cursor].lesson_id
            current_lesson = state.artifact_refs.get(
                "candidate" if state.current_node == "verification"
                else f"lesson:{lesson_id}"
            )
            if current_lesson != lesson_ref:
                raise ValueError("Quality 审批 Lesson 引用已过期")
            lesson = connection.execute(
                "SELECT 1 FROM artifacts WHERE run_id=? AND kind='lesson' "
                "AND artifact_id=? AND version=? AND content_hash=?",
                (command.run_id, lesson_ref.artifact_id,
                 lesson_ref.version, lesson_ref.content_hash),
            ).fetchone()
            if lesson is None:
                raise ValueError("Quality 审批 Lesson 引用无效")
            if action == "accept" and state.current_node == "verification":
                candidate = connection.execute(
                    "SELECT content_json, producer_role FROM artifacts WHERE run_id=? "
                    "AND artifact_id=? AND version=? AND kind='lesson' "
                    "AND content_hash=?",
                    (
                        command.run_id, lesson_ref.artifact_id,
                        lesson_ref.version, lesson_ref.content_hash,
                    ),
                ).fetchone()
                if candidate is None or candidate["producer_role"] != "repair":
                    raise ValueError("Quality 审批 Candidate 引用无效")
                run.lesson = LessonDraft.model_validate(json.loads(candidate["content_json"]))
                connection.execute(
                    "INSERT INTO events(run_id, stage, type, status, artifact_id, "
                    "artifact_version, request_key, request_hash, created_at) "
                    "VALUES (?, 'quality', 'candidate.human_accepted', 'running', "
                    "?, ?, ?, ?, ?)",
                    (
                        command.run_id, lesson_ref.artifact_id, lesson_ref.version,
                        f"{command.id}:candidate",
                        command_hash(command.kind, command.payload), now,
                    ),
                )
            event_type = (
                "quality.risk_accepted"
                if action == "accept" else "quality.retry_requested"
            )
            run.status = "running"
            run.stages[5].status = "pending"
            run.stages[5].failure_reason = None
            event_id = connection.execute(
                "INSERT INTO events(run_id, stage, type, status, input_summary, "
                "artifact_id, artifact_version, request_key, request_hash, created_at) "
                "VALUES (?, 'quality', ?, 'running', ?, ?, ?, ?, ?, ?)",
                (
                    command.run_id, event_type,
                    reason.strip() if isinstance(reason, str) else None,
                    quality_ref.artifact_id if quality_ref else None,
                    quality_ref.version if quality_ref else None, command.id,
                    command_hash(command.kind, command.payload), now,
                ),
            ).lastrowid
            run.revision = event_id
            if technical_retry:
                retry_state = state.model_copy(update={
                    "last_outcome": "waiting_for_human",
                    "exit_reason": "reviewer_output_retry_requested",
                })
                self._checkpoint(
                    connection, command.run_id, None, "after_node", retry_state, event_id,
                )
            if action == "accept" and state.current_node == "verification":
                refs = dict(state.artifact_refs)
                refs[f"lesson:{lesson_id}"] = lesson_ref
                decision_state = state.model_copy(update={
                    "artifact_refs": refs,
                    "active_finding_id": None,
                    "last_outcome": "succeeded",
                    "exit_reason": "candidate_human_accepted",
                })
                self._checkpoint(
                    connection, command.run_id, None,
                    "after_node", decision_state, event_id,
                )
            connection.execute(
                "UPDATE runs SET status='running', updated_at=? WHERE id=?",
                (now, command.run_id),
            )
            connection.execute(
                "UPDATE snapshots SET revision=?, projection_json=?, updated_at=? "
                "WHERE run_id=?",
                (event_id, run.model_dump_json(), now, command.run_id),
            )
            return {"id": event_id, "type": event_type, "replayed": False}

    @staticmethod
    def _checkpoint(connection, run_id: str, execution_id: str | None,
                    position: str, state: GraphState, event_id: int | None = None) -> str:
        checkpoint_id = uuid4().hex
        connection.execute(
            "INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?, ?, ?)",
            (checkpoint_id, run_id, execution_id, position,
             state.model_dump_json(), event_id, _utc().isoformat()),
        )
        return checkpoint_id

    def claim_node_execution(
        self,
        run_id: str,
        node: str,
        state: GraphState,
        owner: str,
        epoch: int,
        *,
        input_hash: str | None,
        reuse_enabled: bool,
        retry_override: bool = False,
        recovery_event_id: int | None = None,
        command_id: str | None = None,
    ) -> NodeClaim:
        now = _utc().isoformat()
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_lease(connection, run_id, owner, epoch)
            control = connection.execute(
                "SELECT stop_requested FROM run_controls WHERE run_id=?", (run_id,)
            ).fetchone()
            if control and control["stop_requested"]:
                return NodeClaim(outcome="blocked", reason="stop_requested")
            tokens_used, token_limit, _ = BudgetStore.token_state(connection, run_id)
            latest_attempt = connection.execute(
                "SELECT status FROM node_executions WHERE run_id=? AND node=? "
                "ORDER BY rowid DESC LIMIT 1",
                (run_id, node),
            ).fetchone()
            recovering_started = bool(
                latest_attempt
                and latest_attempt["status"] in ("STARTED", "WAITING")
            )
            if (
                token_limit is not None
                and tokens_used >= token_limit
                and not recovering_started
            ):
                raise TokenLimitReached(tokens_used, token_limit, node)
            if reuse_enabled and input_hash is not None:
                waiting = connection.execute(
                    "SELECT * FROM node_executions WHERE run_id=? AND node=? "
                    "AND status='WAITING' ORDER BY rowid DESC LIMIT 1",
                    (run_id, node),
                ).fetchone()
                if waiting is not None:
                    if waiting["input_hash"] != input_hash:
                        return NodeClaim(
                            outcome="blocked",
                            reason="interrupt_input_changed",
                        )
                    checkpoint_id = self._checkpoint(
                        connection, run_id, waiting["id"], "before_node", state,
                    )
                    connection.execute(
                        "UPDATE node_executions SET status='STARTED', "
                        "lease_epoch=?, before_checkpoint_id=?, "
                        "after_checkpoint_id=NULL, error=NULL, "
                        "failure_class=NULL, updated_at=? "
                        "WHERE id=? AND status='WAITING'",
                        (epoch, checkpoint_id, now, waiting["id"]),
                    )
                    return NodeClaim(
                        outcome="claimed",
                        execution_id=waiting["id"],
                        attempt=waiting["attempt"],
                        checkpoint_id=checkpoint_id,
                        lease_epoch=epoch,
                    )
            lookup = reuse_enabled and input_hash is not None
            if lookup:
                live = connection.execute(
                    "SELECT * FROM node_executions WHERE run_id=? AND node=? "
                    "AND input_hash=? AND status='STARTED' ORDER BY rowid DESC",
                    (run_id, node, input_hash),
                ).fetchall()
                for row in live:
                    if row["lease_epoch"] == epoch:
                        return NodeClaim(
                            outcome="busy", execution_id=row["id"],
                            lease_epoch=epoch,
                        )
                if not retry_override:
                    for row in connection.execute(
                        "SELECT * FROM node_executions WHERE run_id=? AND node=? "
                        "AND input_hash=? AND status='COMMITTED' "
                        "ORDER BY rowid DESC",
                        (run_id, node, input_hash),
                    ).fetchall():
                        if not row["after_checkpoint_id"]:
                            continue
                        checkpoint = connection.execute(
                            "SELECT state_json FROM checkpoints WHERE id=?",
                            (row["after_checkpoint_id"],),
                        ).fetchone()
                        if checkpoint is None:
                            continue
                        after = GraphState.model_validate_json(
                            checkpoint["state_json"]
                        )
                        if after.last_outcome != "succeeded":
                            continue
                        run_row = connection.execute(
                            "SELECT status FROM runs WHERE id=?", (run_id,)
                        ).fetchone()
                        connection.execute(
                            "INSERT INTO events(run_id, stage, type, status, "
                            "input_summary, output_summary, request_key, "
                            "request_hash, created_at) VALUES (?, ?, "
                            "'node.reused', ?, ?, ?, ?, ?, ?)",
                            (
                                run_id, node,
                                run_row["status"] if run_row else "unknown",
                                "复用相同输入的已完成节点结果",
                                str(row["id"]), row["id"], input_hash, now,
                            ),
                        )
                        return NodeClaim(
                            outcome="reused",
                            source_execution_id=row["id"],
                            source_checkpoint_id=row["after_checkpoint_id"],
                            after_state=after,
                        )
                for row in live:
                    if row["lease_epoch"] < epoch:
                        connection.execute(
                            "UPDATE node_executions SET status='FAILED', "
                            "error='lease_expired_takeover', "
                            "failure_class='transient', updated_at=? "
                            "WHERE id=? AND status='STARTED'",
                            (now, row["id"]),
                        )
                failures = connection.execute(
                    "SELECT COUNT(*) FROM node_executions WHERE run_id=? AND node=? "
                    "AND input_hash=? AND status='FAILED'",
                    (run_id, node, input_hash),
                ).fetchone()[0]
                if failures:
                    latest_failed = connection.execute(
                        "SELECT * FROM node_executions WHERE run_id=? AND node=? "
                        "AND input_hash=? AND status='FAILED' "
                        "ORDER BY rowid DESC LIMIT 1",
                        (run_id, node, input_hash),
                    ).fetchone()
                    if not retry_override:
                        if failures >= MAX_NODE_INPUT_FAILURES:
                            return NodeClaim(
                                outcome="blocked",
                                reason="max_attempts_reached",
                            )
                        if latest_failed["failure_class"] != "transient":
                            return NodeClaim(
                                outcome="blocked",
                                reason=(
                                    "retry_denied:"
                                    f"{latest_failed['failure_class'] or 'unknown'}"
                                ),
                            )
            attempt = connection.execute(
                "SELECT COUNT(*) FROM node_executions WHERE run_id=? AND node=?",
                (run_id, node),
            ).fetchone()[0] + 1
            execution_id = uuid4().hex
            checkpoint_id = self._checkpoint(
                connection, run_id, execution_id, "before_node", state,
                recovery_event_id,
            )
            connection.execute(
                "INSERT INTO node_executions("
                "id, run_id, node, attempt, lease_epoch, status, "
                "before_checkpoint_id, after_checkpoint_id, error, created_at, "
                "updated_at, command_id, input_hash, failure_class) "
                "VALUES (?, ?, ?, ?, ?, 'STARTED', ?, NULL, NULL, ?, ?, ?, ?, NULL)",
                (
                    execution_id, run_id, node, attempt, epoch, checkpoint_id,
                    now, now, command_id, input_hash,
                ),
            )
            return NodeClaim(
                outcome="claimed",
                execution_id=execution_id,
                attempt=attempt,
                checkpoint_id=checkpoint_id,
                lease_epoch=epoch,
            )

    def start_node(
        self, run_id: str, node: str, state: GraphState, owner: str, epoch: int,
        recovery_event_id: int | None = None,
        command_id: str | None = None,
    ) -> str:
        claim = self.claim_node_execution(
            run_id, node, state, owner, epoch, input_hash=None,
            reuse_enabled=False, recovery_event_id=recovery_event_id,
            command_id=command_id,
        )
        if claim.outcome == "blocked" and claim.reason == "stop_requested":
            raise StopRequested("STOP 已受理，禁止开始下一节点")
        if claim.outcome != "claimed" or claim.execution_id is None:
            raise ValueError(f"Node 领取失败：{claim.outcome}")
        return claim.execution_id

    def finish_node(
        self, execution_id: str, state: GraphState, owner: str, epoch: int,
        *, failed: bool = False, error: str | None = None,
        failure_class: str | None = None,
    ) -> None:
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT run_id, status FROM node_executions WHERE id=?", (execution_id,)
            ).fetchone()
            if row is None or row["status"] != "STARTED":
                raise ValueError("NodeExecution 状态不允许提交")
            self._require_lease(connection, row["run_id"], owner, epoch)
            checkpoint_id = self._checkpoint(
                connection, row["run_id"], execution_id, "after_node", state
            )
            connection.execute(
                "UPDATE node_executions SET status=?, after_checkpoint_id=?, "
                "error=?, lease_epoch=?, failure_class=?, updated_at=? WHERE id=?",
                (
                    "FAILED" if failed else "COMMITTED", checkpoint_id,
                    error[:200] if error else None, epoch,
                    (failure_class or "unknown") if failed else None,
                    _utc().isoformat(), execution_id,
                ),
            )

    def finish_node_waiting(
        self, execution_id: str, state: GraphState, owner: str, epoch: int,
        reason: str,
    ) -> None:
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT run_id, status FROM node_executions WHERE id=?",
                (execution_id,),
            ).fetchone()
            if row is None or row["status"] != "STARTED":
                raise ValueError("NodeExecution 状态不允许等待")
            self._require_lease(connection, row["run_id"], owner, epoch)
            checkpoint_id = self._checkpoint(
                connection, row["run_id"], execution_id, "after_node", state,
            )
            connection.execute(
                "UPDATE node_executions SET status='WAITING', "
                "after_checkpoint_id=?, error=?, lease_epoch=?, "
                "failure_class=NULL, updated_at=? WHERE id=?",
                (
                    checkpoint_id, reason[:200], epoch,
                    _utc().isoformat(), execution_id,
                ),
            )

    def stop_requested(self, run_id: str) -> bool:
        with self.facts.connect() as connection:
            row = connection.execute(
                "SELECT stop_requested FROM run_controls WHERE run_id=?", (run_id,)
            ).fetchone()
            return bool(row and row["stop_requested"])

    def human_input_state(self, run_id: str) -> dict | None:
        with self.facts.connect() as connection:
            row = connection.execute(
                "SELECT revision, human_input_json FROM run_controls WHERE run_id=?",
                (run_id,),
            ).fetchone()
        if row is None or not row["human_input_json"]:
            return None
        return {"revision": row["revision"], "text": row["human_input_json"]}

    def record_revision(self, command: Command, owner: str, epoch: int) -> None:
        text = command.payload.get("text")
        expected = command.payload.get("expected_checkpoint_id")
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise ValueError("REVISE 文本必须为 1 至 2000 字符")
        if not isinstance(expected, str) or not expected:
            raise ValueError("REVISE 必须指定 checkpoint")
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_lease(connection, command.run_id, owner, epoch)
            checkpoint = connection.execute(
                "SELECT id FROM checkpoints WHERE run_id=? ORDER BY rowid DESC LIMIT 1",
                (command.run_id,),
            ).fetchone()
            if checkpoint is None or checkpoint["id"] != expected:
                raise ValueError("REVISE checkpoint 已过期")
            status = connection.execute(
                "SELECT status FROM runs WHERE id=?", (command.run_id,)
            ).fetchone()["status"]
            if status not in ("stopped", "waiting_for_human"):
                raise ValueError("REVISE 仅允许在人工控制状态提交")
            new_limit = command.payload.get("provider_limit")
            if new_limit is not None:
                from app.v0.budget import BudgetStore, DEFAULT_CALL_LIMIT

                current = connection.execute(
                    "SELECT provider_limit FROM budget_limits WHERE run_id=?",
                    (command.run_id,),
                ).fetchone()
                current_limit = current[0] if current else DEFAULT_CALL_LIMIT
                used = connection.execute(
                    "SELECT COUNT(*) FROM provider_calls WHERE run_id=?",
                    (command.run_id,),
                ).fetchone()[0]
                gate = connection.execute(
                    "SELECT type, failure_reason FROM events WHERE run_id=? AND "
                    "type IN ('stage.waiting', 'release.waiting') ORDER BY id DESC LIMIT 1",
                    (command.run_id,),
                ).fetchone()
                exhausted = connection.execute(
                    "SELECT 1 FROM events WHERE run_id=? AND type='budget.exhausted' "
                    "AND id>(SELECT COALESCE(MAX(id),0) FROM events WHERE run_id=? "
                    "AND type='budget.approved') LIMIT 1",
                    (command.run_id, command.run_id),
                ).fetchone()
                if (
                    type(new_limit) is not int
                    or new_limit != current_limit + 20
                    or used < current_limit
                    or status != "waiting_for_human"
                    or gate is None
                    or gate["type"] != "stage.waiting"
                    or gate["failure_reason"] != "Provider 调用预算耗尽，需要人工处理"
                    or exhausted is None
                ):
                    raise ValueError("预算耗尽等待态才允许明确追加 20 次")
                connection.execute(
                    "INSERT INTO budget_limits(run_id, provider_limit, "
                    "approved_by_command) VALUES (?, ?, ?) ON CONFLICT(run_id) "
                    "DO UPDATE SET provider_limit=excluded.provider_limit, "
                    "approved_by_command=excluded.approved_by_command",
                    (command.run_id, new_limit, command.id),
                )
                BudgetStore._event(connection, command.run_id, "budget.approved")
            connection.execute(
                "UPDATE run_controls SET human_input_json=?, revision=revision+1 "
                "WHERE run_id=?",
                (_json({"text": text.strip(), "checkpoint_id": expected,
                        "command_id": command.id}), command.run_id),
            )

    def prepare_resume(
        self, run_id: str, owner: str, epoch: int, payload: dict | None = None,
    ) -> None:
        run = self.facts.get_run(run_id)
        payload = payload or {}
        with self.facts.connect() as connection:
            token_stopped = connection.execute(
                "SELECT 1 FROM events WHERE run_id=? "
                "AND type='budget.token_exhausted' LIMIT 1",
                (run_id,),
            ).fetchone()
        if token_stopped:
            raise ValueError("Token 阈值已终止 Run，不能 RESUME")
        checkpoint = self.last_checkpoint(run_id)
        if checkpoint is None:
            raise ValueError("RESUME 缺少合法 checkpoint")
        state = GraphState.model_validate_json(checkpoint["state_json"])
        if state.current_node == "release":
            raise ValueError("release 仍需人工决定，不能由 RESUME 替代")
        if run.planning_loop_version == 1 and state.current_node in (
            "mission", "blueprint"
        ):
            stage = run.stages[1 if state.current_node == "mission" else 2]
            if stage.failure_reason and stage.failure_reason.startswith(
                "provider_transient_exhausted_"
            ) and payload.get("expected_checkpoint_id") != checkpoint["id"]:
                raise ValueError("技术重试需匹配当前精确 checkpoint")
        if state.current_node in ("blueprint", "generation"):
            active = run.stages[2 if state.current_node == "blueprint" else 4]
            if active.status == "waiting_for_human" and active.failure_reason in (
                "source_evidence_insufficient", "source_review_required",
            ):
                raise ValueError("来源尚未获人工确认，不能由 RESUME 替代")
        if state.current_node == "mission" and self.facts.mission_review_required(run_id):
            mission_ref = state.artifact_refs.get("mission")
            if mission_ref is not None:
                review = self.facts.latest_mission_review(run_id)
                if not review or review["action"] != "approve" or (
                    review["artifact_id"] != mission_ref.artifact_id
                    or review["artifact_version"] != mission_ref.version
                    or review["content_hash"] != mission_ref.content_hash
                ):
                    raise ValueError("Mission 尚未获人工确认，不能由 RESUME 替代")
        if state.current_node == "batch_plan":
            blueprint_ref = state.artifact_refs.get("blueprint")
            batch_stage = run.stages[3]
            if (
                run.constraints_version == 1
                and blueprint_ref is not None
                and batch_stage.status == "waiting_for_human"
                and batch_stage.failure_reason == BLUEPRINT_CHAPTER_DEVIATION_REASON
                and not self.facts.has_artifact_event(
                    run_id,
                    "blueprint.chapter_deviation_accepted",
                    blueprint_ref,
                )
            ):
                if run.planning_loop_version == 1:
                    if payload.get("expected_checkpoint_id") != checkpoint["id"]:
                        raise ValueError("Blueprint 偏差接受需匹配当前 checkpoint")
                    try:
                        supplied = ArtifactRef.model_validate(payload.get("blueprint_ref"))
                    except Exception as error:
                        raise ValueError("Blueprint 偏差接受缺少精确引用") from error
                    if supplied != blueprint_ref:
                        raise ValueError("Blueprint 偏差接受的版本已过期")
                self.facts.record(
                    run,
                    "blueprint.chapter_deviation_accepted",
                    "batch_plan",
                    accepted_ref=blueprint_ref,
                    lease_owner=owner,
                    lease_epoch=epoch,
                )
        run.status = "running"
        active = next(
            (item for item in run.stages if item.status in ("stopped", "waiting_for_human")),
            None,
        )
        if active:
            active.status = "pending"
            active.failure_reason = None
        self.facts.record(
            run, "run.resumed", active.name if active else None,
            lease_owner=owner, lease_epoch=epoch, clear_stop=True,
        )

    def read_model(self, run_id: str) -> ExecutionReadModel:
        self.facts.get_run(run_id)
        commands = self.list_commands(run_id)
        checkpoint = self.last_checkpoint(run_id)
        node = self.current_node(run_id)
        with self.facts.connect() as connection:
            control = connection.execute(
                "SELECT stop_requested, revision, human_input_json "
                "FROM run_controls WHERE run_id=?", (run_id,),
            ).fetchone()
        run = self.facts.get_run(run_id)
        mission_review = None
        if self.facts.mission_review_required(run_id):
            missions = [
                item for item in self.facts.list_artifacts(run_id)
                if item.kind == "mission"
            ]
            if missions:
                latest = missions[-1]
                decision = self.facts.latest_mission_review(run_id)
                approved = bool(
                    decision and decision["action"] == "approve"
                    and decision["artifact_id"] == latest.artifact_id
                    and decision["artifact_version"] == latest.version
                    and decision["content_hash"] == latest.content_hash
                )
                if approved or run.stages[1].status == "waiting_for_human":
                    mission_review = MissionReviewView(
                        status="approved" if approved else "pending",
                        mission_ref=ArtifactRef(
                            run_id=run_id, artifact_id=latest.artifact_id,
                            version=latest.version, kind="mission",
                            content_hash=latest.content_hash,
                        ),
                        checkpoint_id=(checkpoint["id"] if checkpoint and not approved else None),
                    )
        source_review = None
        quality_review = None
        if checkpoint is not None and checkpoint["position"] == "after_node":
            state = GraphState.model_validate_json(checkpoint["state_json"])
            if state.current_node in ("blueprint", "generation"):
                stage = run.stages[2 if state.current_node == "blueprint" else 4]
                if (
                    run.source_evidence_version == 1
                    and run.status == "waiting_for_human"
                    and stage.status == "waiting_for_human"
                    and stage.failure_reason in (
                        "source_evidence_insufficient", "source_review_required",
                    )
                ):
                    all_candidates = SourceFacts(self.facts).list_candidates(run_id)
                    reviewable = [
                        item for item in all_candidates
                        if item["status"] == "needs_human"
                        and is_direct_document_host(item["url"])
                    ]
                    retries = SourceFacts(self.facts).retry_round(run_id)
                    source_review = SourceReviewView(
                        checkpoint_id=checkpoint["id"],
                        candidates=[
                            SourceCandidateView.model_validate(item)
                            for item in reviewable[:3]
                        ],
                        hidden_candidate_count=len(all_candidates) - min(
                            len(reviewable), 3,
                        ),
                        retry_remaining=max(0, 2 - retries),
                    )
            with self.facts.connect() as connection:
                technical_retry = self._retryable_reviewer_failure(
                    connection, run, checkpoint, state
                )
            manual_review = (
                run.status == "waiting_for_human"
                and run.stages[5].status == "waiting_for_human"
            )
            quality_ref = state.artifact_refs.get("quality")
            if (
                (technical_retry or manual_review)
                and state.current_node in ("quality", "verification")
                and (technical_retry or quality_ref is not None)
                and run.blueprint is not None
                and state.quality_cursor < len(run.blueprint.lessons)
            ):
                lesson_id = run.blueprint.lessons[state.quality_cursor].lesson_id
                lesson_ref = state.artifact_refs.get(
                    "candidate" if state.current_node == "verification"
                    else f"lesson:{lesson_id}"
                )
                if lesson_ref is not None:
                    quality_review = QualityReviewView(
                        status="retry_only" if technical_retry else "pending",
                        quality_ref=None if technical_retry else quality_ref,
                        lesson_ref=lesson_ref,
                        checkpoint_id=checkpoint["id"],
                    )
        return ExecutionReadModel.model_validate({
            "run_id": run_id,
            "commands": [CommandView.model_validate({
                **item.model_dump(),
                "error": safe_recorded_error(item.error) if item.error else None,
            }) for item in commands],
            "current_node": node["node"] if node else None,
            "node_status": node["status"] if node else None,
            "checkpoint": {
                "id": checkpoint["id"], "position": checkpoint["position"],
                "node_execution_id": checkpoint["node_execution_id"],
            } if checkpoint else None,
            "stop_requested": bool(control and control["stop_requested"]),
            "human_input_revision": (
                control["revision"] if control and control["human_input_json"] else 0
            ),
            "waiting_reason": next(
                (safe_waiting_reason(item.failure_reason or item.input_summary or "")
                 for item in run.stages
                 if item.status == "waiting_for_human"), None,
            ),
            "budget": BudgetStore(self.facts.path).summary(run_id),
            "mission_review": mission_review,
            "quality_review": quality_review,
            "source_review": source_review,
        })

    def last_checkpoint(self, run_id: str) -> dict | None:
        with self.facts.connect() as connection:
            row = connection.execute(
                "SELECT * FROM checkpoints WHERE run_id=? ORDER BY rowid DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            return dict(row) if row else None

    def event(self, run_id: str, event_id: int) -> dict | None:
        with self.facts.connect() as connection:
            row = connection.execute(
                "SELECT id, type, stage, artifact_id, artifact_version "
                "FROM events WHERE run_id=? AND id=?", (run_id, event_id),
            ).fetchone()
            return dict(row) if row else None

    def current_node(self, run_id: str) -> dict | None:
        with self.facts.connect() as connection:
            row = connection.execute(
                "SELECT * FROM node_executions WHERE run_id=? "
                "ORDER BY rowid DESC LIMIT 1", (run_id,),
            ).fetchone()
            return dict(row) if row else None

    def expire_for_test(self, run_id: str) -> None:
        with self.facts.connect() as connection:
            connection.execute(
                "UPDATE run_leases SET expires_at=? WHERE run_id=?",
                ((_utc() - timedelta(seconds=1)).isoformat(), run_id),
            )
            connection.execute(
                "UPDATE commands SET claimed_until=? WHERE run_id=? "
                "AND status='CLAIMED'",
                ((_utc() - timedelta(seconds=1)).isoformat(), run_id),
            )


class StopRequested(RuntimeError):
    """Cooperative stop reached a safe node boundary."""
