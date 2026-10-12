"""Durable execution protocol tests against a real SQLite file."""

import pytest

from app.v0.execution import ExecutionStore
from app.v0.schemas import CourseInput
from app.v0.schemas import GraphState
from app.v0.schemas import MissionDraft
from app.v0.storage import FactStore
from app.v0.provider import FakeProvider
from app.v0.provider import AgentResponse
from app.v0.worker import Worker


@pytest.fixture
def stores(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="变量", audience="初学者", goal="会解释变量", language="zh"),
        "create-1",
    )
    # These protocol tests predate Mission approval; preserve their downstream fixture.
    run.constraints_version = 0
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0, constraints_version=0 WHERE id=?",
            (run.id,),
        )
        connection.execute(
            "UPDATE snapshots SET projection_json=? WHERE run_id=?",
            (run.model_dump_json(), run.id),
        )
    return facts, ExecutionStore(facts.path), run.id


def test_command_idempotency_and_payload_conflict(stores):
    _, commands, run_id = stores
    first = commands.accept(run_id, "START", {}, "start-1")
    replay = commands.accept(run_id, "START", {}, "start-1")
    assert first.id == replay.id
    assert first.status == "ACCEPTED"
    with pytest.raises(ValueError, match="Idempotency"):
        commands.accept(run_id, "STOP", {}, "start-1")
    assert len(commands.list_commands(run_id)) == 1


def test_run_creation_and_start_command_share_replay_hash(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="变量", audience="初学者", goal="会解释变量", language="zh"),
        "start-key", enqueue_start=True,
    )
    commands = ExecutionStore(facts.path)
    replay = commands.accept(run.id, "START", {}, "start-key")
    assert replay.status == "ACCEPTED"
    assert len(commands.list_commands(run.id)) == 1


def test_two_workers_cannot_claim_same_command_or_lease(stores):
    _, commands, run_id = stores
    command = commands.accept(run_id, "START", {}, "start-1")
    claimed = commands.claim("worker-a")
    assert claimed.id == command.id
    assert commands.claim("worker-b") is None
    assert commands.acquire(run_id, "worker-a", ttl_seconds=60) == 1
    assert commands.acquire(run_id, "worker-b", ttl_seconds=60) is None


def test_busy_run_does_not_starve_other_run_commands(stores):
    facts, commands, first_run = stores
    second, _ = facts.create_run(
        CourseInput(topic="函数", audience="初学者", goal="会写函数", language="zh"),
        "create-2",
    )
    commands.accept(first_run, "START", {}, "first-start")
    commands.claim("worker-a")
    commands.acquire(first_run, "worker-a")
    commands.accept(first_run, "STOP", {}, "first-stop")
    commands.accept(second.id, "START", {}, "second-start")
    next_command = commands.claim("worker-b")
    assert next_command.run_id == second.id


def test_expired_lease_fences_previous_owner(stores):
    _, commands, run_id = stores
    commands.accept(run_id, "START", {}, "start-1")
    commands.claim("worker-a")
    epoch = commands.acquire(run_id, "worker-a", ttl_seconds=1)
    assert epoch == 1
    commands.expire_for_test(run_id)
    assert commands.acquire(run_id, "worker-b", ttl_seconds=60) == 2
    assert not commands.is_owner(run_id, "worker-a", epoch)
    assert commands.is_owner(run_id, "worker-b", 2)


def test_node_attempt_and_checkpoint_require_live_epoch(stores):
    _, commands, run_id = stores
    epoch = commands.acquire(run_id, "worker-a")
    state = GraphState(run_id=run_id)
    attempt = commands.start_node(run_id, "intake", state, "worker-a", epoch)
    assert commands.last_checkpoint(run_id)["position"] == "before_node"
    commands.expire_for_test(run_id)
    commands.acquire(run_id, "worker-b")
    with pytest.raises(PermissionError, match="lease"):
        commands.finish_node(attempt, state, "worker-a", epoch)
    assert commands.current_node(run_id)["status"] == "STARTED"


def test_stop_request_is_visible_before_command_claim(stores):
    _, commands, run_id = stores
    commands.accept(run_id, "STOP", {}, "stop-1")
    assert commands.stop_requested(run_id)
    assert commands.claim("worker-a").kind == "STOP"


