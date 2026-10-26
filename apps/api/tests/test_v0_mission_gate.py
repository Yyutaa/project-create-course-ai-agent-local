import json

from langgraph.graph import END

from app.v0.graph import (
    build_graph,
    route_after_mission_flow,
    route_after_mission_gate,
    route_from_action,
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


def test_route_from_action_uses_normalized_action():
    state = GraphState(
        run_id="run-1", current_node="mission_gate",
        last_outcome="succeeded", approval_action="approve",
    )
    assert route_from_action(
        state, targets={"approve": "blueprint", "revise": "mission"},
    ) == "blueprint"
    revised = state.model_copy(update={"approval_action": "revise"})
    assert route_from_action(
        revised, targets={"approve": "blueprint", "revise": "mission"},
    ) == "mission"
    missing = state.model_copy(update={"approval_action": None})
    assert route_from_action(
        missing, targets={"approve": "blueprint", "revise": "mission"},
    ) == "route_error"


def test_route_after_mission_gate():
    assert route_after_mission_gate(
        state(last_outcome="succeeded", approval_action="approve")
    ) == "blueprint"
    assert route_after_mission_gate(
        state(last_outcome="succeeded", approval_action="revise")
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
            "SELECT id, status, input_hash FROM node_executions "
            "WHERE run_id=? AND node='mission_gate' ORDER BY rowid DESC LIMIT 1",
            (run.id,),
        ).fetchone()
    assert execution["status"] == "WAITING"
    assert execution["input_hash"]
    with facts.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE run_id=?", (run.id,),
        ).fetchone()[0] == 0

    review = commands.read_model(run.id).mission_review
    assert review is not None and review.status == "pending"
    assert review.checkpoint_id == execution["id"]

    approval = commands.read_model(run.id).approval
    assert approval is not None
    assert approval.type == "MISSION_APPROVAL"
    assert approval.checkpoint_id == execution["id"]
    assert approval.actions == ["approve", "revise", "stop"]

    with open_checkpointer(checkpoint_path(facts.path)) as saver:
        graph = build_graph(worker.runner, checkpointer=saver)
        snapshot = graph.get_state(thread_config(run.id))
    assert snapshot.interrupts
    assert snapshot.interrupts[0].value["type"] == "MISSION_APPROVAL"
    assert snapshot.interrupts[0].value["actions"] == ["approve", "revise", "stop"]

    commands.accept(
        run.id, "MISSION_REVIEW", approve_payload(review), "approve-1",
    )
    assert worker.run_once()
    resumed = facts.get_run(run.id)
    assert resumed.stages[1].status == "succeeded"
    assert resumed.blueprint is not None


def test_pre_upgrade_checkpoint_without_approval_action_resumes(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run = make_run(facts)
    worker = Worker(facts.path, provider=FakeProvider(), owner="worker-a")
    assert worker.run_once()
    commands = worker.execution

    review = commands.read_model(run.id).mission_review
    assert review is not None

    # A checkpoint written by a version before approval_action existed has no
    # such key in its persisted state. Resuming must re-execute the Gate, which
    # writes approval_action again and routes to the expected next node.
    with facts.connect() as connection:
        execution = connection.execute(
            "SELECT id, waiting_state_json FROM node_executions "
            "WHERE run_id=? AND node='mission_gate' AND status='WAITING' "
            "ORDER BY rowid DESC LIMIT 1",
            (run.id,),
        ).fetchone()
        legacy_state = json.loads(execution["waiting_state_json"])
        legacy_state.pop("approval_action")
        connection.execute(
            "UPDATE node_executions SET waiting_state_json=? WHERE id=?",
            (json.dumps(legacy_state), execution["id"]),
        )
        persisted = connection.execute(
            "SELECT waiting_state_json FROM node_executions WHERE id=?",
            (execution["id"],),
        ).fetchone()
    assert "approval_action" not in json.loads(persisted["waiting_state_json"])

    commands.accept(
        run.id, "MISSION_REVIEW", approve_payload(review), "approve-legacy-state",
    )
    assert worker.run_once()

    resumed = facts.get_run(run.id)
    assert resumed.stages[1].status == "succeeded"
    assert resumed.blueprint is not None
    with facts.connect() as connection:
        after = connection.execute(
            "SELECT after_state_json FROM node_executions "
            "WHERE run_id=? AND node='mission_gate' AND id=?",
            (run.id, execution["id"]),
        ).fetchone()
    assert after["after_state_json"] is not None
    assert json.loads(after["after_state_json"])["approval_action"] == "approve"


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
