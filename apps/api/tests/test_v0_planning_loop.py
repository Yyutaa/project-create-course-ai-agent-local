"""Bounded Blueprint replanning preserves the original persisted candidate."""

import pytest

from app.v0.provider import AgentResponse, FakeProvider, TransientProviderError
from app.v0.execution import ExecutionStore
from app.v0.context import ContextPackBuilder
from app.v0.runner import V0Runner
from app.v0.schemas import ArtifactRecord, ArtifactRef, CourseInput
from app.v0.storage import FactStore
from app.v0.worker import Worker


class SequencedBlueprint(FakeProvider):
    def __init__(self, chapter_counts: list[int]):
        super().__init__()
        self.chapter_counts = chapter_counts
        self.requests = []

    def invoke(self, request):
        if request.role != "blueprint":
            return super().invoke(request)
        self.requests.append(request)
        count = self.chapter_counts[len(self.requests) - 1]
        return AgentResponse(role="blueprint", payload={"lessons": [
            {"title": f"章节 {index + 1}", "learning_goal": f"目标 {index + 1}",
             "evidence": f"练习 {index + 1}"}
            for index in range(count)
        ]})


def run_planning(tmp_path, expected: int, chapter_counts: list[int], *, legacy=False):
    facts = FactStore(tmp_path / "facts.sqlite3")
    provider = SequencedBlueprint(chapter_counts)
    runner = V0Runner(provider, store=facts)
    created = runner.create(CourseInput(
        topic="变量", audience="初学者", goal="完成课程", language="zh",
        expected_chapters=expected, min_effective_chars=1,
    ), request_key="planning")
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0, source_evidence_version=0, "
            "planning_loop_version=? WHERE id=?", (0 if legacy else 1, created.id),
        )
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (created.id,))
    runner.execute(created.id)
    return facts, provider, facts.get_run(created.id)


def test_new_run_persists_planning_policy_and_migrated_run_defaults_to_legacy(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(CourseInput(
        topic="变量", audience="初学者", goal="完成课程", language="zh",
    ), "new-policy")
    assert facts.schema_version() == 13
    assert facts.get_run(run.id).planning_loop_version == 1
    with facts.connect() as connection:
        connection.execute("UPDATE runs SET planning_loop_version=0 WHERE id=?", (run.id,))
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run.id,))
    assert facts.get_run(run.id).planning_loop_version == 0


def test_v12_migration_defaults_existing_run_to_legacy_and_is_repeatable(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(CourseInput(
        topic="变量", audience="初学者", goal="完成课程", language="zh",
    ), "before-v13")
    with facts.connect() as connection:
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run.id,))
        connection.execute("ALTER TABLE runs DROP COLUMN planning_loop_version")
        connection.execute("PRAGMA user_version=12")
    facts.migrate()
    facts.migrate()
    assert facts.schema_version() == 13
    assert facts.get_run(run.id).planning_loop_version == 0


def test_large_valid_prior_blueprint_has_bounded_replan_context():
    run_id = "large-replan"
    mission_ref = ArtifactRef(
        run_id=run_id, artifact_id="mission", version=1,
        kind="mission", content_hash="mission-hash",
    )
    blueprint_ref = ArtifactRef(
        run_id=run_id, artifact_id="blueprint", version=1,
        kind="blueprint", content_hash="blueprint-hash",
    )
    records = {
        "mission": ArtifactRecord(
            artifact_id="mission", version=1, run_id=run_id, kind="mission",
            content={"audience": "初学者", "learning_goal": "掌握状态",
                     "scope": "状态", "stop_conditions": ["完成练习"]},
            content_hash="mission-hash",
        ),
        "blueprint": ArtifactRecord(
            artifact_id="blueprint", version=1, run_id=run_id,
            kind="blueprint", content={"lessons": [
                {"title": f"第 {index} 章", "learning_goal": "理解基本概念",
                 "evidence": "完成对应练习", "lesson_id": f"lesson-{index}",
                 "batch_id": "batch"}
                for index in range(98)
            ]}, content_hash="blueprint-hash",
        ),
    }
    pack = ContextPackBuilder(lambda artifact_id, _version: records[artifact_id]).for_blueprint(
        run_id, mission_ref, expected_chapters=100,
        previous_blueprint_ref=blueprint_ref,
    )
    assert pack.total_chars <= 8_000
    assert pack.inputs[1].content["previous_chapter_count"] == 98
    assert "lessons" not in pack.inputs[1].content