def test_stale_worker_cannot_commit_artifact_or_checkpoint(stores):
    facts, commands, run_id = stores
    epoch = commands.acquire(run_id, "worker-a", ttl_seconds=1)
    attempt = commands.start_node(
        run_id, "mission", GraphState(run_id=run_id, current_node="mission"),
        "worker-a", epoch,
    )
    commands.expire_for_test(run_id)
    commands.acquire(run_id, "worker-b")
    run = facts.get_run(run_id)
    with pytest.raises(PermissionError, match="lease"):
        facts.record(
            run, "artifact.created", "mission",
            artifact=MissionDraft(
                audience="初学者", learning_goal="认识变量", scope="变量",
                stop_conditions=["完成练习"],
            ),
            lease_owner="worker-a", lease_epoch=epoch,
            node_execution_id=attempt,
            checkpoint_state=GraphState(run_id=run_id, current_node="mission"),
        )
    assert facts.list_artifacts(run_id) == []
    assert commands.last_checkpoint(run_id)["position"] == "before_node"


def test_worker_executes_accepted_start_independent_of_api(stores):
    facts, commands, run_id = stores
    commands.accept(run_id, "START", {}, "start-1")
    worker = Worker(facts.path, provider=FakeProvider(), owner="worker-a")
    assert worker.run_once()
    assert facts.get_run(run_id).status == "waiting_for_human"
    assert commands.list_commands(run_id)[0].status == "APPLIED"
    assert commands.current_node(run_id)["status"] == "COMMITTED"
    assert commands.last_checkpoint(run_id)["position"] == "after_node"
    assert commands.read_model(run_id).waiting_reason


def test_resume_accepts_exact_blueprint_chapter_deviation_once(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="变量", audience="初学者", goal="会解释变量", language="zh"),
        "chapter-deviation-create",
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0 WHERE id=?", (run.id,)
        )
    commands = ExecutionStore(facts.path)

    class FourteenLessons(FakeProvider):
        def invoke(self, request):
            if request.role == "blueprint":
                return AgentResponse(role="blueprint", payload={"lessons": [
                    {
                        "title": f"章节 {index}",
                        "learning_goal": f"学会主题 {index}",
                        "evidence": f"练习 {index}",
                    }
                    for index in range(14)
                ]})
            return super().invoke(request)

    commands.accept(run.id, "START", {}, "start-chapter-deviation")
    worker = Worker(facts.path, provider=FourteenLessons(), owner="worker-a")
    assert worker.run_once()
    waiting = facts.get_run(run.id)
    assert waiting.stages[3].status == "waiting_for_human"
    blueprint = next(item for item in waiting.artifacts if item.kind == "blueprint")

    commands.accept(run.id, "RESUME", {}, "accept-chapter-deviation")
    assert worker.run_once()

    resumed = facts.get_run(run.id)
    assert resumed.batch_plan is not None
    with facts.connect() as connection:
        events = connection.execute(
            "SELECT artifact_id, artifact_version FROM events WHERE run_id=? "
            "AND type='blueprint.chapter_deviation_accepted'",
            (run.id,),
        ).fetchall()
    assert len(events) == 1
    assert (events[0]["artifact_id"], events[0]["artifact_version"]) == (
        blueprint.artifact_id,
        blueprint.version,
    )


