from langgraph.checkpoint.memory import MemorySaver

from app.v0.graph import build_graph
from app.v0.langgraph_checkpoint import (
    checkpoint_path,
    latest_checkpoint,
    open_checkpointer,
    thread_config,
)
from app.v0.provider import FakeProvider
from app.v0.runner import V0Runner
from app.v0.schemas import CourseInput
from app.v0.storage import FactStore
from app.v0.worker import Worker


def make_run(facts: FactStore, key: str):
    run, _ = facts.create_run(
        CourseInput(
            topic="变量", audience="初学者", goal="解释变量", language="zh",
            expected_chapters=1, min_effective_chars=1,
        ),
        key,
        enqueue_start=True,
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0, source_evidence_version=0 "
            "WHERE id=?", (run.id,),
        )
    return run


def test_worker_dual_writes_checkpoint_by_thread_id(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run = make_run(facts, "langgraph-dual-write")
    worker = Worker(facts.path, provider=FakeProvider(), owner="worker-a")
    assert worker.run_once()

    checkpoint = latest_checkpoint(checkpoint_path(facts.path), run.id)
    assert checkpoint is not None
    assert checkpoint.config["configurable"]["thread_id"] == run.id
    values = checkpoint.checkpoint["channel_values"]
    assert values["run_id"] == run.id
    assert values["current_node"]
    assert worker.execution.last_checkpoint(run.id) is not None


def test_langgraph_threads_are_isolated_between_runs(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    first = make_run(facts, "langgraph-run-a")
    second = make_run(facts, "langgraph-run-b")
    first_worker = Worker(facts.path, provider=FakeProvider(), owner="worker-a")
    second_worker = Worker(facts.path, provider=FakeProvider(), owner="worker-b")
    assert first_worker.run_once()
    assert second_worker.run_once()

    path = checkpoint_path(facts.path)
    first_checkpoint = latest_checkpoint(path, first.id)
    second_checkpoint = latest_checkpoint(path, second.id)
    assert first_checkpoint is not None
    assert second_checkpoint is not None
    assert first_checkpoint.config["configurable"]["thread_id"] == first.id
    assert second_checkpoint.config["configurable"]["thread_id"] == second.id
    assert first_checkpoint.checkpoint["channel_values"]["run_id"] == first.id
    assert second_checkpoint.checkpoint["channel_values"]["run_id"] == second.id


def test_memory_checkpointer_can_be_injected_for_tests(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run = make_run(facts, "langgraph-memory")
    saver = MemorySaver()
    runner = V0Runner(
        FakeProvider(), store=facts, langgraph_checkpointer=saver,
    )
    runner.execute(run.id)

    checkpoint = saver.get_tuple(thread_config(run.id))
    assert checkpoint is not None
    assert checkpoint.checkpoint["channel_values"]["run_id"] == run.id


def test_langgraph_can_read_the_written_graph_state(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run = make_run(facts, "langgraph-read")
    worker = Worker(facts.path, provider=FakeProvider(), owner="worker-a")
    assert worker.run_once()

    with open_checkpointer(checkpoint_path(facts.path)) as saver:
        graph = build_graph(worker.runner, checkpointer=saver)
        snapshot = graph.get_state(thread_config(run.id))
    assert snapshot.values["run_id"] == run.id
    assert snapshot.values["current_node"]
