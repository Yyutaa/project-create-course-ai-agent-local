import asyncio

from fastapi.testclient import TestClient

from app.api.run_routes import get_runner
from app.main import app
from app.v0.execution import ExecutionStore
from app.v0.provider import FakeProvider
from app.v0.runner import V0Runner
from app.v0.schemas import CourseInput
from app.v0.storage import FactStore


def test_change_cursor_tracks_execution_writes_and_rolls_back(tmp_path):
    store = FactStore(tmp_path / "facts.sqlite3")
    store.migrate()
    run, _ = store.create_run(
        CourseInput(topic="Python", audience="初学者", goal="完成练习", language="zh"),
        "start",
    )
    initial = store.change_seq(run.id)

    command = ExecutionStore(store.path).accept(run.id, "STOP", {}, "stop")
    assert command.status == "ACCEPTED"
    assert store.change_seq(run.id) > initial

    after_command = store.change_seq(run.id)
    with store.connect() as connection:
        connection.execute("UPDATE runs SET status='stopped' WHERE id=?", (run.id,))
    assert store.change_seq(run.id) > after_command

    before_rollback = store.change_seq(run.id)
    try:
        with store.connect() as connection:
            connection.execute(
                "UPDATE commands SET status='CLAIMED' WHERE id=?", (command.id,)
            )
            raise RuntimeError("rollback")
    except RuntimeError:
        pass
    assert store.change_seq(run.id) == before_rollback


def test_stream_emits_current_cursor_then_committed_change(tmp_path):
    from app.api.stream_routes import watch_run

    store = FactStore(tmp_path / "facts.sqlite3")
    store.migrate()
    run, _ = store.create_run(
        CourseInput(topic="Python", audience="初学者", goal="完成练习", language="zh"),
        "start",
    )

    async def observe():
        stream = watch_run(store, run.id, interval=0)
        first = await anext(stream)
        ExecutionStore(store.path).accept(run.id, "STOP", {}, "stop")
        second = await anext(stream)
        await stream.aclose()
        return first, second

    first, second = asyncio.run(observe())
    assert first.event == second.event == "run.changed"
    assert int(second.id) > int(first.id)
    assert second.data == {"run_id": run.id, "revision": int(second.id)}


def test_stream_keeps_idle_connection_alive_without_exposing_data(tmp_path):
    from app.api.stream_routes import watch_run

    store = FactStore(tmp_path / "facts.sqlite3")
    store.migrate()
    run, _ = store.create_run(
        CourseInput(topic="Python", audience="初学者", goal="完成练习", language="zh"),
        "start",
    )

    async def observe():
        stream = watch_run(store, run.id, interval=0)
        await anext(stream)
        heartbeat = await asyncio.wait_for(anext(stream), timeout=0.2)
        await stream.aclose()
        return heartbeat

    heartbeat = asyncio.run(observe())
    assert heartbeat.comment == "keepalive"
    assert heartbeat.data is None


def test_v10_database_migrates_to_stream_cursor(tmp_path):
    store = FactStore(tmp_path / "facts.sqlite3")
    store.migrate()
    run, _ = store.create_run(
        CourseInput(topic="Python", audience="初学者", goal="完成练习", language="zh"),
        "start",
    )
    with store.connect() as connection:
        triggers = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE '%_stream_%'"
        ).fetchall()
        for trigger in triggers:
            connection.execute(f"DROP TRIGGER {trigger[0]}")
        connection.execute("DROP TABLE run_change_seq")
        connection.execute("PRAGMA user_version=10")

    store.migrate()
    assert store.schema_version() == 19
    before = store.change_seq(run.id)
    ExecutionStore(store.path).accept(run.id, "STOP", {}, "stop")
    assert store.change_seq(run.id) > before


def test_stream_endpoint_rejects_unknown_run(tmp_path):
    runner = V0Runner(FakeProvider(), store=FactStore(tmp_path / "facts.sqlite3"))
    app.dependency_overrides[get_runner] = lambda: runner
    try:
        with TestClient(app) as client:
            response = client.get("/api/v0/runs/missing/stream")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
