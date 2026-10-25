from app.v0.provider import FakeProvider
from app.v0.schemas import CourseInput
from app.v0.storage import FactStore
from app.v0.worker import Worker


def make_run(facts: FactStore):
    run, _ = facts.create_run(
        CourseInput(
            topic="变量", audience="初学者", goal="解释变量", language="zh",
            expected_chapters=1, min_effective_chars=1,
        ),
        "source-gate-run",
        enqueue_start=True,
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0, "
            "source_evidence_version=1 WHERE id=?", (run.id,),
        )
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run.id,))
    return run


def test_source_gate_interrupts_and_retry_resumes(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run = make_run(facts)
    worker = Worker(facts.path, provider=FakeProvider(), owner="worker-a")
    assert worker.run_once()
    commands = worker.execution

    current = facts.get_run(run.id)
    assert current.status == "waiting_for_human"
    assert current.stages[2].status == "waiting_for_human"
    review = commands.read_model(run.id).source_review
    assert review is not None
    with facts.connect() as connection:
        execution = connection.execute(
            "SELECT status, pending_interrupt_id FROM node_executions "
            "WHERE run_id=? AND node='source_gate' "
            "ORDER BY rowid DESC LIMIT 1",
            (run.id,),
        ).fetchone()
    assert execution["status"] == "WAITING"
    assert execution["pending_interrupt_id"]

    commands.accept(
        run.id, "SOURCE_REVIEW", {
            "action": "retry_search",
            "expected_checkpoint_id": review.checkpoint_id,
        },
        "source-retry",
    )
    assert worker.run_once()
    resumed = facts.get_run(run.id)
    assert resumed.status == "waiting_for_human"
    with facts.connect() as connection:
        decisions = connection.execute(
            "SELECT action FROM source_decisions WHERE run_id=?", (run.id,),
        ).fetchall()
        latest = connection.execute(
            "SELECT status FROM node_executions WHERE run_id=? "
            "AND node='source_gate' ORDER BY rowid DESC LIMIT 1",
            (run.id,),
        ).fetchone()
    assert [item["action"] for item in decisions] == ["retry_search"]
    assert latest["status"] == "WAITING"
