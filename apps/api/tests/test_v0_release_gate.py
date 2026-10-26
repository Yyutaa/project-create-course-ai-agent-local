from langgraph.graph import END

from app.v0.graph import build_graph, route_after_release_gate
from app.v0.langgraph_checkpoint import (
    checkpoint_path,
    open_checkpointer,
    thread_config,
)
from app.v0.provider import FakeProvider
from app.v0.schemas import CourseInput, GraphState, ReleaseDecision
from app.v0.storage import FactStore
from app.v0.worker import Worker


def state(**updates):
    return GraphState(run_id="run-1", current_node="release_gate", **updates)


def test_route_after_release_gate_uses_normalized_action():
    assert route_after_release_gate(
        state(last_outcome="succeeded", approval_action="prepare")
    ) == "release"
    assert route_after_release_gate(
        state(last_outcome="succeeded", approval_action="stop")
    ) == "release"
    assert route_after_release_gate(
        state(last_outcome="succeeded", approval_action=None)
    ) == "route_error"
    assert route_after_release_gate(
        state(last_outcome="waiting_for_human")
    ) == END


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

    approval = worker.execution.read_model(run.id).approval
    assert approval is not None
    assert approval.type == "RELEASE_APPROVAL"
    assert approval.actions == ["prepare", "stop"]

    current = facts.get_run(run.id)
    assert current.status == "waiting_for_human"
    assert current.stages[6].status == "waiting_for_human"
    with facts.connect() as connection:
        execution = connection.execute(
            "SELECT id, status, pending_interrupt_id FROM node_executions "
            "WHERE run_id=? AND node='release_gate' "
            "ORDER BY rowid DESC LIMIT 1",
            (run.id,),
        ).fetchone()
    assert execution["status"] == "WAITING"
    assert execution["pending_interrupt_id"]
    assert approval.checkpoint_id == execution["id"]

    with open_checkpointer(checkpoint_path(facts.path)) as saver:
        graph = build_graph(worker.runner, checkpointer=saver)
        snapshot = graph.get_state(thread_config(run.id))
    assert snapshot.interrupts
    assert snapshot.interrupts[0].value["type"] == "RELEASE_APPROVAL"
    assert snapshot.interrupts[0].value["actions"] == ["prepare", "stop"]

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