def test_token_limit_stops_before_next_node_and_cannot_resume(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(
            topic="变量",
            audience="初学者",
            goal="会解释变量",
            language="zh",
            token_limit=120,
        ),
        "token-stop-create",
        enqueue_start=True,
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0 WHERE id=?", (run.id,)
        )
    commands = ExecutionStore(facts.path)

    class MeteredMission(FakeProvider):
        def invoke(self, request):
            response = super().invoke(request)
            if request.role == "mission":
                response.input_tokens = 100
                response.output_tokens = 20
            return response

    worker = Worker(facts.path, provider=MeteredMission(), owner="worker-a")
    assert worker.run_once()

    stopped = facts.get_run(run.id)
    assert stopped.status == "stopped"
    assert stopped.stages[1].status == "succeeded"
    assert stopped.stages[2].status == "stopped"
    assert stopped.stages[2].failure_reason == "token_limit_reached"
    assert commands.last_checkpoint(run.id)["position"] == "after_node"
    with facts.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM node_executions WHERE run_id=? AND node='blueprint'",
            (run.id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM events WHERE run_id=? "
            "AND type='budget.token_exhausted'",
            (run.id,),
        ).fetchone()[0] == 1

    commands.accept(run.id, "RESUME", {}, "resume-token-stopped")
    assert worker.run_once()
    assert commands.list_commands(run.id)[-1].status == "REJECTED"
    with facts.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM node_executions WHERE run_id=? AND node='blueprint'",
            (run.id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM events WHERE run_id=? "
            "AND type='budget.token_exhausted'",
            (run.id,),
        ).fetchone()[0] == 1


def test_token_limit_allows_restarting_the_uncommitted_current_node(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(
            topic="变量",
            audience="初学者",
            goal="会解释变量",
            language="zh",
            token_limit=10,
        ),
        "token-recovery-create",
    )
    commands = ExecutionStore(facts.path)
    epoch = commands.acquire(run.id, "worker-a")
    state = GraphState(run_id=run.id, current_node="mission")
    commands.start_node(run.id, "mission", state, "worker-a", epoch)
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO provider_calls(id,run_id,role,status,input_tokens,"
            "output_tokens,started_at) VALUES (?,?,?,'SUCCEEDED',8,2,'now')",
            ("current-node-call", run.id, "mission"),
        )

    commands.start_node(run.id, "mission", state, "worker-a", epoch)

    with pytest.raises(RuntimeError, match="token_limit_reached"):
        commands.start_node(
            run.id,
            "blueprint",
            state.model_copy(update={"current_node": "blueprint"}),
            "worker-a",
            epoch,
        )

def test_crash_after_mission_artifact_reuses_committed_version(stores):
    facts, commands, run_id = stores
    commands.accept(run_id, "START", {}, "start-1")
    first = Worker(facts.path, provider=FakeProvider(), owner="worker-a")
    claimed = commands.claim("worker-a")
    epoch = commands.acquire(run_id, "worker-a")
    original = first.runner._node_finished

    def crash_after_mission(state, result):
        if result["current_node"] == "mission":
            raise RuntimeError("simulated process death")
        original(state, result)

    first.runner._node_finished = crash_after_mission
    with pytest.raises(RuntimeError, match="process death"):
        first._apply(claimed, epoch)
    assert commands.last_checkpoint(run_id)["position"] == "after_artifact"
    mission = [item for item in facts.list_artifacts(run_id) if item.kind == "mission"]
    assert len(mission) == 1
    commands.expire_for_test(run_id)
    assert Worker(facts.path, provider=FakeProvider(), owner="worker-b").run_once()
    assert facts.get_run(run_id).status == "waiting_for_human"
    assert len([item for item in facts.list_artifacts(run_id) if item.kind == "mission"]) == 1


def test_stop_during_node_allows_commit_but_blocks_next_node(stores):
    facts, commands, run_id = stores

    class StopDuringMission(FakeProvider):
        def invoke(self, request):
            if request.role == "mission":
                commands.accept(run_id, "STOP", {}, "stop-1")
            return super().invoke(request)

    commands.accept(run_id, "START", {}, "start-1")
    worker = Worker(facts.path, provider=StopDuringMission(), owner="worker-a")
    assert worker.run_once()
    run = facts.get_run(run_id)
    assert run.status == "stopped"
    assert run.stages[1].status == "succeeded"
    assert run.stages[2].status == "pending"
    assert len([item for item in facts.list_artifacts(run_id) if item.kind == "mission"]) == 1
    assert worker.run_once()
    assert [item.status for item in commands.list_commands(run_id)] == ["APPLIED", "APPLIED"]


