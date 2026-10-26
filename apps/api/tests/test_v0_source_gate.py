from app.v0.graph import build_graph, route_after_source_gate
from app.v0.langgraph_checkpoint import (
    checkpoint_path,
    open_checkpointer,
    thread_config,
)
from app.v0.provider import FakeProvider
from app.v0.schemas import CourseInput, GraphState
from app.v0.storage import FactStore
from app.v0.worker import Worker


def state(**updates):
    return GraphState(run_id="run-1", current_node="source_gate", **updates)


def test_route_after_source_gate_uses_normalized_action():
    assert route_after_source_gate(
        state(
            last_outcome="succeeded", approval_action="approve",
            source_gate_context="blueprint",
        )
    ) == "blueprint"
    assert route_after_source_gate(
        state(
            last_outcome="succeeded", approval_action="retry_search",
            source_gate_context="generation",
        )
    ) == "generation"
    assert route_after_source_gate(
        state(
            last_outcome="succeeded", approval_action="reject",
            source_gate_context="blueprint",
        )
    ) == "route_error"
    assert route_after_source_gate(
        state(
            last_outcome="succeeded", approval_action=None,
            source_gate_context="blueprint",
        )
    ) == "route_error"


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
    approval = commands.read_model(run.id).approval
    assert approval is not None
    assert approval.type == "SOURCE_APPROVAL"
    assert "retry_search" in approval.actions
    with facts.connect() as connection:
        execution = connection.execute(
            "SELECT id, status, pending_interrupt_id FROM node_executions "
            "WHERE run_id=? AND node='source_gate' "
            "ORDER BY rowid DESC LIMIT 1",
            (run.id,),
        ).fetchone()
    assert execution["status"] == "WAITING"
    assert execution["pending_interrupt_id"]
    assert review.checkpoint_id == execution["id"]
    assert approval.checkpoint_id == execution["id"]

    with open_checkpointer(checkpoint_path(facts.path)) as saver:
        graph = build_graph(worker.runner, checkpointer=saver)
        snapshot = graph.get_state(thread_config(run.id))
    assert snapshot.interrupts
    assert snapshot.interrupts[0].value["type"] == "SOURCE_APPROVAL"
    assert "retry_search" in snapshot.interrupts[0].value["actions"]

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