@pytest.mark.parametrize(
    ("expected", "chapter_counts"),
    [(1, [2, 1]), (2, [1, 2]), (3, [1, 3])],
)
def test_new_run_replans_once_and_preserves_blueprint_versions(
    tmp_path, expected, chapter_counts
):
    facts, provider, run = run_planning(tmp_path, expected, chapter_counts)
    blueprints = [item for item in run.artifacts if item.kind == "blueprint"]
    assert [item.version for item in blueprints] == [1, 2]
    assert run.batch_plan is not None
    assert len(run.blueprint.lessons) == chapter_counts[1]
    assert len(provider.requests) == 2
    assert any(
        ref.artifact_id == blueprints[0].artifact_id
        and ref.version == blueprints[0].version
        for ref in blueprints[1].source_refs
    )
    with facts.connect() as connection:
        events = connection.execute(
            "SELECT type, artifact_version FROM events WHERE run_id=? "
            "AND type='blueprint.replan_requested'", (run.id,),
        ).fetchall()
    assert [(item["type"], item["artifact_version"]) for item in events] == [
        ("blueprint.replan_requested", 1)
    ]


def test_new_run_waits_after_two_bad_blueprints_without_third_call(tmp_path):
    facts, provider, run = run_planning(tmp_path, 2, [1, 1])
    assert run.stages[3].status == "waiting_for_human"
    assert run.stages[3].failure_reason == "blueprint_chapter_deviation"
    assert run.batch_plan is None
    assert len(provider.requests) == 2
    assert [item.version for item in run.artifacts if item.kind == "blueprint"] == [1, 2]
    with facts.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM events WHERE run_id=? AND "
            "type='blueprint.replan_exhausted'", (run.id,),
        ).fetchone()[0] == 1


def test_three_chapters_allows_one_chapter_difference_without_replan(tmp_path):
    _, provider, run = run_planning(tmp_path, 3, [2])
    assert run.batch_plan is not None
    assert len(provider.requests) == 1


def test_legacy_two_chapter_run_keeps_one_chapter_tolerance(tmp_path):
    _, provider, run = run_planning(tmp_path, 2, [1], legacy=True)
    assert run.batch_plan is not None
    assert len(provider.requests) == 1


def test_source_missing_does_not_trigger_blueprint_replan(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    provider = SequencedBlueprint([1, 2])
    runner = V0Runner(provider, store=facts)
    run = runner.create(CourseInput(
        topic="React state", audience="初学者", goal="理解状态", language="zh",
        expected_chapters=2, min_effective_chars=1,
    ), request_key="missing-source")
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0 WHERE id=?", (run.id,),
        )
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run.id,))
    runner.execute(run.id)
    assert facts.get_run(run.id).stages[2].failure_reason == "source_evidence_insufficient"
    assert provider.requests == []


def test_blueprint_schema_error_is_not_replanned(tmp_path):
    class InvalidBlueprint(FakeProvider):
        calls = 0

        def invoke(self, request):
            if request.role == "blueprint":
                self.calls += 1
                return AgentResponse(role="blueprint", payload={"lessons": []})
            return super().invoke(request)

    facts = FactStore(tmp_path / "facts.sqlite3")
    provider = InvalidBlueprint()
    runner = V0Runner(provider, store=facts)
    run = runner.create(CourseInput(
        topic="变量", audience="初学者", goal="理解变量", language="zh",
        expected_chapters=2, min_effective_chars=1,
    ), request_key="invalid-blueprint")
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0, source_evidence_version=0 "
            "WHERE id=?", (run.id,),
        )
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run.id,))
    runner.execute(run.id)
    assert facts.get_run(run.id).stages[2].status == "failed"
    assert provider.calls == 1
    with facts.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM events WHERE run_id=? AND "
            "type='blueprint.replan_requested'", (run.id,),
        ).fetchone()[0] == 0


def test_writer_timeout_keeps_existing_failure_semantics(tmp_path):
    class WriterTimeout(SequencedBlueprint):
        writer_calls = 0

        def invoke(self, request):
            if request.role == "writer":
                self.writer_calls += 1
                raise TransientProviderError("timeout")
            return super().invoke(request)

    facts = FactStore(tmp_path / "facts.sqlite3")
    provider = WriterTimeout([1])
    runner = V0Runner(provider, store=facts)
    run = runner.create(CourseInput(
        topic="变量", audience="初学者", goal="理解变量", language="zh",
        expected_chapters=1, min_effective_chars=1,
    ), request_key="writer-timeout")
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0, source_evidence_version=0 "
            "WHERE id=?", (run.id,),
        )
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run.id,))
    runner.execute(run.id)
    assert facts.get_run(run.id).stages[4].status == "failed"
    assert provider.writer_calls == 1