def test_revise_is_persisted_and_resume_continues_from_checkpoint(stores):
    facts, commands, run_id = stores

    class StopDuringMission(FakeProvider):
        def invoke(self, request):
            if request.role == "mission":
                commands.accept(run_id, "STOP", {}, "stop-1")
            return super().invoke(request)

    commands.accept(run_id, "START", {}, "start-1")
    worker = Worker(facts.path, provider=StopDuringMission(), owner="worker-a")
    worker.run_once()
    worker.run_once()
    checkpoint = commands.last_checkpoint(run_id)["id"]
    commands.accept(
        run_id, "REVISE", {"text": "请补充练习", "expected_checkpoint_id": checkpoint},
        "revise-1",
    )
    assert worker.run_once()
    assert commands.read_model(run_id).human_input_revision >= 2
    commands.accept(run_id, "RESUME", {}, "resume-1")
    assert worker.run_once()
    assert facts.get_run(run_id).status == "waiting_for_human"
    assert facts.get_run(run_id).stages[2].status == "succeeded"


def test_new_stop_arriving_during_resume_is_not_cleared(stores):
    facts, commands, run_id = stores

    class StopDuringMission(FakeProvider):
        def invoke(self, request):
            if request.role == "mission":
                commands.accept(run_id, "STOP", {}, "first-stop")
            return super().invoke(request)

    commands.accept(run_id, "START", {}, "start-1")
    worker = Worker(facts.path, provider=StopDuringMission(), owner="worker-a")
    worker.run_once()
    worker.run_once()
    commands.accept(run_id, "RESUME", {}, "resume-1")
    original = worker.execution.prepare_resume

    def stop_just_after_resume(*args):
        original(*args)
        commands.accept(run_id, "STOP", {}, "second-stop")

    worker.execution.prepare_resume = stop_just_after_resume
    worker.run_once()
    assert facts.get_run(run_id).status == "stopped"
    assert facts.get_run(run_id).stages[2].status == "pending"
    assert commands.stop_requested(run_id)


def test_stop_before_first_node_prevents_all_artifacts(stores):
    facts, commands, run_id = stores
    commands.accept(run_id, "START", {}, "start-1")
    commands.accept(run_id, "STOP", {}, "stop-1")
    worker = Worker(facts.path, provider=FakeProvider(), owner="worker-a")
    worker.run_once()
    assert facts.get_run(run_id).status == "stopped"
    assert facts.list_artifacts(run_id) == []
    assert commands.current_node(run_id) is None
    assert commands.last_checkpoint(run_id)["position"] == "before_node"
    worker.run_once()  # apply STOP command
    commands.accept(run_id, "RESUME", {}, "resume-1")
    worker.run_once()
    assert facts.get_run(run_id).status == "waiting_for_human"


def test_revise_rejects_stale_checkpoint_without_changing_input(stores):
    facts, commands, run_id = stores
    commands.accept(run_id, "START", {}, "start-1")
    commands.accept(run_id, "STOP", {}, "stop-1")
    worker = Worker(facts.path, provider=FakeProvider(), owner="worker-a")
    worker.run_once()
    commands.accept(
        run_id, "REVISE", {"text": "修改目标", "expected_checkpoint_id": "old"},
        "revise-stale",
    )
    worker.run_once()
    worker.run_once()
    assert commands.list_commands(run_id)[2].status == "REJECTED"
    assert commands.read_model(run_id).human_input_revision == 0


def test_business_failure_does_not_implicitly_retry_on_resume(stores):
    facts, commands, run_id = stores
    commands.accept(run_id, "START", {}, "start-1")
    worker = Worker(facts.path, provider=FakeProvider(fail_at="writer"))
    worker.run_once()
    assert facts.get_run(run_id).status == "failed"
    assert commands.list_commands(run_id)[0].status == "FAILED"
    assert commands.current_node(run_id)["status"] == "FAILED"
    commands.accept(run_id, "RESUME", {}, "resume-1")
    worker.run_once()
    assert commands.list_commands(run_id)[1].status == "REJECTED"


