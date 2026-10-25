from app.v0.provider import FakeProvider
from app.v0.schemas import CourseInput, ReleaseDecision
from app.v0.storage import FactStore
from app.v0.worker import Worker


def make_run(facts: FactStore):
    run, _ = facts.create_run(
        CourseInput(
            topic="变量", audience="初学者", goal="解释变量", language="zh",
            expected_chapters=1, min_effective_chars=1,
        ),
        "release-gate-run",
        enqueue_start=True,
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0, "
            "source_evidence_version=0 WHERE id=?", (run.id,),
        )
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run.id,))
    return run


def test_release_gate_interrupts_and_api_decision_resumes(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run = make_run(facts)
    worker = Worker(facts.path, provider=FakeProvider(), owner="worker-a")
    assert worker.run_once()

    current = facts.get_run(run.id)
    assert current.status == "waiting_for_human"
    assert current.stages[6].status == "waiting_for_human"
    with facts.connect() as connection:
        execution = connection.execute(
            "SELECT status, pending_interrupt_id FROM node_executions "
            "WHERE run_id=? AND node='release_gate' "
            "ORDER BY rowid DESC LIMIT 1",
            (run.id,),
        ).fetchone()
    assert execution["status"] == "WAITING"
    assert execution["pending_interrupt_id"]

    released = worker.runner.decide(
        run.id,
        ReleaseDecision(action="prepare", reason="人工确认可以发布"),
        "release-gate-decision",
    )
    assert released.status == "ready_for_release"
    assert released.stages[6].status == "succeeded"
    assert released.release_decision is not None
    assert released.release_decision.action == "prepare"
    with facts.connect() as connection:
        execution = connection.execute(
            "SELECT status, pending_interrupt_id FROM node_executions "
            "WHERE run_id=? AND node='release_gate' "
            "ORDER BY rowid DESC LIMIT 1",
            (run.id,),
        ).fetchone()
    assert execution["status"] == "COMMITTED"
    assert execution["pending_interrupt_id"] is None
