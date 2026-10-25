import pytest
from threading import Event, Thread

from app.v0.provider import AgentResponse, FakeProvider
from app.v0.runner import V0Runner
from app.v0.schemas import CourseInput, QualitySummary, ReleaseDecision
from app.v0.storage import FactStore


COURSE = CourseInput(
    topic="Python 变量",
    audience="零基础学习者",
    goal="能解释并修改变量",
    language="zh",
)


def execute_legacy(runner: V0Runner, run_id: str) -> None:
    # Preserve downstream runner assertions for pre-migration Runs.
    if runner.store is not None:
        run = runner.get(run_id)
        run.constraints_version = 0
        run.source_evidence_version = 0
        run.context_contract_version = 0
        run.langgraph_flow_version = 0
        with runner.store.connect() as connection:
            connection.execute(
                "UPDATE runs SET mission_review_required=0, constraints_version=0, "
                "source_evidence_version=0, context_contract_version=0, langgraph_flow_version=0 "
                "WHERE id=?",
                (run_id,),
            )
            connection.execute(
                "UPDATE snapshots SET projection_json=? WHERE run_id=?",
                (run.model_dump_json(), run_id),
            )
    runner.execute(run_id)


def test_successful_runner_records_six_steps_and_waits_for_human():
    runner = V0Runner(FakeProvider())
    created = runner.create(COURSE)
    execute_legacy(runner, created.id)
    run = runner.get(created.id)

    assert [stage.name for stage in run.stages] == [
        "intake",
        "mission",
        "blueprint",
        "batch_plan",
        "generation",
        "quality",
        "release",
    ]
    assert [stage.status for stage in run.stages] == ["succeeded"] * 6 + [
        "waiting_for_human"
    ]
    assert all(stage.input_summary and stage.output_summary for stage in run.stages[:6])
    assert run.status == "waiting_for_human"
    assert run.lesson is not None
    assert run.quality is not None and run.quality.status == "ready"
    assert run.release_decision is None


def test_generation_failure_stops_later_stages():
    runner = V0Runner(FakeProvider(fail_at="writer"))
    run = runner.create(COURSE)
    execute_legacy(runner, run.id)
    failed = runner.get(run.id)

    assert failed.status == "failed"
    assert failed.stages[4].status == "failed"
    assert "writer" in (failed.stages[4].failure_reason or "")
    assert [stage.status for stage in failed.stages[5:]] == ["pending", "pending"]
    with pytest.raises(ValueError, match="等待人工"):
        runner.decide(run.id, ReleaseDecision(action="prepare", reason="人工确认"))


def test_human_stop_does_not_mark_run_ready_for_release():
    runner = V0Runner(FakeProvider())
    run = runner.create(COURSE)
    execute_legacy(runner, run.id)

    stopped = runner.decide(
        run.id, ReleaseDecision(action="stop", reason="课程需要进一步核对")
    )

    assert stopped.status == "stopped"
    assert stopped.stages[-1].status == "stopped"
    assert stopped.release_decision is not None
    assert stopped.release_decision.action == "stop"
    with pytest.raises(ValueError, match="等待人工"):
        runner.decide(run.id, ReleaseDecision(action="prepare", reason="再次提交"))


def test_snapshot_never_exposes_result_before_stage_succeeds():
    class PausingRunner(V0Runner):
        def __init__(self):
            super().__init__(FakeProvider())
            self.entered = Event()
            self.resume = Event()

        def _mark_succeeded(self, run_id, index, *args):
            if index == 1:
                self.entered.set()
                assert self.resume.wait(2)
            return super()._mark_succeeded(run_id, index, *args)

    runner = PausingRunner()
    run = runner.create(COURSE)
    worker = Thread(target=execute_legacy, args=(runner, run.id))
    worker.start()
    try:
        assert runner.entered.wait(2)
        snapshot = runner.get(run.id)
        assert snapshot.stages[1].status == "running"
        assert snapshot.mission is None
    finally:
        runner.resume.set()
        worker.join(timeout=2)


def test_ready_quality_always_discloses_v0_validation_limits():
    class OptimisticProvider(FakeProvider):
        def invoke(self, request):
            if request.role == "reviewer":
                return AgentResponse(
                    role="reviewer",
                    payload=QualitySummary(
                        status="ready",
                        checks=["标题存在"],
                        language_risk="部分句子需要人工复读",
                        limitations=["模型自述无其他限制"],
                    ).model_dump(),
                )
            return super().invoke(request)

    runner = V0Runner(OptimisticProvider())
    created = runner.create(COURSE)
    execute_legacy(runner, created.id)
    quality = runner.get(created.id).quality

    assert quality is not None
    assert "未核验事实来源" in quality.limitations
    assert "未执行完整课程量规" in quality.limitations
    assert "未执行完整 Humanizer 评分" in quality.limitations


def test_persistent_runner_rebuilds_after_restart(tmp_path):
    store = FactStore(tmp_path / "facts.sqlite3")
    runner = V0Runner(FakeProvider(), store=store)
    created = runner.create(COURSE, request_key="start-one")
    execute_legacy(runner, created.id)

    restored = V0Runner(FakeProvider(), store=store).get(created.id)
    assert restored.course_id is not None
    assert restored.status == "waiting_for_human"
    assert [stage.status for stage in restored.stages] == ["succeeded"] * 6 + [
        "waiting_for_human"
    ]
    assert {artifact.kind for artifact in restored.artifacts} == {
        "mission",
        "blueprint",
        "batch_plan",
        "lesson",
        "quality",
    }
    assert list(
        (tmp_path / "workspaces" / restored.course_id / "runs" / created.id).glob(
            "lesson-v*.md"
        )
    )

    with store.connect() as connection:
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (created.id,))
    rebuilt = V0Runner(FakeProvider(), store=store).get(created.id)
    assert rebuilt.model_dump() == restored.model_dump()