def test_crash_after_first_lesson_reuses_it_and_completes_two_batches(stores):
    facts, commands, run_id = stores

    class FourLessons(FakeProvider):
        def invoke(self, request):
            if request.role == "blueprint":
                return AgentResponse(role="blueprint", payload={"lessons": [
                    {"title": f"章节 {index}", "learning_goal": f"学会主题 {index}",
                     "evidence": f"练习 {index}"}
                    for index in range(4)
                ]})
            return super().invoke(request)

    commands.accept(run_id, "START", {}, "start-1")
    first = Worker(facts.path, provider=FourLessons(), owner="worker-a")
    command = commands.claim("worker-a")
    epoch = commands.acquire(run_id, "worker-a")
    original = first.runner._persist_candidate
    calls = 0

    def crash_after_lesson(*args):
        nonlocal calls
        original(*args)
        calls += 1
        if calls == 1:
            raise SystemExit("simulated process death")

    first.runner._persist_candidate = crash_after_lesson
    with pytest.raises(SystemExit, match="process death"):
        first._apply(command, epoch)
    first_ref = [item for item in facts.list_artifacts(run_id) if item.kind == "lesson"][0]
    commands.expire_for_test(run_id)
    assert Worker(facts.path, provider=FourLessons(), owner="worker-b").run_once()
    run = facts.get_run(run_id)
    assert run.status == "waiting_for_human"
    assert len(run.batch_plan.continuity_ledger) == 4
    assert len(run.batch_plan.batch_ids) == 2
    lessons = [item for item in facts.list_artifacts(run_id) if item.kind == "lesson"]
    assert len(lessons) == 4
    assert lessons[0].artifact_id == first_ref.artifact_id
    assert lessons[0].version == first_ref.version


def test_crash_after_human_wait_is_reconciled_without_rerunning_graph(stores):
    facts, commands, run_id = stores
    commands.accept(run_id, "START", {}, "start-1")
    first = Worker(facts.path, provider=FakeProvider(), owner="worker-a")
    command = commands.claim("worker-a")
    epoch = commands.acquire(run_id, "worker-a")
    original = first.runner._node_finished

    def crash_at_release(state, result):
        if result["current_node"] == "release":
            raise SystemExit("simulated process death")
        original(state, result)

    first.runner._node_finished = crash_at_release
    with pytest.raises(SystemExit, match="process death"):
        first._apply(command, epoch)
    assert facts.get_run(run_id).status == "waiting_for_human"
    assert commands.last_checkpoint(run_id)["position"] == "after_artifact"
    artifact_count = len(facts.list_artifacts(run_id))
    commands.expire_for_test(run_id)
    Worker(facts.path, provider=FakeProvider(), owner="worker-b").run_once()
    assert commands.list_commands(run_id)[0].status == "APPLIED"
    assert commands.current_node(run_id)["status"] == "COMMITTED"
    assert len(facts.list_artifacts(run_id)) == artifact_count


def test_crash_after_business_failure_keeps_start_command_failed(stores):
    facts, commands, run_id = stores
    commands.accept(run_id, "START", {}, "start-1")
    first = Worker(facts.path, provider=FakeProvider(fail_at="mission"), owner="worker-a")
    command = commands.claim("worker-a")
    epoch = commands.acquire(run_id, "worker-a")
    original = first.runner._node_finished

    def crash_after_failure(state, result):
        if result.get("last_outcome") == "failed":
            raise SystemExit("simulated process death")
        original(state, result)

    first.runner._node_finished = crash_after_failure
    with pytest.raises(SystemExit):
        first._apply(command, epoch)
    assert facts.get_run(run_id).status == "failed"
    commands.expire_for_test(run_id)
    Worker(facts.path, provider=FakeProvider(), owner="worker-b").run_once()
    assert commands.list_commands(run_id)[0].status == "FAILED"
    assert commands.current_node(run_id)["status"] == "FAILED"


