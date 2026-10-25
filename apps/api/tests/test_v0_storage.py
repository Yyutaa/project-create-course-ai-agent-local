import sqlite3

import pytest

from app.v0 import storage
from app.v0.schemas import ArtifactRef, BlueprintDraft, BlueprintLesson, MissionDraft
from app.v0.workspace import Workspace


def test_migration_is_repeatable_and_preserves_rows(tmp_path):
    store = storage.FactStore(tmp_path / "facts.sqlite3")
    store.migrate()
    with store.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id, title, workspace_key, created_at) VALUES (?, ?, ?, ?)",
            ("c1", "第一门课", "c1", "2026-09-22T00:00:00Z"),
        )
    store.migrate()
    assert store.schema_version() == 15
    with store.connect() as connection:
        assert (
            connection.execute("SELECT title FROM courses WHERE id='c1'").fetchone()[0]
            == "第一门课"
        )


def test_v14_migration_preserves_existing_runs_and_versions_new_runs(tmp_path):
    path = tmp_path / "facts.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE runs (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO runs(id) VALUES ('old-run')")
        connection.execute("PRAGMA user_version=13")

    store = storage.FactStore(path)
    store.migrate()
    store.migrate()

    assert store.schema_version() == 15
    with store.connect() as connection:
        assert connection.execute(
            "SELECT context_contract_version FROM runs WHERE id='old-run'"
        ).fetchone()[0] == 0


def test_new_run_context_contract_version_survives_snapshot_rebuild(tmp_path):
    store = storage.FactStore(tmp_path / "facts.sqlite3")
    store.migrate()
    run, _ = store.create_run(
        storage.CourseInput(
            topic="Vue", audience="初学者", goal="理解 state", language="zh",
            source_policy="仅允许使用公开官方资料",
        ),
        "new-context-contract",
    )
    assert run.context_contract_version == 1
    with store.connect() as connection:
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run.id,))
    assert store.get_run(run.id).context_contract_version == 1


def test_new_runs_require_official_policy_without_writing_partial_facts(tmp_path):
    store = storage.FactStore(tmp_path / "facts.sqlite3")
    store.migrate()
    course = storage.CourseInput(
        topic="Vue state", audience="初学者", goal="理解 state", language="zh",
        source_policy="仅限使用内部提供材料",
    )

    with pytest.raises(ValueError, match="仅允许使用公开官方资料"):
        store.create_run(course, "internal-policy", enqueue_start=True)

    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0


def test_new_run_source_evidence_version_survives_snapshot_rebuild(tmp_path):
    store = storage.FactStore(tmp_path / "facts.sqlite3")
    store.migrate()
    run, _ = store.create_run(
        storage.CourseInput(
            topic="Vue", audience="初学者", goal="理解 state", language="zh",
            source_policy="仅允许使用公开官方资料",
        ),
        "official-policy",
    )
    with store.connect() as connection:
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run.id,))

    assert store.get_run(run.id).source_evidence_version == 1


def test_v7_migration_preserves_legacy_run_without_enabling_constraints(tmp_path):
    path = tmp_path / "facts.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE runs (id TEXT PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE intakes (run_id TEXT PRIMARY KEY, topic TEXT NOT NULL, "
            "audience TEXT NOT NULL, goal TEXT NOT NULL, language TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO runs VALUES ('legacy-run')")
        connection.execute(
            "INSERT INTO intakes VALUES "
            "('legacy-run', 'Python', '初学者', '完成练习', 'zh')"
        )
        connection.execute("PRAGMA user_version=7")

    store = storage.FactStore(path)
    store.migrate()
    store.migrate()

    assert store.schema_version() == 15
    with store.connect() as connection:
        run = connection.execute(
            "SELECT constraints_version FROM runs WHERE id='legacy-run'"
        ).fetchone()
        intake = connection.execute(
            "SELECT expected_chapters, min_effective_chars, token_limit "
            "FROM intakes WHERE run_id='legacy-run'"
        ).fetchone()
    assert run[0] == 0
    with store.connect() as connection:
        assert connection.execute(
            "SELECT source_evidence_version FROM runs WHERE id='legacy-run'"
        ).fetchone()[0] == 0
    assert tuple(intake) == (12, 12_000, None)


def test_new_run_constraints_survive_snapshot_rebuild_and_affect_idempotency(tmp_path):
    store = storage.FactStore(tmp_path / "facts.sqlite3")
    store.migrate()
    course = storage.CourseInput(
        topic="React",
        audience="初学者",
        goal="完成页面",
        language="zh",
        source_policy="仅允许使用公开官方资料",
        expected_chapters=8,
        min_effective_chars=6_000,
        token_limit=50_000,
    )
    run, _ = store.create_run(course, "constraint-run")
    replay, created = store.create_run(course, "constraint-run")

    assert not created
    assert replay.id == run.id
    with pytest.raises(ValueError, match="Idempotency-Key"):
        store.create_run(
            course.model_copy(update={"expected_chapters": 9}),
            "constraint-run",
        )
    with pytest.raises(ValueError, match="Idempotency-Key"):
        store.create_run(
            course.model_copy(update={"source_policy": "仅限使用内部提供材料"}),
            "constraint-run",
        )

    with store.connect() as connection:
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run.id,))
    rebuilt = store.get_run(run.id)

    assert rebuilt.constraints_version == 1
    assert rebuilt.course_input.expected_chapters == 8
    assert rebuilt.course_input.min_effective_chars == 6_000
    assert rebuilt.course_input.token_limit == 50_000
    assert rebuilt.course_input.source_policy == "仅允许使用公开官方资料"
    assert rebuilt.source_evidence_version == 1


