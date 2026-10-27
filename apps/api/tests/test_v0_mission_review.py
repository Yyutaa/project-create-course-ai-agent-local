"""Mission approval is a durable, version-bound execution decision."""

import sqlite3

import pytest

from app.v0.execution import ExecutionStore
from app.v0.context import ContextPackBuilder
from app.v0.artifact_tools import ArtifactTools
from app.v0.agents import AGENT_DEFINITIONS
from app.v0.schemas import ArtifactRef, CourseInput, GraphState, MissionDraft
from app.v0.storage import FactStore
from app.v0.provider import FakeProvider
from app.v0.provider import AgentResponse
from app.v0.worker import Worker
from app.v0.delivery import DeliveryStore
from app.v0.token_preflight import TokenPreflightError


COURSE = CourseInput(
    topic="变量", audience="初学者", goal="会解释变量", language="zh"
)


def disable_source_evidence(facts: FactStore, run_id: str) -> None:
    """Keep Mission-only protocol fixtures on their original downstream path."""
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET source_evidence_version=0 WHERE id=?", (run_id,),
        )
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run_id,))


def create_legacy_run(facts: FactStore, course, key: str, **kwargs):
    """Create a Run pinned to the pre-LangGraph mission gate flow."""
    run, created = facts.create_run(course, key, **kwargs)
    run.langgraph_flow_version = 0
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET langgraph_flow_version=0 WHERE id=?", (run.id,),
        )
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run.id,))
    return run, created