def test_persistent_generation_failure_has_failure_event(tmp_path):
    store = FactStore(tmp_path / "facts.sqlite3")
    runner = V0Runner(FakeProvider(fail_at="writer"), store=store)
    created = runner.create(COURSE, request_key="start-fail")
    execute_legacy(runner, created.id)
    failed = V0Runner(FakeProvider(), store=store).get(created.id)
    assert failed.status == "failed"
    assert failed.stages[4].status == "failed"
    assert failed.stages[5].status == "pending"
    with store.connect() as connection:
        types = [
            row[0]
            for row in connection.execute(
                "SELECT type FROM events WHERE run_id=? ORDER BY id", (created.id,)
            )
        ]
    assert types[-1] == "stage.failed"


def test_lesson_file_failure_does_not_claim_generation_success(tmp_path, monkeypatch):
    store = FactStore(tmp_path / "facts.sqlite3")
    runner = V0Runner(FakeProvider(), store=store)
    created = runner.create(COURSE, request_key="file-failure")

    def fail_write(*args):
        raise OSError("磁盘不可写")

    monkeypatch.setattr(store.workspace, "write_lesson", fail_write)
    execute_legacy(runner, created.id)
    failed = runner.get(created.id)
    assert failed.status == "failed"
    assert failed.stages[4].status == "failed"
    assert all(item.kind != "lesson" for item in failed.artifacts)
    with store.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM artifacts WHERE run_id=? AND kind='lesson'",
                (created.id,),
            ).fetchone()[0]
            == 0
        )


def test_artifact_transaction_failure_rolls_back_and_removes_file(tmp_path):
    store = FactStore(tmp_path / "facts.sqlite3")
    runner = V0Runner(FakeProvider(), store=store)
    created = runner.create(COURSE, request_key="db-failure")
    with store.connect() as connection:
        connection.execute(
            "CREATE TRIGGER deny_lesson BEFORE INSERT ON artifacts "
            "WHEN NEW.kind='lesson' BEGIN SELECT RAISE(ABORT, 'denied'); END"
        )
    execute_legacy(runner, created.id)
    failed = runner.get(created.id)
    assert failed.status == "failed"
    assert failed.stages[4].status == "failed"
    assert not list((tmp_path / "workspaces" / failed.course_id).rglob("*.md"))
    with store.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM artifacts WHERE run_id=? AND kind='lesson'",
                (created.id,),
            ).fetchone()[0]
            == 0
        )


def test_restart_preserves_accepted_run_for_worker_takeover(tmp_path):
    store = FactStore(tmp_path / "facts.sqlite3")
    created = V0Runner(FakeProvider(), store=store).create(
        COURSE, request_key="accepted-before-restart"
    )
    restored = V0Runner(FakeProvider(), store=store).get(created.id)
    assert restored.status == "running"
    assert restored.stages[0].status == "pending"
    assert restored.stages[0].failure_reason is None
    with store.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM events WHERE run_id=? AND type='run.interrupted'",
            (created.id,),
        ).fetchone()[0]
    V0Runner(FakeProvider(), store=store)
    with store.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM events WHERE run_id=? AND type='run.interrupted'",
                (created.id,),
            ).fetchone()[0]
            == count
            == 0
        )


def test_runner_invokes_roles_in_order_with_exact_artifact_handoffs(tmp_path):
    class RecordingProvider:
        def __init__(self):
            self.requests = []
            self.fake = FakeProvider()

        def invoke(self, request):
            self.requests.append(request)
            return self.fake.invoke(request)

    provider = RecordingProvider()
    runner = V0Runner(provider, store=FactStore(tmp_path / "facts.sqlite3"))
    created = runner.create(COURSE, request_key="role-order")
    execute_legacy(runner, created.id)

    assert [request.role for request in provider.requests] == [
        "mission",
        "blueprint",
        "writer",
        "reviewer",
        "reviewer",
    ]
    assert [item.kind for item in provider.requests[0].inputs] == ["intake"]
    assert provider.requests[0].inputs[0].reference is None
    assert [item.kind for item in provider.requests[1].inputs] == ["mission"]
    assert [item.kind for item in provider.requests[2].inputs] == [
        "mission",
        "blueprint",
        "batch_plan",
    ]
    assert [item.kind for item in provider.requests[3].inputs] == [
        "mission",
        "blueprint",
        "lesson",
    ]
    assert [item.kind for item in provider.requests[4].inputs] == ["lesson"]
    assert all(
        item.reference is not None
        for request in provider.requests[1:]
        for item in request.inputs
    )
    assert all(request.role != "repair" for request in provider.requests)


def test_invalid_agent_schema_is_visible_and_stops_the_current_stage(tmp_path):
    class InvalidBlueprintProvider(FakeProvider):
        def invoke(self, request):
            if request.role == "blueprint":
                return AgentResponse(
                    role="blueprint",
                    payload={"lessons": [], "private": "do-not-echo"},
                )
            return super().invoke(request)

    runner = V0Runner(
        InvalidBlueprintProvider(), store=FactStore(tmp_path / "facts.sqlite3")
    )
    created = runner.create(COURSE, request_key="invalid-blueprint")
    execute_legacy(runner, created.id)
    failed = runner.get(created.id)

    assert failed.status == "failed"
    assert failed.stages[2].status == "failed"
    assert "blueprint 输出校验失败" in (failed.stages[2].failure_reason or "")
    assert "do-not-echo" not in (failed.stages[2].failure_reason or "")
    assert [stage.status for stage in failed.stages[3:]] == ["pending"] * 4