def test_crash_after_quality_artifact_reuses_committed_result(stores):
    facts, commands, run_id = stores
    commands.accept(run_id, "START", {}, "start-1")
    first = Worker(facts.path, provider=FakeProvider(), owner="worker-a")
    command = commands.claim("worker-a")
    epoch = commands.acquire(run_id, "worker-a")
    original = first.runner._persist_system_artifact

    def crash_after_quality(run_id_arg, stage, artifact, refs):
        original(run_id_arg, stage, artifact, refs)
        if stage == "quality":
            raise SystemExit("simulated process death")

    first.runner._persist_system_artifact = crash_after_quality
    with pytest.raises(SystemExit, match="process death"):
        first._apply(command, epoch)
    assert commands.last_checkpoint(run_id)["position"] == "after_artifact"
    quality_before = [item for item in facts.list_artifacts(run_id) if item.kind == "quality"]
    assert len(quality_before) == 1
    commands.expire_for_test(run_id)
    second = Worker(facts.path, provider=FakeProvider(), owner="worker-b")
    claimed = commands.claim("worker-b")
    second_epoch = commands.acquire(run_id, "worker-b")
    original_start = second.execution.start_node

    def crash_during_recovery(*args):
        attempt = original_start(*args)
        if args[1] == "quality":
            raise SystemExit("second process death")
        return attempt

    second.execution.start_node = crash_during_recovery
    with pytest.raises(SystemExit, match="second process death"):
        second._apply(claimed, second_epoch)
    assert commands.last_checkpoint(run_id)["position"] == "before_node"
    commands.expire_for_test(run_id)
    Worker(facts.path, provider=FakeProvider(), owner="worker-c").run_once()
    quality_after = [item for item in facts.list_artifacts(run_id) if item.kind == "quality"]
    assert len(quality_after) == 1
    assert facts.get_run(run_id).status == "waiting_for_human"


def test_crash_after_repair_candidate_does_not_create_second_candidate(stores):
    facts, commands, run_id = stores

    class Repairing(FakeProvider):
        def invoke(self, request):
            response = super().invoke(request)
            if request.role == "writer":
                response.payload["markdown"] = "标题缺失\n\n正文和练习。"
            if request.role == "repair":
                response.payload["markdown"] = "# 修好的标题"
            return response

    commands.accept(run_id, "START", {}, "start-1")
    first = Worker(facts.path, provider=Repairing(), owner="worker-a")
    command = commands.claim("worker-a")
    epoch = commands.acquire(run_id, "worker-a")
    original = first.runner._persist_repair_candidate

    def crash_after_candidate(*args):
        original(*args)
        raise SystemExit("simulated process death")

    first.runner._persist_repair_candidate = crash_after_candidate
    with pytest.raises(SystemExit, match="process death"):
        first._apply(command, epoch)
    before = [item for item in facts.list_artifacts(run_id) if item.kind == "lesson"]
    assert [item.version for item in before] == [1, 2]
    commands.expire_for_test(run_id)
    Worker(facts.path, provider=Repairing(), owner="worker-b").run_once()
    after = [item for item in facts.list_artifacts(run_id) if item.kind == "lesson"]
    assert [item.version for item in after] == [1, 2]
    assert facts.get_run(run_id).status == "waiting_for_human"


def test_crash_after_repair_task_reuses_quality_task_artifact(stores):
    facts, commands, run_id = stores

    class Repairing(FakeProvider):
        def invoke(self, request):
            response = super().invoke(request)
            if request.role == "writer":
                response.payload["markdown"] = "标题缺失\n\n正文和练习。"
            if request.role == "repair":
                response.payload["markdown"] = "# 修好的标题"
            return response

    commands.accept(run_id, "START", {}, "start-1")
    first = Worker(facts.path, provider=Repairing(), owner="worker-a")
    command = commands.claim("worker-a")
    epoch = commands.acquire(run_id, "worker-a")
    original = first.runner._persist_system_artifact

    def crash_after_task(run_id_arg, stage, artifact, refs):
        original(run_id_arg, stage, artifact, refs)
        if stage == "quality" and artifact.repair_tasks:
            raise SystemExit("simulated process death")

    first.runner._persist_system_artifact = crash_after_task
    with pytest.raises(SystemExit):
        first._apply(command, epoch)
    before = [item for item in facts.list_artifacts(run_id) if item.kind == "quality"]
    assert len(before) == 2
    commands.expire_for_test(run_id)
    Worker(facts.path, provider=Repairing(), owner="worker-b").run_once()
    after = [item for item in facts.list_artifacts(run_id) if item.kind == "quality"]
    assert len(after) == 3
    assert facts.get_run(run_id).status == "waiting_for_human"