def worker_planning(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(CourseInput(
        topic="变量", audience="初学者", goal="理解变量", language="zh",
        expected_chapters=2, min_effective_chars=1,
    ), "worker-planning", enqueue_start=True)
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0, source_evidence_version=0 "
            "WHERE id=?", (run.id,),
        )
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run.id,))
    provider = SequencedBlueprint([1, 1])
    return facts, run.id, provider


def test_new_run_manual_deviation_acceptance_requires_exact_checkpoint_and_ref(tmp_path):
    facts, run_id, provider = worker_planning(tmp_path)
    commands = ExecutionStore(facts.path)
    worker = Worker(facts.path, provider=provider, owner="worker-a")
    assert worker.run_once()
    waiting = facts.get_run(run_id)
    latest = [item for item in waiting.artifacts if item.kind == "blueprint"][-1]
    reference = ArtifactRef(
        run_id=run_id, artifact_id=latest.artifact_id,
        version=latest.version, kind="blueprint", content_hash=latest.content_hash,
    )
    checkpoint = commands.last_checkpoint(run_id)["id"]
    commands.accept(run_id, "RESUME", {
        "expected_checkpoint_id": checkpoint,
        "blueprint_ref": reference.model_copy(update={"version": 1}).model_dump(),
    }, "stale-accept")
    assert worker.run_once()
    assert commands.list_commands(run_id)[-1].status == "REJECTED"
    commands.accept(run_id, "RESUME", {
        "expected_checkpoint_id": checkpoint,
        "blueprint_ref": reference.model_dump(),
    }, "exact-accept")
    assert worker.run_once()
    assert facts.get_run(run_id).batch_plan is not None
    assert len(provider.requests) == 2
    with facts.connect() as connection:
        accepted = connection.execute(
            "SELECT artifact_version FROM events WHERE run_id=? AND "
            "type='blueprint.chapter_deviation_accepted'", (run_id,),
        ).fetchall()
    assert [row[0] for row in accepted] == [2]


@pytest.mark.parametrize("crash_at", ["before_event", "event", "artifact"])
def test_worker_takeover_reuses_committed_replan_fact(tmp_path, crash_at):
    facts, run_id, provider = worker_planning(tmp_path)
    commands = ExecutionStore(facts.path)
    first = Worker(facts.path, provider=provider, owner="worker-a")
    command = commands.claim(first.owner)
    epoch = commands.acquire(run_id, first.owner)
    if crash_at in ("before_event", "event"):
        original = first.runner._record_artifact_event

        def crash_after_event(run_id, event_type, stage, reference):
            if crash_at == "before_event" and event_type == "blueprint.replan_requested":
                raise KeyboardInterrupt("simulated crash before replan event")
            original(run_id, event_type, stage, reference)
            if crash_at == "event" and event_type == "blueprint.replan_requested":
                raise KeyboardInterrupt("simulated crash after replan event")

        first.runner._record_artifact_event = crash_after_event
    else:
        original = first.runner._node_finished

        def crash_after_artifact(state, result):
            if result.get("current_node") == "blueprint" and len(provider.requests) == 2:
                raise RuntimeError("simulated crash after blueprint artifact")
            original(state, result)

        first.runner._node_finished = crash_after_artifact
    with pytest.raises((RuntimeError, KeyboardInterrupt), match="simulated crash"):
        first._apply(command, epoch)
    assert commands.last_checkpoint(run_id)["position"] == "after_artifact"
    commands.expire_for_test(run_id)
    second = Worker(facts.path, provider=provider, owner="worker-b")
    assert second.run_once()
    current = facts.get_run(run_id)
    assert current.stages[3].status == "waiting_for_human"
    assert len(provider.requests) == 2
    assert [item.version for item in current.artifacts if item.kind == "blueprint"] == [1, 2]
    with facts.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM events WHERE run_id=? AND "
            "type='blueprint.replan_requested'", (run_id,),
        ).fetchone()[0] == 1