def test_foreign_keys_and_transaction_rollback(tmp_path):
    store = storage.FactStore(tmp_path / "facts.sqlite3")
    store.migrate()
    with pytest.raises(sqlite3.IntegrityError):
        with store.connect() as connection:
            connection.execute(
                "INSERT INTO runs(id, course_id, status, idempotency_key, request_hash, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("r1", "missing", "running", "k1", "hash", "now", "now"),
            )
    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_workspace_rejects_symlink_escape(tmp_path):
    root = tmp_path / "workspaces"
    course = root / "c1"
    course.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (course / "runs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="越界"):
        Workspace(root).write_lesson("c1", "r1", 1, "# 课程")
    assert list(outside.iterdir()) == []


def test_migration_upgrades_v1_artifacts_without_inventing_provenance(tmp_path):
    path = tmp_path / "facts.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE artifacts (artifact_id TEXT NOT NULL, version INTEGER NOT NULL, "
            "run_id TEXT NOT NULL, kind TEXT NOT NULL, content_json TEXT NOT NULL, "
            "content_hash TEXT NOT NULL, workspace_relpath TEXT, created_at TEXT NOT NULL, "
            "PRIMARY KEY(artifact_id, version), UNIQUE(run_id, kind, version))"
        )
        connection.execute("PRAGMA user_version=1")

    store = storage.FactStore(path)
    store.migrate()

    assert store.schema_version() == 15
    with store.connect() as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(artifacts)").fetchall()
        }
        assert {"producer_role", "source_refs_json"} <= columns


def test_artifact_producer_and_source_refs_survive_snapshot_rebuild(tmp_path):
    store = storage.FactStore(tmp_path / "facts.sqlite3")
    store.migrate()
    course = storage.CourseInput(
        topic="React",
        audience="初学者",
        goal="完成页面",
        language="zh",
    )
    run, _ = store.create_run(course, "start-provenance")
    run.stages[1].status = "succeeded"
    mission = MissionDraft(
        audience="初学者",
        learning_goal="完成页面",
        scope="React 基础",
        stop_conditions=["目标冲突时停止"],
    )
    run.mission = mission
    run = store.record(
        run,
        "stage.succeeded",
        "mission",
        mission,
        producer_role="mission",
        source_refs=[],
    )
    mission_summary = run.artifacts[-1]
    mission_ref = ArtifactRef(
        run_id=run.id,
        artifact_id=mission_summary.artifact_id,
        version=mission_summary.version,
        kind=mission_summary.kind,
        content_hash=mission_summary.content_hash,
    )
    run.stages[2].status = "succeeded"
    blueprint = BlueprintDraft(
        lessons=[
            BlueprintLesson(
                title="第一课",
                learning_goal="完成页面",
                evidence="页面可运行",
            )
        ]
    )
    run.blueprint = blueprint
    run = store.record(
        run,
        "stage.succeeded",
        "blueprint",
        blueprint,
        producer_role="blueprint",
        source_refs=[mission_ref],
    )
    blueprint_summary = run.artifacts[-1]

    with store.connect() as connection:
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run.id,))
    rebuilt = store.get_run(run.id)
    rebuilt_blueprint = next(item for item in rebuilt.artifacts if item.kind == "blueprint")
    detail = store.get_artifact(blueprint_summary.artifact_id, blueprint_summary.version)

    assert rebuilt_blueprint.producer_role == "blueprint"
    assert rebuilt_blueprint.source_refs == [mission_ref]
    assert detail.producer_role == "blueprint"
    assert detail.source_refs == [mission_ref]


def test_v2_database_upgrades_to_execution_protocol_without_recreating_runs(tmp_path):
    path = tmp_path / "facts.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE runs (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO runs VALUES ('existing-run')")
        connection.execute("PRAGMA user_version=2")

    store = storage.FactStore(path)
    store.migrate()
    store.migrate()

    with store.connect() as connection:
        assert store.schema_version() == 15
        assert connection.execute("SELECT id FROM runs").fetchone()[0] == "existing-run"
        assert connection.execute(
            "SELECT mission_review_required FROM runs WHERE id='existing-run'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='commands'"
        ).fetchone()[0] == "commands"


def test_v15_migration_adds_node_input_columns_and_preserves_rows(tmp_path):
    path = tmp_path / "facts.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE node_executions (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, "
            "node TEXT NOT NULL, attempt INTEGER NOT NULL, lease_epoch INTEGER NOT NULL, "
            "status TEXT NOT NULL, before_checkpoint_id TEXT, after_checkpoint_id TEXT, "
            "error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO node_executions VALUES "
            "('old', 'run-1', 'mission', 1, 1, 'COMMITTED', NULL, NULL, NULL, "
            "'now', 'now')"
        )
        connection.execute("PRAGMA user_version=14")

    store = storage.FactStore(path)
    store.migrate()
    store.migrate()

    assert store.schema_version() == 15
    with store.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(node_executions)")
        }
        row = connection.execute(
            "SELECT input_hash, failure_class FROM node_executions WHERE id='old'"
        ).fetchone()
        index = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' "
            "AND name='node_executions_by_input'"
        ).fetchone()
    assert {"input_hash", "failure_class"} <= columns
    assert row["input_hash"] is None
    assert row["failure_class"] is None
    assert index is not None