def test_crash_after_candidate_acceptance_does_not_repeat_accept_event(stores):
    facts, commands, run_id = stores

    class Repairing(FakeProvider):
        def invoke(self, request):
            response = super().invoke(request)
            if request.role == "writer":
                response.payload["markdown"] = "标题缺失\n\n正文和练习。"
            if request.role == "repair":
                response.payload["markdown"] = "# 修好的标题"
            return response

    commands.accept(run_id, "START", {}, "start-1")
    first = Worker(facts.path, provider=Repairing(), owner="worker-a")
    command = commands.claim("worker-a")
    epoch = commands.acquire(run_id, "worker-a")
    original = first.runner._accept_repair_candidate

    def crash_after_accept(*args):
        original(*args)
        raise SystemExit("simulated process death")

    first.runner._accept_repair_candidate = crash_after_accept
    with pytest.raises(SystemExit):
        first._apply(command, epoch)
    commands.expire_for_test(run_id)
    Worker(facts.path, provider=Repairing(), owner="worker-b").run_once()
    with facts.connect() as connection:
        accepted = connection.execute(
            "SELECT COUNT(*) FROM events WHERE run_id=? AND type='candidate.accepted'",
            (run_id,),
        ).fetchone()[0]
    assert accepted == 1
    assert facts.get_run(run_id).status == "waiting_for_human"


def test_crash_after_verification_quality_reuses_committed_summary(stores):
    facts, commands, run_id = stores

    class Repairing(FakeProvider):
        def invoke(self, request):
            response = super().invoke(request)
            if request.role == "writer":
                response.payload["markdown"] = "标题缺失\n\n正文和练习。"
            if request.role == "repair":
                response.payload["markdown"] = "# 修好的标题"
            return response

    commands.accept(run_id, "START", {}, "start-1")
    first = Worker(facts.path, provider=Repairing(), owner="worker-a")
    command = commands.claim("worker-a")
    epoch = commands.acquire(run_id, "worker-a")
    original = first.runner._persist_system_artifact

    def crash_after_verified_summary(run_id_arg, stage, artifact, refs):
        original(run_id_arg, stage, artifact, refs)
        if stage == "quality" and artifact.resolved_finding_ids:
            raise SystemExit("simulated process death")

    first.runner._persist_system_artifact = crash_after_verified_summary
    with pytest.raises(SystemExit):
        first._apply(command, epoch)
    quality_before = [item for item in facts.list_artifacts(run_id) if item.kind == "quality"]
    commands.expire_for_test(run_id)
    Worker(facts.path, provider=Repairing(), owner="worker-b").run_once()
    quality_after = [item for item in facts.list_artifacts(run_id) if item.kind == "quality"]
    assert len(quality_after) == len(quality_before)
    assert facts.get_run(run_id).status == "waiting_for_human"


def test_crash_after_candidate_rejection_does_not_repeat_reject_event(stores):
    facts, commands, run_id = stores

    class FailingRepair(FakeProvider):
        def invoke(self, request):
            response = super().invoke(request)
            if request.role == "writer":
                response.payload["markdown"] = "标题缺失\n\n正文和练习。"
            if request.role == "repair":
                response.payload["markdown"] = "仍然没有标题"
            return response

    commands.accept(run_id, "START", {}, "start-1")
    first = Worker(facts.path, provider=FailingRepair(), owner="worker-a")
    command = commands.claim("worker-a")
    epoch = commands.acquire(run_id, "worker-a")
    original = first.runner._reject_repair_candidate

    def crash_after_reject(*args):
        original(*args)
        raise SystemExit("simulated process death")

    first.runner._reject_repair_candidate = crash_after_reject
    with pytest.raises(SystemExit):
        first._apply(command, epoch)
    commands.expire_for_test(run_id)
    Worker(facts.path, provider=FailingRepair(), owner="worker-b").run_once()
    with facts.connect() as connection:
        rejected = connection.execute(
            "SELECT COUNT(*) FROM events WHERE run_id=? AND type='candidate.rejected'",
            (run_id,),
        ).fetchone()[0]
    assert rejected == 2
    assert facts.get_run(run_id).status == "waiting_for_human"