def test_v4_run_migrates_without_retroactive_mission_gate(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE runs (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO runs VALUES ('old-run')")
        connection.execute("PRAGMA user_version=4")
    facts = FactStore(path)
    facts.migrate()
    facts.migrate()
    assert facts.schema_version() == 20
    assert facts.mission_review_required("old-run") is False


def test_new_run_requires_mission_review_and_accepts_idempotent_command(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = create_legacy_run(facts, COURSE, "create-1")
    assert facts.mission_review_required(run.id)

    commands = ExecutionStore(facts.path)
    payload = {"action": "approve", "mission_ref": {"artifact_id": "mission-1"}}
    first = commands.accept(run.id, "MISSION_REVIEW", payload, "review-1")
    replay = commands.accept(run.id, "MISSION_REVIEW", payload, "review-1")
    assert first.id == replay.id
    assert first.status == "ACCEPTED"
    with pytest.raises(ValueError, match="Idempotency"):
        commands.accept(
            run.id, "MISSION_REVIEW", {**payload, "action": "revise"}, "review-1"
        )


def waiting_mission(facts, commands, run_id):
    owner = "worker-a"
    epoch = commands.acquire(run_id, owner)
    state = GraphState(run_id=run_id, current_node="mission")
    attempt = commands.start_node(run_id, "mission", state, owner, epoch)
    mission = MissionDraft(
        audience="初学者", learning_goal="解释变量", scope="变量基础",
        stop_conditions=["目标冲突时停止"],
    )
    run = facts.get_run(run_id)
    run.mission = mission
    run.status = "waiting_for_human"
    run.stages[1].status = "waiting_for_human"
    run.stages[1].failure_reason = "Mission 待人工确认"
    facts.record(
        run, "stage.waiting", "mission", artifact=mission,
        producer_role="mission", lease_owner=owner, lease_epoch=epoch,
        node_execution_id=attempt, checkpoint_state=state,
    )
    item = facts.list_artifacts(run_id)[-1]
    ref = ArtifactRef(
        run_id=run_id, artifact_id=item.artifact_id, version=item.version,
        kind="mission", content_hash=item.content_hash,
    )
    commands.finish_node(
        attempt,
        state.model_copy(update={
            "artifact_refs": {"mission": ref},
            "last_outcome": "waiting_for_human",
        }),
        owner, epoch,
    )
    return owner, epoch, ref, commands.last_checkpoint(run_id)["id"]


def test_mission_decision_is_version_bound_and_replay_safe(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = create_legacy_run(facts, COURSE, "create-1")
    commands = ExecutionStore(facts.path)
    owner, epoch, ref, checkpoint_id = waiting_mission(facts, commands, run.id)
    payload = {
        "action": "approve", "mission_ref": ref.model_dump(),
        "expected_checkpoint_id": checkpoint_id,
    }
    command = commands.accept(run.id, "MISSION_REVIEW", payload, "approve-v1")
    assert commands.claim(owner).id == command.id
    first = commands.apply_mission_review(command, owner, epoch)
    second = commands.apply_mission_review(command, owner, epoch)
    assert first["id"] == second["id"]
    assert facts.get_run(run.id).stages[1].status == "succeeded"
    assert facts.get_run(run.id).status == "running"
    assert facts.latest_mission_review(run.id)["action"] == "approve"
    with facts.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM mission_reviews WHERE run_id=?", (run.id,)
        ).fetchone()[0] == 1
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run.id,))
    rebuilt = facts.get_run(run.id)
    assert rebuilt.status == "running"
    assert rebuilt.stages[1].status == "succeeded"


def test_new_run_waits_for_mission_review_before_blueprint(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = create_legacy_run(facts, COURSE, "create-1", enqueue_start=True)
    worker = Worker(facts.path, provider=FakeProvider())
    assert worker.run_once()
    current = facts.get_run(run.id)
    assert current.status == "waiting_for_human"
    assert current.stages[1].status == "waiting_for_human"
    assert current.mission is not None
    assert current.blueprint is None
    assert len([a for a in facts.list_artifacts(run.id) if a.kind == "mission"]) == 1


def test_stop_after_mission_can_resume_into_langgraph_mission_gate(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(COURSE, "stop-before-gate", enqueue_start=True)
    commands = ExecutionStore(facts.path)

    class StopDuringMission(FakeProvider):
        def invoke(self, request):
            if request.role == "mission":
                commands.accept(run.id, "STOP", {}, "stop-during-mission")
            return super().invoke(request)

    worker = Worker(facts.path, provider=StopDuringMission())
    assert worker.run_once()  # Mission commits, then STOP blocks mission_gate.
    assert worker.run_once()  # Apply STOP.
    stopped = facts.get_run(run.id)
    assert stopped.status == "stopped"
    assert stopped.stages[1].status == "succeeded"
    assert commands.waiting_interrupt_id(run.id) is None
    assert facts.latest_mission_review(run.id) is None

    commands.accept(run.id, "RESUME", {}, "resume-to-gate")
    assert worker.run_once()
    resumed = facts.get_run(run.id)
    assert commands.list_commands(run.id)[-1].status == "APPLIED"
    assert resumed.status == "waiting_for_human"
    assert resumed.stages[1].status == "waiting_for_human"
    assert resumed.blueprint is None
    assert commands.waiting_interrupt_id(run.id) is not None
    assert facts.latest_mission_review(run.id) is None
    assert len([a for a in facts.list_artifacts(run.id) if a.kind == "mission"]) == 1

    commands.accept(run.id, "RESUME", {}, "resume-cannot-approve")
    assert worker.run_once()
    assert commands.list_commands(run.id)[-1].status == "REJECTED"
    assert commands.list_commands(run.id)[-1].error == (
        "Mission 待人工确认，请提交 MISSION_REVIEW"
    )
    assert facts.get_run(run.id).blueprint is None
    assert facts.latest_mission_review(run.id) is None


def test_blueprint_resume_reuses_approved_mission_gate(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    course = COURSE.model_copy(update={
        "expected_chapters": 1, "min_effective_chars": 1,
    })
    run, _ = facts.create_run(course, "blueprint-preflight", enqueue_start=True)
    disable_source_evidence(facts, run.id)
    commands = ExecutionStore(facts.path)

    class BlueprintPreflightOnce(FakeProvider):
        rejected = False

        def preflight(self, request):
            if request.role == "blueprint" and not self.rejected:
                self.rejected = True
                raise TokenPreflightError("最终消息超过 Token 预算")

    worker = Worker(facts.path, provider=BlueprintPreflightOnce())
    assert worker.run_once()
    commands.accept(
        run.id, "MISSION_REVIEW",
        review_payload(facts, commands, run.id, "approve"),
        "approve-mission",
    )
    assert worker.run_once()
    assert facts.get_run(run.id).stages[2].failure_reason == "最终消息超过 Token 预算"
    assert commands.read_model(run.id).waiting_reason == "最终消息超过 Token 预算"
    approved = facts.latest_mission_review(run.id)
    assert approved["action"] == "approve"

    commands.accept(run.id, "RESUME", {}, "resume-blueprint")
    assert worker.run_once()
    assert commands.list_commands(run.id)[-1].status == "APPLIED"
    assert facts.get_run(run.id).blueprint is not None
    gate = commands.waiting_gate_state(run.id)
    assert gate is None or gate["node"] != "mission_gate"
    assert facts.latest_mission_review(run.id)["id"] == approved["id"]


def test_resume_recovers_stale_gate_for_exactly_approved_mission(tmp_path, monkeypatch):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    course = COURSE.model_copy(update={
        "expected_chapters": 1, "min_effective_chars": 1,
    })
    run, _ = facts.create_run(course, "stale-approved-gate", enqueue_start=True)
    disable_source_evidence(facts, run.id)
    commands = ExecutionStore(facts.path)

    class BlueprintPreflightOnce(FakeProvider):
        rejected = False

        def preflight(self, request):
            if request.role == "blueprint" and not self.rejected:
                self.rejected = True
                raise TokenPreflightError("最终消息超过 Token 预算")

    worker = Worker(facts.path, provider=BlueprintPreflightOnce())
    assert worker.run_once()
    commands.accept(
        run.id, "MISSION_REVIEW",
        review_payload(facts, commands, run.id, "approve"),
        "approve-stale-mission",
    )
    assert worker.run_once()
    approved = facts.latest_mission_review(run.id)

    # Recreate the old replay behavior once, then restore the real store.
    original_review = worker.runner.store.latest_mission_review
    monkeypatch.setattr(
        worker.runner.store, "latest_mission_review", lambda _: None,
    )
    commands.accept(run.id, "RESUME", {}, "recreate-stale-gate")
    assert worker.run_once()
    monkeypatch.setattr(
        worker.runner.store, "latest_mission_review", original_review,
    )
    gate = commands.waiting_gate_state(run.id)
    assert gate is not None and gate["node"] == "mission_gate"
    assert facts.get_run(run.id).blueprint is None

    with facts.connect() as connection:
        connection.execute(
            "UPDATE mission_reviews SET content_hash=? WHERE id=?",
            ("different-hash", approved["id"]),
        )
    commands.accept(run.id, "RESUME", {}, "reject-stale-hash")
    assert worker.run_once()
    assert commands.list_commands(run.id)[-1].status == "REJECTED"
    with facts.connect() as connection:
        connection.execute(
            "UPDATE mission_reviews SET content_hash=? WHERE id=?",
            (approved["content_hash"], approved["id"]),
        )

    commands.accept(run.id, "RESUME", {}, "recover-stale-gate")
    # A restarted Worker may use a different provider fingerprint than the
    # one that wrote this obsolete interrupt.
    commands.expire_for_test(run.id)
    assert Worker(facts.path, provider=FakeProvider()).run_once()
    assert commands.list_commands(run.id)[-1].status == "APPLIED"
    assert facts.get_run(run.id).blueprint is not None
    assert facts.latest_mission_review(run.id)["id"] == approved["id"]


def test_mission_review_failure_names_downstream_stage_and_safe_cause(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        COURSE.model_copy(update={
            "expected_chapters": 1, "min_effective_chars": 1,
        }),
        "review-downstream-failure", enqueue_start=True,
    )
    disable_source_evidence(facts, run.id)
    commands = ExecutionStore(facts.path)
    worker = Worker(facts.path, provider=FakeProvider(fail_at="writer"))
    assert worker.run_once()
    commands.accept(
        run.id, "MISSION_REVIEW",
        review_payload(facts, commands, run.id, "approve"),
        "approve-before-writer-fails",
    )
    assert worker.run_once()
    result = commands.list_commands(run.id)[-1]
    assert result.status == "FAILED"
    assert result.error == (
        "Mission 审批已保存；后续 generation 阶段失败：writer 固定失败夹具"
    )
    assert commands.read_model(run.id).commands[-1].error == result.error
    assert facts.latest_mission_review(run.id)["action"] == "approve"


def test_historical_hidden_mission_review_error_uses_persisted_stage(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        COURSE.model_copy(update={
            "expected_chapters": 1, "min_effective_chars": 1,
        }),
        "historical-review-error", enqueue_start=True,
    )
    disable_source_evidence(facts, run.id)
    commands = ExecutionStore(facts.path)
    worker = Worker(facts.path, provider=FakeProvider(fail_at="writer"))
    assert worker.run_once()
    commands.accept(
        run.id, "MISSION_REVIEW",
        review_payload(facts, commands, run.id, "approve"),
        "approve-before-historical-error",
    )
    assert worker.run_once()
    command = commands.list_commands(run.id)[-1]
    with facts.connect() as connection:
        connection.execute(
            "UPDATE commands SET error=? WHERE id=?",
            ("RuntimeError：细节已隐藏，请检查受限诊断信息", command.id),
        )
    assert commands.read_model(run.id).commands[-1].error == (
        "Mission 审批已保存；后续 generation 阶段失败：writer 固定失败夹具"
    )


def test_revision_context_and_source_reference_are_limited_to_prior_mission(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = create_legacy_run(facts, COURSE, "create-1")
    commands = ExecutionStore(facts.path)
    _, _, prior, _ = waiting_mission(facts, commands, run.id)
    pack = ContextPackBuilder(facts.get_artifact).for_mission_revision(
        run.id, COURSE, prior, "把目标改成能独立解释变量"
    )
    assert pack.role == "mission"
    assert [item.kind for item in pack.inputs] == ["intake"]
    assert pack.inputs[0].content["revision_request"]["feedback"] == (
        "把目标改成能独立解释变量"
    )
    assert pack.inputs[0].content["revision_request"]["prior_ref"]["version"] == 1
    tools = ArtifactTools(AGENT_DEFINITIONS, facts.get_artifact)
    candidate = tools.write_candidate_artifact(
        "mission", run.id, "mission",
        MissionDraft(
            audience="初学者", learning_goal="解释变量", scope="变量基础",
            stop_conditions=["目标冲突时停止"],
        ),
        [prior], lambda item: item,
    )
    assert candidate.source_refs == [prior]


def review_payload(facts, commands, run_id, action, feedback=None):
    item = next(
        a for a in reversed(facts.list_artifacts(run_id)) if a.kind == "mission"
    )
    payload = {
        "action": action,
        "mission_ref": ArtifactRef(
            run_id=run_id, artifact_id=item.artifact_id, version=item.version,
            kind="mission", content_hash=item.content_hash,
        ).model_dump(),
        "expected_checkpoint_id": commands.last_checkpoint(run_id)["id"],
    }
    if feedback is not None:
        payload["feedback"] = feedback
    return payload


def test_worker_approval_continues_from_mission_to_blueprint(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = create_legacy_run(facts, COURSE, "create-1", enqueue_start=True)
    disable_source_evidence(facts, run.id)
    commands = ExecutionStore(facts.path)
    worker = Worker(facts.path, provider=FakeProvider())
    assert worker.run_once()
    assert facts.get_run(run.id).blueprint is None
    command = commands.accept(
        run.id, "MISSION_REVIEW", review_payload(facts, commands, run.id, "approve"),
        "approve-v1",
    )
    assert worker.run_once()
    assert next(c for c in commands.list_commands(run.id) if c.id == command.id).status == "APPLIED"
    assert facts.get_run(run.id).blueprint is not None
    assert facts.latest_mission_review(run.id)["action"] == "approve"


def test_worker_revision_keeps_v1_and_waits_again_for_v2(tmp_path):
    class RevisingProvider(FakeProvider):
        def invoke(self, request):
            if request.role == "mission" and "revision_request" in request.inputs[0].content:
                assert request.inputs[0].content["revision_request"]["feedback"] == (
                    "目标改为解释列表"
                )
                return AgentResponse(role="mission", payload={
                    "audience": "初学者", "learning_goal": "解释列表",
                    "scope": "列表基础", "stop_conditions": ["目标冲突时停止"],
                })
            return super().invoke(request)

    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = create_legacy_run(facts, COURSE, "create-1", enqueue_start=True)
    commands = ExecutionStore(facts.path)
    worker = Worker(facts.path, provider=RevisingProvider())
    assert worker.run_once()
    commands.accept(
        run.id, "MISSION_REVIEW",
        review_payload(facts, commands, run.id, "revise", "目标改为解释列表"),
        "revise-v1",
    )
    assert worker.run_once()
    current = facts.get_run(run.id)
    assert current.status == "waiting_for_human"
    assert current.blueprint is None
    assert current.mission.learning_goal == "解释列表"
    missions = [a for a in facts.list_artifacts(run.id) if a.kind == "mission"]
    assert [a.version for a in missions] == [1, 2]
    assert missions[1].source_refs[0].version == 1


def test_resume_cannot_approve_mission_by_itself(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = create_legacy_run(facts, COURSE, "create-1", enqueue_start=True)
    commands = ExecutionStore(facts.path)
    worker = Worker(facts.path, provider=FakeProvider())
    worker.run_once()
    commands.accept(run.id, "RESUME", {}, "resume-without-review")
    worker.run_once()
    assert commands.list_commands(run.id)[-1].status == "REJECTED"
    assert facts.get_run(run.id).blueprint is None


def test_stale_checkpoint_rejects_mission_review_without_decision(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = create_legacy_run(facts, COURSE, "create-1", enqueue_start=True)
    commands = ExecutionStore(facts.path)
    worker = Worker(facts.path, provider=FakeProvider())
    worker.run_once()
    payload = review_payload(facts, commands, run.id, "approve")
    payload["expected_checkpoint_id"] = "stale-checkpoint"
    commands.accept(run.id, "MISSION_REVIEW", payload, "stale-review")
    worker.run_once()
    assert commands.list_commands(run.id)[-1].status == "REJECTED"
    assert facts.latest_mission_review(run.id) is None
    assert facts.get_run(run.id).blueprint is None


def test_stale_mission_hash_rejects_review_without_decision(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = create_legacy_run(facts, COURSE, "create-1", enqueue_start=True)
    commands = ExecutionStore(facts.path)
    worker = Worker(facts.path, provider=FakeProvider())
    worker.run_once()
    payload = review_payload(facts, commands, run.id, "approve")
    payload["mission_ref"]["content_hash"] = "stale-hash"
    commands.accept(run.id, "MISSION_REVIEW", payload, "stale-hash")
    worker.run_once()
    assert commands.list_commands(run.id)[-1].status == "REJECTED"
    assert facts.latest_mission_review(run.id) is None
    assert facts.get_run(run.id).blueprint is None


def test_crash_after_review_decision_replays_without_second_decision(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = create_legacy_run(facts, COURSE, "create-1", enqueue_start=True)
    disable_source_evidence(facts, run.id)
    commands = ExecutionStore(facts.path)
    first = Worker(facts.path, provider=FakeProvider(), owner="worker-a")
    first.run_once()
    command = commands.accept(
        run.id, "MISSION_REVIEW", review_payload(facts, commands, run.id, "approve"),
        "approve-v1",
    )
    claimed = commands.claim(first.owner)
    assert claimed.id == command.id
    epoch = commands.acquire(run.id, first.owner)
    first.runner.execute = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("simulated crash after decision")
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        first._apply(claimed, epoch)
    assert facts.latest_mission_review(run.id)["action"] == "approve"
    commands.expire_for_test(run.id)
    assert Worker(facts.path, provider=FakeProvider(), owner="worker-b").run_once()
    assert facts.get_run(run.id).blueprint is not None
    with facts.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM mission_reviews WHERE run_id=?", (run.id,)
        ).fetchone()[0] == 1


def test_mission_review_is_indexed_as_redacted_human_evidence(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = create_legacy_run(facts, COURSE, "create-1", enqueue_start=True)
    commands = ExecutionStore(facts.path)
    worker = Worker(facts.path, provider=FakeProvider())
    worker.run_once()
    commands.accept(
        run.id, "MISSION_REVIEW",
        review_payload(facts, commands, run.id, "revise", "PRIVATE_FEEDBACK_731"),
        "revise-v1",
    )
    worker.run_once()
    evidence = DeliveryStore(facts.path).read(run.id)
    assert any(decision.kind == "mission.revision_requested" for decision in evidence.decisions)
    assert next(path for path in evidence.paths if path.scenario == "human").status == "observed"
    assert "PRIVATE_FEEDBACK_731" not in evidence.model_dump_json()


def test_stop_accepted_before_approval_blocks_blueprint(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = create_legacy_run(facts, COURSE, "create-1", enqueue_start=True)
    commands = ExecutionStore(facts.path)
    worker = Worker(facts.path, provider=FakeProvider())
    worker.run_once()
    commands.accept(
        run.id, "MISSION_REVIEW", review_payload(facts, commands, run.id, "approve"),
        "approve-v1",
    )
    commands.accept(run.id, "STOP", {}, "stop-before-approval")
    assert worker.run_once()
    assert facts.get_run(run.id).blueprint is None
    assert facts.get_run(run.id).status == "stopped"


def test_crash_after_mission_artifact_reuses_version_on_takeover(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = create_legacy_run(facts, COURSE, "create-1", enqueue_start=True)
    first = Worker(facts.path, provider=FakeProvider(), owner="worker-a")
    first.runner._mark_waiting = lambda *args: (_ for _ in ()).throw(
        SystemExit("crash after mission artifact")
    )
    with pytest.raises(SystemExit, match="crash after mission artifact"):
        first.run_once()
    assert len([a for a in facts.list_artifacts(run.id) if a.kind == "mission"]) == 1
    ExecutionStore(facts.path).expire_for_test(run.id)
    assert Worker(facts.path, provider=FakeProvider(), owner="worker-b").run_once()
    assert facts.get_run(run.id).stages[1].status == "waiting_for_human"
    assert len([a for a in facts.list_artifacts(run.id) if a.kind == "mission"]) == 1
