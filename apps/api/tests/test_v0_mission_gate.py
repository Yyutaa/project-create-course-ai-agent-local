from langgraph.graph import END

from app.v0.graph import (
    build_graph,
    route_after_mission_flow,
    route_after_mission_gate,
)
from app.v0.langgraph_checkpoint import (
    checkpoint_path,
    open_checkpointer,
    thread_config,
)
from app.v0.provider import FakeProvider
from app.v0.runner import V0Runner
from app.v0.schemas import CourseInput, GraphState
from app.v0.storage import FactStore
from app.v0.worker import Worker


def state(**updates):
    return GraphState(run_id="run-1", current_node="mission_gate", **updates)


def test_route_after_mission_gate():
    assert route_after_mission_gate(
        state(last_outcome="succeeded", mission_decision="approve")
    ) == "blueprint"
    assert route_after_mission_gate(
        state(last_outcome="succeeded", mission_decision="revise")
    ) == "mission"
    assert route_after_mission_gate(
        state(last_outcome="waiting_for_human")
    ) == END


def test_route_after_mission_flow():
    success = GraphState(
        run_id="run-1", current_node="mission", last_outcome="succeeded",
    )
    assert route_after_mission_flow(
        success, langgraph_flow_version=1, mission_review_required=True,
    ) == "mission_gate"
    assert route_after_mission_flow(
        success, langgraph_flow_version=0, mission_review_required=True,
    ) == "blueprint"
    assert route_after_mission_flow(
        success, langgraph_flow_version=1, mission_review_required=False,
    ) == "blueprint"


def test_graph_contains_mission_gate_node():
    graph = build_graph(V0Runner(FakeProvider()))
    assert "mission_gate" in graph.get_graph().nodes


def make_run(facts: FactStore):
    run, _ = facts.create_run(
        CourseInput(
            topic="变量", audience="初学者", goal="解释变量", language="zh",
            expected_chapters=1, min_effective_chars=1,
        ),
        "mission-gate-run",
        enqueue_start=True,
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET source_evidence_version=0 WHERE id=?", (run.id,),
        )
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run.id,))
    return run


def approve_payload(review):
    return {
        "action": "approve",
        "mission_ref": review.mission_ref.model_dump(mode="json"),
        "expected_checkpoint_id": review.checkpoint_id,
    }


def test_mission_gate_interrupts_and_approval_resumes(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run = make_run(facts)
    worker = Worker(facts.path, provider=FakeProvider(), owner="worker-a")
    assert worker.run_once()
    commands = worker.execution

    current = facts.get_run(run.id)
    assert current.status == "waiting_for_human"
    assert current.stages[1].status == "waiting_for_human"
    with facts.connect() as connection:
        execution = connection.execute(
            "SELECT status, input_hash FROM node_executions "
            "WHERE run_id=? AND node='mission_gate' ORDER BY rowid DESC LIMIT 1",
            (run.id,),
        ).fetchone()
    assert execution["status"] == "WAITING"
    assert execution["input_hash"]

    review = commands.read_model(run.id).mission_review
    assert review is not None and review.status == "pending"

    with open_checkpointer(checkpoint_path(facts.path)) as saver:
        graph = build_graph(worker.runner, checkpointer=saver)
        snapshot = graph.get_state(thread_config(run.id))
    assert snapshot.interrupts

    commands.accept(
        run.id, "MISSION_REVIEW", approve_payload(review), "approve-1",
    )
    assert worker.run_once()
    resumed = facts.get_run(run.id)
    assert resumed.stages[1].status == "succeeded"
    assert resumed.blueprint is not None


def test_mission_gate_revision_regenerates_and_interrupts_again(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run = make_run(facts)
    worker = Worker(facts.path, provider=FakeProvider(), owner="worker-a")
    assert worker.run_once()
    commands = worker.execution
    review = commands.read_model(run.id).mission_review
    assert review is not None

    commands.accept(run.id, "MISSION_REVIEW", {
        "action": "revise",
        "mission_ref": review.mission_ref.model_dump(mode="json"),
        "expected_checkpoint_id": review.checkpoint_id,
        "feedback": "学习目标改得更具体",
    }, "revise-1")
    assert worker.run_once()

    current = facts.get_run(run.id)
    assert current.status == "waiting_for_human"
    assert current.stages[1].status == "waiting_for_human"
    missions = [
        item for item in facts.list_artifacts(run.id) if item.kind == "mission"
    ]
    assert len(missions) == 2
    latest_review = facts.latest_mission_review(run.id)
    assert latest_review["action"] == "revise"
    second = commands.read_model(run.id).mission_review
    assert second is not None and second.status == "pending"
    assert second.mission_ref.version == 2
