"""SQLite facts for the seven-stage V0 workflow."""

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Iterator
from uuid import uuid4

from pydantic import BaseModel

from app.v0.schemas import (
    ArtifactRecord,
    ArtifactRef,
    ArtifactSummary,
    CourseRecord,
    CourseProgress,
    CourseChapter,
    CourseInput,
    DEFAULT_SOURCE_POLICY,
    GraphState,
    Publication,
    ReleaseDecision,
    RunContent,
    SnapshotRecord,
    V0Run,
)
from app.v0.workspace import Workspace


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


def command_hash(kind: str, payload: dict) -> str:
    return sha256(f"{kind}:{_json(payload)}".encode("utf-8")).hexdigest()


class FactStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.workspace = Workspace(self.path.parent / "workspaces")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def schema_version(self) -> int:
        with self.connect() as connection:
            return connection.execute("PRAGMA user_version").fetchone()[0]

    def change_seq(self, run_id: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT seq FROM run_change_seq WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            return row[0]

    def migrate(self) -> None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version >= 17:
                return
            if version == 16:
                self._migrate_v17(connection)
                return
            if version == 15:
                self._migrate_v16(connection)
                self._migrate_v17(connection)
                return
            if version == 14:
                self._migrate_v15(connection)
                self._migrate_v16(connection)
                self._migrate_v17(connection)
                return
            if version == 13:
                self._migrate_v14(connection)
                self._migrate_v15(connection)
                self._migrate_v16(connection)
                self._migrate_v17(connection)
                return
            if version == 12:
                self._migrate_v13(connection)
                self._migrate_v14(connection)
                self._migrate_v15(connection)
                self._migrate_v16(connection)
                self._migrate_v17(connection)
                return
            if version == 11:
                self._migrate_v12(connection)
                self._migrate_v13(connection)
                self._migrate_v14(connection)
                self._migrate_v15(connection)
                self._migrate_v16(connection)
                self._migrate_v17(connection)
                return
            if version == 10:
                self._migrate_v11(connection)
                self._migrate_v12(connection)
                self._migrate_v13(connection)
                self._migrate_v14(connection)
                self._migrate_v15(connection)
                self._migrate_v16(connection)
                self._migrate_v17(connection)
                return
            if version == 9:
                self._migrate_v10(connection)
                self._migrate_v11(connection)
                self._migrate_v12(connection)
                self._migrate_v13(connection)
                self._migrate_v14(connection)
                self._migrate_v15(connection)
                self._migrate_v16(connection)
                self._migrate_v17(connection)
                return
            if version == 8:
                self._migrate_v9(connection)
                self._migrate_v10(connection)
                self._migrate_v11(connection)
                self._migrate_v12(connection)
                self._migrate_v13(connection)
                self._migrate_v14(connection)
                self._migrate_v15(connection)
                self._migrate_v16(connection)
                self._migrate_v17(connection)
                return
            if version == 7:
                self._migrate_v8(connection)
                self._migrate_v9(connection)
                self._migrate_v10(connection)
                self._migrate_v11(connection)
                self._migrate_v12(connection)
                self._migrate_v13(connection)
                self._migrate_v14(connection)
                self._migrate_v15(connection)
                self._migrate_v16(connection)
                self._migrate_v17(connection)
                return
            if version == 6:
                self._migrate_v7(connection)
                self._migrate_v8(connection)
                self._migrate_v9(connection)
                self._migrate_v10(connection)
                self._migrate_v11(connection)
                self._migrate_v12(connection)
                self._migrate_v13(connection)
                self._migrate_v14(connection)
                self._migrate_v15(connection)
                self._migrate_v16(connection)
                self._migrate_v17(connection)
                return
            if version == 5:
                self._migrate_v6(connection)
                self._migrate_v7(connection)
                self._migrate_v8(connection)
                self._migrate_v9(connection)
                self._migrate_v10(connection)
                self._migrate_v11(connection)
                self._migrate_v12(connection)
                self._migrate_v13(connection)
                self._migrate_v14(connection)
                self._migrate_v15(connection)
                self._migrate_v16(connection)
                self._migrate_v17(connection)
                return
            if version == 4:
                self._migrate_v5(connection)
                self._migrate_v6(connection)
                self._migrate_v7(connection)
                self._migrate_v8(connection)
                self._migrate_v9(connection)
                self._migrate_v10(connection)
                self._migrate_v11(connection)
                self._migrate_v12(connection)
                self._migrate_v13(connection)
                self._migrate_v14(connection)
                self._migrate_v15(connection)
                self._migrate_v16(connection)
                self._migrate_v17(connection)
                return
            if version == 3:
                self._migrate_v4(connection)
                self._migrate_v5(connection)
                self._migrate_v6(connection)
                self._migrate_v7(connection)
                self._migrate_v8(connection)
                self._migrate_v9(connection)
                self._migrate_v10(connection)
                self._migrate_v11(connection)
                self._migrate_v12(connection)
                self._migrate_v13(connection)
                self._migrate_v14(connection)
                self._migrate_v15(connection)
                self._migrate_v16(connection)
                self._migrate_v17(connection)
                return
            if version == 0:
                connection.execute(
                    "CREATE TABLE courses (id TEXT PRIMARY KEY, title TEXT NOT NULL, "
                    "workspace_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE runs (id TEXT PRIMARY KEY, course_id TEXT NOT NULL "
                    "REFERENCES courses(id), status TEXT NOT NULL, "
                    "idempotency_key TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL, "
                    "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE INDEX runs_by_course ON runs(course_id, created_at)"
                )
                connection.execute(
                    "CREATE TABLE intakes (run_id TEXT PRIMARY KEY REFERENCES runs(id), "
                    "topic TEXT NOT NULL, audience TEXT NOT NULL, goal TEXT NOT NULL, "
                    "language TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE artifacts (artifact_id TEXT NOT NULL, version INTEGER "
                    "NOT NULL CHECK(version > 0), run_id TEXT NOT NULL REFERENCES runs(id), "
                    "kind TEXT NOT NULL, content_json TEXT NOT NULL, "
                    "content_hash TEXT NOT NULL, workspace_relpath TEXT, "
                    "created_at TEXT NOT NULL, producer_role TEXT, "
                    "source_refs_json TEXT NOT NULL DEFAULT '[]', "
                    "PRIMARY KEY(artifact_id, version), UNIQUE(run_id, kind, version))"
                )
                connection.execute(
                    "CREATE INDEX artifacts_by_run ON artifacts(run_id, kind, version)"
                )
                connection.execute(
                    "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "run_id TEXT NOT NULL REFERENCES runs(id), stage TEXT, type TEXT NOT NULL, "
                    "status TEXT, input_summary TEXT, output_summary TEXT, "
                    "failure_reason TEXT, artifact_id TEXT, artifact_version INTEGER, "
                    "release_action TEXT, release_reason TEXT, request_key TEXT, "
                    "request_hash TEXT, created_at TEXT NOT NULL, "
                    "UNIQUE(run_id, request_key))"
                )
                connection.execute("CREATE INDEX events_by_run ON events(run_id, id)")
                connection.execute(
                    "CREATE TABLE snapshots (run_id TEXT PRIMARY KEY REFERENCES runs(id), "
                    "revision INTEGER NOT NULL, projection_json TEXT NOT NULL, "
                    "updated_at TEXT NOT NULL)"
                )
            elif version == 1:
                connection.execute("ALTER TABLE artifacts ADD COLUMN producer_role TEXT")
                connection.execute(
                    "ALTER TABLE artifacts ADD COLUMN source_refs_json "
                    "TEXT NOT NULL DEFAULT '[]'"
                )
            connection.execute(
                "CREATE TABLE commands (id TEXT PRIMARY KEY, run_id TEXT NOT NULL "
                "REFERENCES runs(id), kind TEXT NOT NULL, payload_json TEXT NOT NULL, "
                "payload_hash TEXT NOT NULL, idempotency_key TEXT NOT NULL, "
                "status TEXT NOT NULL, claimed_by TEXT, claimed_until TEXT, "
                "error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
                "UNIQUE(run_id, idempotency_key))"
            )
            connection.execute(
                "CREATE INDEX commands_ready ON commands(status, created_at)"
            )
            connection.execute(
                "CREATE TABLE run_leases (run_id TEXT PRIMARY KEY REFERENCES runs(id), "
                "owner TEXT NOT NULL, epoch INTEGER NOT NULL, expires_at TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE node_executions (id TEXT PRIMARY KEY, run_id TEXT NOT NULL "
                "REFERENCES runs(id), node TEXT NOT NULL, attempt INTEGER NOT NULL, "
                "lease_epoch INTEGER NOT NULL, status TEXT NOT NULL, "
                "before_checkpoint_id TEXT, after_checkpoint_id TEXT, "
                "error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE checkpoints (id TEXT PRIMARY KEY, run_id TEXT NOT NULL "
                "REFERENCES runs(id), node_execution_id TEXT, position TEXT NOT NULL, "
                "state_json TEXT NOT NULL, event_id INTEGER, created_at TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX checkpoints_by_run ON checkpoints(run_id, created_at)"
            )
            connection.execute(
                "CREATE TABLE run_controls (run_id TEXT PRIMARY KEY REFERENCES runs(id), "
                "stop_requested INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL "
                "DEFAULT 0, human_input_json TEXT)"
            )
            self._migrate_v4(connection)
            self._migrate_v5(connection)
            self._migrate_v6(connection)
            self._migrate_v7(connection)
            self._migrate_v8(connection)
            self._migrate_v9(connection)
            self._migrate_v10(connection)
            self._migrate_v11(connection)
            self._migrate_v12(connection)
            self._migrate_v13(connection)
            self._migrate_v14(connection)
            self._migrate_v15(connection)
            self._migrate_v16(connection)
            self._migrate_v17(connection)

    @staticmethod
    def _migrate_v4(connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE node_executions ADD COLUMN command_id TEXT")
        connection.execute(
            "CREATE TABLE provider_calls (id TEXT PRIMARY KEY, run_id TEXT NOT NULL "
            "REFERENCES runs(id), command_id TEXT, node_execution_id TEXT, "
            "role TEXT NOT NULL, status TEXT NOT NULL, duration_ms INTEGER, "
            "input_tokens INTEGER, output_tokens INTEGER, started_at TEXT NOT NULL, "
            "finished_at TEXT)"
        )
        connection.execute(
            "CREATE INDEX provider_calls_by_run ON provider_calls(run_id, started_at)"
        )
        connection.execute(
            "CREATE TABLE budget_limits (run_id TEXT PRIMARY KEY REFERENCES runs(id), "
            "provider_limit INTEGER NOT NULL DEFAULT 60, approved_by_command TEXT)"
        )
        connection.execute("PRAGMA user_version=4")

    @staticmethod
    def _migrate_v5(connection: sqlite3.Connection) -> None:
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
        ).fetchone():
            connection.execute(
                "ALTER TABLE runs ADD COLUMN mission_review_required "
                "INTEGER NOT NULL DEFAULT 0"
            )
        connection.execute(
            "CREATE TABLE mission_reviews (id TEXT PRIMARY KEY, run_id TEXT NOT NULL "
            "REFERENCES runs(id), command_id TEXT NOT NULL UNIQUE "
            "REFERENCES commands(id), artifact_id TEXT NOT NULL, "
            "artifact_version INTEGER NOT NULL, content_hash TEXT NOT NULL, "
            "checkpoint_id TEXT NOT NULL, action TEXT NOT NULL "
            "CHECK(action IN ('approve', 'revise')), feedback TEXT, "
            "created_at TEXT NOT NULL, "
            "UNIQUE(run_id, artifact_id, artifact_version))"
        )
        connection.execute("PRAGMA user_version=5")

    @staticmethod
    def _migrate_v6(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE local_llm_config (id INTEGER PRIMARY KEY CHECK(id=1), "
            "provider TEXT NOT NULL CHECK(provider='deepseek'), "
            "model TEXT NOT NULL CHECK(model IN "
            "('deepseek-flash', 'deepseek-v4-pro')), "
            "state TEXT NOT NULL CHECK(state IN ('ready', 'repair')))"
        )
        connection.execute("PRAGMA user_version=6")

    @staticmethod
    def _migrate_v7(connection: sqlite3.Connection) -> None:
        connection.execute(
            "ALTER TABLE local_llm_config ADD COLUMN operation_token TEXT"
        )
        connection.execute("PRAGMA user_version=7")

    @staticmethod
    def _migrate_v8(connection: sqlite3.Connection) -> None:
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
        ).fetchone():
            run_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(runs)")
            }
            if "constraints_version" not in run_columns:
                connection.execute(
                    "ALTER TABLE runs ADD COLUMN constraints_version "
                    "INTEGER NOT NULL DEFAULT 0 CHECK(constraints_version IN (0, 1))"
                )
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='intakes'"
        ).fetchone():
            intake_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(intakes)")
            }
            if "expected_chapters" not in intake_columns:
                connection.execute(
                    "ALTER TABLE intakes ADD COLUMN expected_chapters "
                    "INTEGER NOT NULL DEFAULT 12 "
                    "CHECK(expected_chapters BETWEEN 1 AND 100)"
                )
            if "min_effective_chars" not in intake_columns:
                connection.execute(
                    "ALTER TABLE intakes ADD COLUMN min_effective_chars "
                    "INTEGER NOT NULL DEFAULT 12000 CHECK(min_effective_chars > 0)"
                )
            if "token_limit" not in intake_columns:
                connection.execute(
                    "ALTER TABLE intakes ADD COLUMN token_limit "
                    "INTEGER CHECK(token_limit IS NULL OR token_limit > 0)"
                )
        connection.execute("PRAGMA user_version=8")

    @staticmethod
    def _migrate_v9(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS publications (run_id TEXT PRIMARY KEY "
            "REFERENCES runs(id), course_id TEXT NOT NULL, slug TEXT NOT NULL UNIQUE, "
            "href TEXT NOT NULL, published_at TEXT NOT NULL, "
            "catalog_entry_json TEXT NOT NULL)"
        )
        connection.execute("PRAGMA user_version=9")

    @staticmethod
    def _migrate_v10(connection: sqlite3.Connection) -> None:
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='intakes'"
        ).fetchone():
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(intakes)")
            }
            if "source_policy" not in columns:
                connection.execute(
                    "ALTER TABLE intakes ADD COLUMN source_policy TEXT NOT NULL "
                    "DEFAULT '允许使用用户资料与公开官方资料'"
                )
        connection.execute("PRAGMA user_version=10")

    @staticmethod
    def _migrate_v11(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS run_change_seq "
            "(run_id TEXT PRIMARY KEY REFERENCES runs(id), "
            "seq INTEGER NOT NULL DEFAULT 0)"
        )
        has_runs = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
        ).fetchone()
        if has_runs:
            connection.execute(
                "INSERT OR IGNORE INTO run_change_seq SELECT id, 0 FROM runs"
            )
            for operation in ("INSERT", "UPDATE"):
                connection.execute(
                    f"CREATE TRIGGER IF NOT EXISTS runs_stream_{operation.lower()} "
                    f"AFTER {operation} ON runs BEGIN "
                    "INSERT INTO run_change_seq(run_id, seq) VALUES (NEW.id, 1) "
                    "ON CONFLICT(run_id) DO UPDATE SET seq=seq+1; END"
                )
        for table in (
            "events", "snapshots", "artifacts", "commands", "node_executions",
            "checkpoints", "run_controls", "provider_calls", "budget_limits",
            "publications",
        ):
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists or not has_runs:
                continue
            for operation, row in (("INSERT", "NEW"), ("UPDATE", "NEW"),
                                   ("DELETE", "OLD")):
                connection.execute(
                    f"CREATE TRIGGER IF NOT EXISTS {table}_stream_{operation.lower()} "
                    f"AFTER {operation} ON {table} BEGIN "
                    "INSERT INTO run_change_seq(run_id, seq) "
                    f"VALUES ({row}.run_id, 1) "
                    "ON CONFLICT(run_id) DO UPDATE SET seq=seq+1; END"
                )
        connection.execute("PRAGMA user_version=11")

    @staticmethod
    def _migrate_v12(connection: sqlite3.Connection) -> None:
        has_runs = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
        ).fetchone()
        if has_runs:
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(runs)")
            }
            if "source_evidence_version" not in columns:
                connection.execute(
                    "ALTER TABLE runs ADD COLUMN source_evidence_version "
                    "INTEGER NOT NULL DEFAULT 0 "
                    "CHECK(source_evidence_version IN (0, 1))"
                )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS tool_invocations ("
            "id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), "
            "node_execution_id TEXT, command_id TEXT, tool_id TEXT NOT NULL, "
            "args_hash TEXT NOT NULL, status TEXT NOT NULL, result_json TEXT, "
            "error_code TEXT, lease_epoch INTEGER NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS tool_calls_by_run "
            "ON tool_invocations(run_id, tool_id, args_hash, status)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS source_candidates ("
            "id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), "
            "search_call_id TEXT REFERENCES tool_invocations(id), "
            "url TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, "
            "metadata_hash TEXT NOT NULL, created_at TEXT NOT NULL, "
            "UNIQUE(run_id, url))"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS source_documents ("
            "id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), "
            "candidate_id TEXT NOT NULL REFERENCES source_candidates(id), "
            "version INTEGER NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL, "
            "content TEXT NOT NULL, content_hash TEXT NOT NULL, "
            "identity_json TEXT NOT NULL, status TEXT NOT NULL, "
            "created_at TEXT NOT NULL, UNIQUE(candidate_id, version))"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS source_claim_links ("
            "id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), "
            "lesson_artifact_id TEXT NOT NULL, lesson_version INTEGER NOT NULL, "
            "lesson_hash TEXT NOT NULL, line_number INTEGER NOT NULL, "
            "claim_hash TEXT NOT NULL, document_id TEXT REFERENCES source_documents(id), "
            "document_hash TEXT, excerpt_hash TEXT, status TEXT NOT NULL, "
            "created_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS source_decisions ("
            "id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), "
            "candidate_id TEXT REFERENCES source_candidates(id), "
            "checkpoint_id TEXT NOT NULL, action TEXT NOT NULL, "
            "reason TEXT NOT NULL, command_id TEXT NOT NULL UNIQUE, "
            "created_at TEXT NOT NULL)"
        )
        if has_runs:
            for table in (
                "tool_invocations", "source_candidates", "source_documents",
                "source_claim_links", "source_decisions",
            ):
                for operation, row in (
                    ("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD"),
                ):
                    connection.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_stream_{operation.lower()} "
                        f"AFTER {operation} ON {table} BEGIN "
                        "INSERT INTO run_change_seq(run_id, seq) "
                        f"VALUES ({row}.run_id, 1) "
                        "ON CONFLICT(run_id) DO UPDATE SET seq=seq+1; END"
                    )
        connection.execute("PRAGMA user_version=12")

    @staticmethod
    def _migrate_v13(connection: sqlite3.Connection) -> None:
        has_runs = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
        ).fetchone()
        if has_runs and "planning_loop_version" not in {
            row["name"] for row in connection.execute("PRAGMA table_info(runs)")
        }:
            connection.execute(
                "ALTER TABLE runs ADD COLUMN planning_loop_version "
                "INTEGER NOT NULL DEFAULT 0 CHECK(planning_loop_version IN (0, 1))"
            )
        connection.execute("PRAGMA user_version=13")

    @staticmethod
    def _migrate_v14(connection: sqlite3.Connection) -> None:
        has_runs = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
        ).fetchone()
        if has_runs and "context_contract_version" not in {
            row["name"] for row in connection.execute("PRAGMA table_info(runs)")
        }:
            connection.execute(
                "ALTER TABLE runs ADD COLUMN context_contract_version "
                "INTEGER NOT NULL DEFAULT 0 CHECK(context_contract_version IN (0, 1))"
            )
        connection.execute("PRAGMA user_version=14")

    @staticmethod
    def _migrate_v15(connection: sqlite3.Connection) -> None:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='node_executions'"
        ).fetchone()
        if exists:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(node_executions)")
            }
            if "input_hash" not in columns:
                connection.execute(
                    "ALTER TABLE node_executions ADD COLUMN input_hash TEXT"
                )
            if "failure_class" not in columns:
                connection.execute(
                    "ALTER TABLE node_executions ADD COLUMN failure_class TEXT"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS node_executions_by_input "
                "ON node_executions(run_id, node, input_hash)"
            )
        connection.execute("PRAGMA user_version=15")

    @staticmethod
    def _migrate_v16(connection: sqlite3.Connection) -> None:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
        ).fetchone()
        if exists:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(runs)")
            }
            if "langgraph_flow_version" not in columns:
                connection.execute(
                    "ALTER TABLE runs ADD COLUMN langgraph_flow_version "
                    "INTEGER NOT NULL DEFAULT 0 "
                    "CHECK(langgraph_flow_version IN (0, 1))"
                )
        connection.execute("PRAGMA user_version=16")

    @staticmethod
    def _migrate_v17(connection: sqlite3.Connection) -> None:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='node_executions'"
        ).fetchone()
        if exists:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(node_executions)")
            }
            if "pending_interrupt_id" not in columns:
                connection.execute(
                    "ALTER TABLE node_executions ADD COLUMN pending_interrupt_id TEXT"
                )
        connection.execute("PRAGMA user_version=17")

    def mission_review_required(self, run_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT mission_review_required FROM runs WHERE id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            return bool(row[0])

    def create_run(
        self, course_input: CourseInput, request_key: str, *, enqueue_start: bool = False
    ) -> tuple[V0Run, bool]:
        request_hash = _hash(course_input.model_dump())
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT id, request_hash FROM runs WHERE idempotency_key=?", (request_key,)
            ).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise ValueError("Idempotency-Key 已用于不同课程输入")
                return self._get_run(connection, existing["id"]), False

            if course_input.source_policy != DEFAULT_SOURCE_POLICY:
                raise ValueError(f"新建课程仅允许使用来源政策：{DEFAULT_SOURCE_POLICY}")

            course_id, run_id, now = uuid4().hex, uuid4().hex, _now()
            workspace = self.workspace.course_dir(course_id)
            workspace.mkdir(parents=True, exist_ok=False)
            run = V0Run(
                id=run_id,
                course_id=course_id,
                course_input=course_input,
                constraints_version=1,
                source_evidence_version=1,
                planning_loop_version=1,
                context_contract_version=1,
                langgraph_flow_version=1,
            )
            try:
                connection.execute(
                    "INSERT INTO courses VALUES (?, ?, ?, ?)",
                    (course_id, course_input.topic, course_id, now),
                )
                connection.execute(
                    "INSERT INTO runs(id, course_id, status, idempotency_key, "
                    "request_hash, created_at, updated_at, mission_review_required, "
                    "constraints_version, source_evidence_version, planning_loop_version, "
                    "context_contract_version, langgraph_flow_version) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, 1, 1, 1, 1)",
                    (run_id, course_id, "running", request_key, request_hash, now, now),
                )
                connection.execute(
                    "INSERT INTO intakes(run_id, topic, audience, goal, language, "
                    "source_policy, expected_chapters, min_effective_chars, token_limit) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        course_input.topic,
                        course_input.audience,
                        course_input.goal,
                        course_input.language,
                        course_input.source_policy,
                        course_input.expected_chapters,
                        course_input.min_effective_chars,
                        course_input.token_limit,
                    ),
                )
                event_id = connection.execute(
                    "INSERT INTO events(run_id, type, status, created_at) "
                    "VALUES (?, 'run.accepted', 'running', ?)",
                    (run_id, now),
                ).lastrowid
                run.revision = event_id
                connection.execute(
                    "INSERT INTO snapshots VALUES (?, ?, ?, ?)",
                    (run_id, event_id, run.model_dump_json(), now),
                )
                if enqueue_start:
                    connection.execute(
                        "INSERT INTO commands(id, run_id, kind, payload_json, "
                        "payload_hash, idempotency_key, status, created_at, updated_at) "
                        "VALUES (?, ?, 'START', '{}', ?, ?, 'ACCEPTED', ?, ?)",
                        (uuid4().hex, run_id, command_hash("START", {}),
                         request_key, now, now),
                    )
                    connection.execute(
                        "INSERT INTO run_controls(run_id) VALUES (?)", (run_id,)
                    )
                    connection.execute(
                        "INSERT INTO checkpoints VALUES (?, ?, NULL, 'before_node', "
                        "?, NULL, ?)",
                        (uuid4().hex, run_id, GraphState(run_id=run_id).model_dump_json(), now),
                    )
            except Exception:
                workspace.rmdir()
                raise
            return run, True

    def get_run(self, run_id: str) -> V0Run:
        with self.connect() as connection:
            return self._get_run(connection, run_id)

    def list_run_events(self, run_id: str, limit: int = 40) -> list[dict]:
        with self.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM runs WHERE id=?", (run_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(run_id)
            rows = connection.execute(
                "SELECT id, type, stage, created_at FROM events WHERE run_id=? "
                "ORDER BY id DESC LIMIT ?", (run_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def _get_run(self, connection: sqlite3.Connection, run_id: str) -> V0Run:
        current = connection.execute(
            "SELECT revision, projection_json FROM snapshots WHERE run_id=?", (run_id,)
        ).fetchone()
        latest = connection.execute(
            "SELECT MAX(id) FROM events WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        if latest is None:
            raise KeyError(run_id)
        if current and current["revision"] == latest:
            return V0Run.model_validate_json(current["projection_json"])
        run = self._rebuild(connection, run_id)
        connection.execute(
            "INSERT INTO snapshots VALUES (?, ?, ?, ?) ON CONFLICT(run_id) DO UPDATE "
            "SET revision=excluded.revision, projection_json=excluded.projection_json, "
            "updated_at=excluded.updated_at",
            (run_id, run.revision, run.model_dump_json(), _now()),
        )
        return run

    def _rebuild(self, connection: sqlite3.Connection, run_id: str) -> V0Run:
        row = connection.execute(
            "SELECT runs.course_id, runs.constraints_version, "
            "runs.source_evidence_version, runs.planning_loop_version, "
            "runs.context_contract_version, runs.langgraph_flow_version, "
            "intakes.topic, "
            "intakes.audience, intakes.goal, intakes.language, intakes.source_policy, "
            "intakes.expected_chapters, intakes.min_effective_chars, "
            "intakes.token_limit FROM runs JOIN intakes ON intakes.run_id=runs.id "
            "WHERE runs.id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        course = CourseInput(
            **{
                field: row[field]
                for field in (
                    "topic",
                    "audience",
                    "goal",
                    "language",
                    "source_policy",
                    "expected_chapters",
                    "min_effective_chars",
                    "token_limit",
                )
            }
        )
        run = V0Run(
            id=run_id,
            course_id=row["course_id"],
            course_input=course,
            constraints_version=row["constraints_version"],
            source_evidence_version=row["source_evidence_version"],
            planning_loop_version=row["planning_loop_version"],
            context_contract_version=row["context_contract_version"],
            langgraph_flow_version=row["langgraph_flow_version"],
        )
        events = connection.execute(
            "SELECT * FROM events WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
        for event in events:
            stage = next((item for item in run.stages if item.name == event["stage"]), None)
            kind = event["type"]
            if kind == "stage.started" and stage:
                stage.status = "running"
                stage.input_summary = event["input_summary"] or ""
            elif kind in ("stage.succeeded", "stage.failed") and stage:
                stage.status = "succeeded" if kind == "stage.succeeded" else "failed"
                stage.output_summary = event["output_summary"] or ""
                stage.failure_reason = event["failure_reason"]
                if kind == "stage.failed":
                    run.status = "failed"
                if event["artifact_id"]:
                    self._apply_event_artifact(connection, run, event)
            elif kind == "artifact.created" and event["artifact_id"]:
                self._apply_event_artifact(connection, run, event)
            elif kind == "candidate.created" and event["artifact_id"]:
                self._apply_event_artifact(connection, run, event, activate=False)
            elif kind in (
                "candidate.accepted", "candidate.human_accepted"
            ) and event["artifact_id"]:
                self._apply_event_artifact(connection, run, event, append=False)
            elif kind == "stage.waiting" and stage:
                run.status = "waiting_for_human"
                stage.status = "waiting_for_human"
                stage.failure_reason = event["failure_reason"]
                if event["artifact_id"]:
                    self._apply_event_artifact(connection, run, event)
            elif kind == "release.waiting":
                run.status = "waiting_for_human"
                run.stages[-1].status = "waiting_for_human"
                run.stages[-1].input_summary = event["input_summary"] or ""
            elif kind == "release.decided":
                run.release_decision = ReleaseDecision(
                    action=event["release_action"], reason=event["release_reason"]
                )
                run.status = (
                    "ready_for_release"
                    if event["release_action"] == "prepare"
                    else "stopped"
                )
                run.stages[-1].status = (
                    "succeeded" if event["release_action"] == "prepare" else "stopped"
                )
                run.stages[-1].output_summary = event["output_summary"] or ""
            elif kind == "release.published":
                run.status = "published"
                run.stages[-1].status = "succeeded"
                run.stages[-1].output_summary = event["output_summary"] or ""
                run.publication = self._publication(connection, run_id)
            elif kind == "run.interrupted":
                run.status = "failed"
                active = next(
                    (item for item in run.stages if item.name == event["stage"]), None
                )
                if active:
                    active.status = "failed"
                    active.failure_reason = event["failure_reason"]
            elif kind == "budget.token_exhausted":
                run.status = "stopped"
                if stage:
                    stage.status = "stopped"
                    stage.failure_reason = event["failure_reason"]
            elif kind == "run.stopped":
                run.status = "stopped"
                if stage:
                    stage.status = "stopped"
                    stage.failure_reason = event["failure_reason"]
            elif kind == "run.resumed":
                run.status = "running"
                if stage:
                    stage.status = "pending"
                    stage.failure_reason = None
            elif kind in ("mission.approved", "mission.revision_requested"):
                run.status = "running"
                run.stages[1].status = (
                    "succeeded" if kind == "mission.approved" else "pending"
                )
                run.stages[1].failure_reason = None
            elif kind in ("quality.risk_accepted", "quality.retry_requested"):
                run.status = "running"
                run.stages[5].status = "pending"
                run.stages[5].failure_reason = None
            elif kind in ("source.approve", "source.reject") and stage:
                run.status = "running"
                stage.status = "pending"
                stage.failure_reason = None
            run.revision = event["id"]
        return run

    @staticmethod
    def _publication(connection: sqlite3.Connection, run_id: str) -> Publication | None:
        row = connection.execute(
            "SELECT slug, href, published_at FROM publications WHERE run_id=?",
            (run_id,),
        ).fetchone()
        return (
            Publication(
                slug=row["slug"], href=row["href"], published_at=row["published_at"]
            )
            if row
            else None
        )

    def latest_mission_review(self, run_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM mission_reviews WHERE run_id=? ORDER BY rowid DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            return dict(row) if row else None

    def _apply_event_artifact(
        self,
        connection: sqlite3.Connection,
        run: V0Run,
        event: sqlite3.Row,
        *,
        activate: bool = True,
        append: bool = True,
    ) -> None:
        artifact = connection.execute(
            "SELECT kind, content_json, content_hash, producer_role, source_refs_json "
            "FROM artifacts WHERE artifact_id=? AND version=?",
            (event["artifact_id"], event["artifact_version"]),
        ).fetchone()
        if artifact is None:
            raise RuntimeError("Event 引用的 Artifact 缺失")
        if activate:
            attribute = "lesson" if artifact["kind"] == "lesson" else artifact["kind"]
            model_field = V0Run.model_fields[attribute]
            from pydantic import TypeAdapter

            setattr(
                run,
                attribute,
                TypeAdapter(model_field.annotation).validate_python(
                    json.loads(artifact["content_json"])
                ),
            )
        if append:
            run.artifacts.append(
                ArtifactSummary(
                    artifact_id=event["artifact_id"],
                    version=event["artifact_version"],
                    kind=artifact["kind"],
                    content_hash=artifact["content_hash"],
                    producer_role=artifact["producer_role"],
                    source_refs=self._source_refs(artifact["source_refs_json"]),
                )
            )

    def record(
        self,
        run: V0Run,
        event_type: str,
        stage: str | None = None,
        artifact: BaseModel | None = None,
        request_key: str | None = None,
        request_hash: str | None = None,
        failure_reason: str | None = None,
        producer_role: str | None = None,
        source_refs: list[ArtifactRef] | tuple[ArtifactRef, ...] | None = None,
        artifact_kind: str | None = None,
        accepted_ref: ArtifactRef | None = None,
        lease_owner: str | None = None,
        lease_epoch: int | None = None,
        node_execution_id: str | None = None,
        checkpoint_state: GraphState | None = None,
        clear_stop: bool = False,
    ) -> V0Run:
        relative_path = None
        artifact_id = accepted_ref.artifact_id if accepted_ref else None
        version = accepted_ref.version if accepted_ref else None
        content_json = None
        content_hash = None
        source_refs = list(source_refs or [])
        kind = artifact_kind or ("lesson" if stage == "generation" else stage)
        if artifact is not None:
            content = artifact.model_dump()
            content_json = _json(content)
            content_hash = _hash(content)
        now = _now()
        try:
            with self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                if lease_owner is not None:
                    lease = connection.execute(
                        "SELECT 1 FROM run_leases WHERE run_id=? AND owner=? "
                        "AND epoch=? AND expires_at>?",
                        (run.id, lease_owner, lease_epoch, now),
                    ).fetchone()
                    if lease is None:
                        raise PermissionError("lease 已失效，禁止提交")
                if clear_stop:
                    connection.execute(
                        "UPDATE run_controls SET stop_requested=0, revision=revision+1 "
                        "WHERE run_id=?", (run.id,),
                    )
                if artifact is not None:
                    existing = connection.execute(
                        "SELECT artifact_id, MAX(version) AS version FROM artifacts "
                        "WHERE run_id=? AND kind=?", (run.id, kind),
                    ).fetchone()
                    artifact_id = existing["artifact_id"] or uuid4().hex
                    version = (existing["version"] or 0) + 1
                    if kind == "lesson":
                        try:
                            relative_path = self.workspace.write_lesson(
                                run.course_id, run.id, version, content["markdown"]
                            )
                        except FileExistsError:
                            # SQLite has no row for this next version: a prior
                            # process died after the derived file was written.
                            orphan = (
                                f"{run.course_id}/runs/{run.id}/lesson-v{version}.md"
                            )
                            self.workspace.remove_new_file(orphan)
                            relative_path = self.workspace.write_lesson(
                                run.course_id, run.id, version, content["markdown"]
                            )
                    connection.execute(
                        "INSERT INTO artifacts(artifact_id, version, run_id, kind, "
                        "content_json, content_hash, workspace_relpath, created_at, "
                        "producer_role, source_refs_json) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            artifact_id,
                            version,
                            run.id,
                            kind,
                            content_json,
                            content_hash,
                            relative_path,
                            now,
                            producer_role,
                            _json([item.model_dump() for item in source_refs]),
                        ),
                    )
                    run.artifacts.append(
                        ArtifactSummary(
                            artifact_id=artifact_id,
                            version=version,
                            kind=kind,
                            content_hash=content_hash,
                            producer_role=producer_role,
                            source_refs=source_refs,
                        )
                    )
                stage_record = next(
                    (item for item in run.stages if item.name == stage), None
                )
                event_id = connection.execute(
                    "INSERT INTO events(run_id, stage, type, status, input_summary, "
                    "output_summary, failure_reason, artifact_id, artifact_version, "
                    "release_action, release_reason, request_key, request_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run.id,
                        stage,
                        event_type,
                        stage_record.status if stage_record else run.status,
                        stage_record.input_summary if stage_record else None,
                        stage_record.output_summary if stage_record else None,
                        stage_record.failure_reason if stage_record else failure_reason,
                        artifact_id,
                        version,
                        run.release_decision.action
                        if event_type == "release.decided"
                        else None,
                        run.release_decision.reason
                        if event_type == "release.decided"
                        else None,
                        request_key,
                        request_hash,
                        now,
                    ),
                ).lastrowid
                run.revision = event_id
                if (
                    event_type == "stage.waiting"
                    and stage_record is not None
                    and stage_record.failure_reason == "返工预算耗尽，需要人工处理"
                ):
                    already = connection.execute(
                        "SELECT 1 FROM events WHERE run_id=? AND "
                        "type='budget.repair_exhausted' LIMIT 1", (run.id,),
                    ).fetchone()
                    if not already:
                        run.revision = connection.execute(
                            "INSERT INTO events(run_id, stage, type, created_at) "
                            "VALUES (?, ?, 'budget.repair_exhausted', ?)",
                            (run.id, stage, now),
                        ).lastrowid
                connection.execute(
                    "UPDATE runs SET status=?, updated_at=? WHERE id=?",
                    (run.status, now, run.id),
                )
                connection.execute(
                    "UPDATE snapshots SET revision=?, projection_json=?, updated_at=? "
                    "WHERE run_id=?",
                    (run.revision, run.model_dump_json(), now, run.id),
                )
                if node_execution_id and checkpoint_state:
                    refs = dict(checkpoint_state.artifact_refs)
                    if artifact is not None:
                        key = "candidate" if event_type == "candidate.created" else (
                            f"lesson:{content.get('lesson_id')}"
                            if kind == "lesson" and content.get("lesson_id")
                            else kind
                        )
                        refs[key] = ArtifactRef(
                            run_id=run.id, artifact_id=artifact_id,
                            version=version, kind=kind, content_hash=content_hash,
                        )
                    checkpoint = checkpoint_state.model_copy(
                        update={"artifact_refs": refs}
                    )
                    connection.execute(
                        "INSERT INTO checkpoints VALUES (?, ?, ?, 'after_artifact', "
                        "?, ?, ?)",
                        (uuid4().hex, run.id, node_execution_id,
                         checkpoint.model_dump_json(), event_id, now),
                    )
        except Exception:
            if relative_path:
                self.workspace.remove_new_file(relative_path)
            raise
        return run

    def release_replay(
        self, run_id: str, key: str, decision: ReleaseDecision
    ) -> V0Run | None:
        with self.connect() as connection:
            event = connection.execute(
                "SELECT request_hash FROM events WHERE run_id=? AND request_key=?",
                (run_id, key),
            ).fetchone()
            if event is None:
                return None
            if event["request_hash"] != _hash(decision.model_dump()):
                raise ValueError("Idempotency-Key 已用于不同 release 决定")
            return self._get_run(connection, run_id)

    def decision_hash(self, decision: ReleaseDecision) -> str:
        return _hash(decision.model_dump())

    def publication_replay(self, run_id: str, key: str) -> V0Run | None:
        with self.connect() as connection:
            event = connection.execute(
                "SELECT request_hash FROM events WHERE run_id=? AND request_key=? "
                "AND type='release.published'",
                (run_id, key),
            ).fetchone()
            if event is None:
                return None
            if event["request_hash"] != command_hash("PUBLISH", {}):
                raise ValueError("Idempotency-Key 已用于其他发布请求")
            return self._get_run(connection, run_id)

    def publication_for_run(self, run_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM publications WHERE run_id=?", (run_id,)
            ).fetchone()
            return dict(row) if row else None

    def publication_slug_exists(self, slug: str) -> bool:
        with self.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM publications WHERE slug=?", (slug,)
            ).fetchone() is not None

    def record_publication(
        self,
        run: V0Run,
        *,
        slug: str,
        href: str,
        entry: dict,
        request_key: str,
        request_hash: str,
    ) -> V0Run:
        now = _now()
        run.status = "published"
        run.stages[-1].status = "succeeded"
        run.stages[-1].output_summary = f"已发布课程：{slug}"
        run.publication = Publication(slug=slug, href=href, published_at=now)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO publications(run_id, course_id, slug, href, "
                "published_at, catalog_entry_json) VALUES (?, ?, ?, ?, ?, ?)",
                (run.id, run.course_id, slug, href, now, _json(entry)),
            )
            run.revision = connection.execute(
                "INSERT INTO events(run_id, stage, type, status, output_summary, "
                "request_key, request_hash, created_at) "
                "VALUES (?, 'release', 'release.published', 'published', ?, ?, ?, ?)",
                (
                    run.id,
                    run.stages[-1].output_summary,
                    request_key,
                    request_hash,
                    now,
                ),
            ).lastrowid
            connection.execute(
                "UPDATE runs SET status=?, updated_at=? WHERE id=?",
                (run.status, now, run.id),
            )
            connection.execute(
                "UPDATE snapshots SET revision=?, projection_json=?, updated_at=? "
                "WHERE run_id=?",
                (run.revision, run.model_dump_json(), now, run.id),
            )
        return run

    def list_courses(self) -> list[CourseProgress]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT courses.id, courses.title, courses.workspace_key, "
                "runs.id AS run_id FROM courses JOIN runs ON runs.id = ("
                "SELECT id FROM runs AS latest WHERE latest.course_id=courses.id "
                "ORDER BY created_at DESC, id DESC LIMIT 1) "
                "WHERE runs.id NOT IN (SELECT run_id FROM publications) "
                "ORDER BY courses.created_at DESC, courses.id"
            ).fetchall()
            courses = []
            for row in rows:
                run = self._get_run(connection, row["run_id"])
                stage = next(
                    (stage for stage in run.stages if stage.status != "succeeded"),
                    run.stages[-1],
                )
                courses.append(CourseProgress(
                    **dict(row), current_stage=stage.name, stage_status=stage.status
                ))
            return courses

    def get_course(self, course_id: str) -> CourseRecord:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, title, workspace_key FROM courses WHERE id=?", (course_id,)
            ).fetchone()
            if row is None:
                raise KeyError(course_id)
            return CourseRecord(**dict(row))

    def get_run_content(self, run_id: str) -> RunContent:
        with self.connect() as connection:
            run = self._get_run(connection, run_id)
            if run.blueprint is None:
                return RunContent(run_id=run_id, title=run.course_input.topic, chapters=[])
            rows = connection.execute(
                "SELECT artifacts.version, artifacts.content_json FROM events "
                "JOIN artifacts ON artifacts.artifact_id=events.artifact_id "
                "AND artifacts.version=events.artifact_version "
                "WHERE events.run_id=? AND artifacts.kind='lesson' "
                "AND events.type IN ('artifact.created', 'candidate.accepted', "
                "'candidate.human_accepted') "
                "ORDER BY events.id",
                (run_id,),
            ).fetchall()
            accepted = {}
            for row in rows:
                lesson = json.loads(row["content_json"])
                key = lesson.get("lesson_id") or lesson.get("title")
                if key:
                    accepted[key] = (lesson["markdown"], row["version"])
            chapters = []
            for lesson in run.blueprint.lessons:
                content = accepted.get(lesson.lesson_id or lesson.title)
                chapters.append(CourseChapter(
                    lesson_id=lesson.lesson_id, title=lesson.title,
                    status="generated" if content else "pending",
                    markdown=content[0] if content else None,
                    version=content[1] if content else None,
                ))
            return RunContent(
                run_id=run_id, title=run.course_input.topic, chapters=chapters
            )

    def list_artifacts(self, run_id: str) -> list[ArtifactSummary]:
        self.get_run(run_id)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT artifact_id, version, kind, content_hash, producer_role, "
                "source_refs_json FROM artifacts "
                "WHERE run_id=? ORDER BY created_at, rowid",
                (run_id,),
            ).fetchall()
            return [
                ArtifactSummary(
                    artifact_id=row["artifact_id"],
                    version=row["version"],
                    kind=row["kind"],
                    content_hash=row["content_hash"],
                    producer_role=row["producer_role"],
                    source_refs=self._source_refs(row["source_refs_json"]),
                )
                for row in rows
            ]

    def get_artifact(self, artifact_id: str, version: int) -> ArtifactRecord:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id=? AND version=?",
                (artifact_id, version),
            ).fetchone()
            if row is None:
                raise KeyError(artifact_id)
            return ArtifactRecord(
                artifact_id=row["artifact_id"],
                version=row["version"],
                run_id=row["run_id"],
                kind=row["kind"],
                content=json.loads(row["content_json"]),
                content_hash=row["content_hash"],
                producer_role=row["producer_role"],
                source_refs=self._source_refs(row["source_refs_json"]),
                workspace_relpath=row["workspace_relpath"],
            )

    def has_artifact_event(self, run_id: str, event_type: str, ref: ArtifactRef) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM events JOIN artifacts "
                "ON artifacts.artifact_id=events.artifact_id "
                "AND artifacts.version=events.artifact_version "
                "WHERE events.run_id=? AND events.type=? "
                "AND artifacts.run_id=? AND artifacts.artifact_id=? "
                "AND artifacts.version=? AND artifacts.kind=? "
                "AND artifacts.content_hash=? LIMIT 1",
                (
                    run_id,
                    event_type,
                    ref.run_id,
                    ref.artifact_id,
                    ref.version,
                    ref.kind,
                    ref.content_hash,
                ),
            ).fetchone()
        return row is not None

    @staticmethod
    def _source_refs(value: str) -> list[ArtifactRef]:
        return [ArtifactRef.model_validate(item) for item in json.loads(value)]

    def get_snapshot(self, run_id: str) -> SnapshotRecord:
        run = self.get_run(run_id)
        return SnapshotRecord(run_id=run_id, revision=run.revision, run=run)
