"""Lease-fenced source and tool facts; network calls remain outside SQLite locks."""

from datetime import datetime, timezone
from hashlib import sha256
import json
import sqlite3
from urllib.parse import urlsplit
from uuid import uuid4

from app.v0.budget import BudgetExceeded
from app.v0.source_tools import TOOL_MANIFESTS, canonical_public_url
from app.v0.storage import FactStore


SEARCH_LIMIT = 20
FETCH_LIMIT = 40
_CALL_LIMITS = {
    "course.source.search": SEARCH_LIMIT,
    "course.source.fetch": FETCH_LIMIT,
}


class ToolBudgetExceeded(BudgetExceeded):
    code = "source_tool_budget_exhausted"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _require_lease(
    connection: sqlite3.Connection, run_id: str, owner: str, epoch: int,
) -> None:
    valid = connection.execute(
        "SELECT 1 FROM run_leases WHERE run_id=? AND owner=? AND epoch=? "
        "AND expires_at>?", (run_id, owner, epoch, _now()),
    ).fetchone()
    if valid is None:
        raise PermissionError("lease 已失效，禁止提交来源事实")


class SourceFacts:
    def __init__(self, facts: FactStore):
        self.facts = facts

    def retry_round(self, run_id: str) -> int:
        with self.facts.connect() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM source_decisions "
                "WHERE run_id=? AND action='retry_search'", (run_id,),
            ).fetchone()[0]

    def begin_call(
        self, run_id: str, tool_id: str, arguments: dict,
        owner: str, epoch: int, node_execution_id: str | None,
        command_id: str | None,
    ) -> tuple[str, dict | None]:
        manifest = TOOL_MANIFESTS.get(tool_id)
        if manifest is None:
            raise ValueError("未知来源工具")
        args_hash = _hash(arguments)
        now = _now()
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_lease(connection, run_id, owner, epoch)
            if manifest.idempotent:
                previous = connection.execute(
                    "SELECT id, result_json FROM tool_invocations "
                    "WHERE run_id=? AND tool_id=? AND args_hash=? "
                    "AND status='SUCCEEDED' ORDER BY created_at DESC LIMIT 1",
                    (run_id, tool_id, args_hash),
                ).fetchone()
                if previous is not None:
                    return previous["id"], json.loads(previous["result_json"])
            used = connection.execute(
                "SELECT COUNT(*) FROM tool_invocations WHERE run_id=? AND tool_id=?",
                (run_id, tool_id),
            ).fetchone()[0]
            if used >= _CALL_LIMITS[tool_id]:
                raise ToolBudgetExceeded("来源工具调用预算耗尽")
            call_id = uuid4().hex
            connection.execute(
                "INSERT INTO tool_invocations "
                "(id, run_id, node_execution_id, command_id, tool_id, args_hash, "
                "status, lease_epoch, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'STARTED', ?, ?, ?)",
                (call_id, run_id, node_execution_id, command_id, tool_id,
                 args_hash, epoch, now, now),
            )
            return call_id, None

    def finish_call(
        self, call_id: str, owner: str, epoch: int, result: dict,
    ) -> None:
        result_json = _json(result)
        if len(result_json.encode("utf-8")) > 128 * 1024:
            raise ValueError("来源工具结果超出上限")
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            call = connection.execute(
                "SELECT run_id, status FROM tool_invocations WHERE id=?", (call_id,),
            ).fetchone()
            if call is None:
                raise KeyError(call_id)
            _require_lease(connection, call["run_id"], owner, epoch)
            if call["status"] != "STARTED":
                raise ValueError("来源工具调用已结束")
            connection.execute(
                "UPDATE tool_invocations SET status='SUCCEEDED', result_json=?, "
                "updated_at=? WHERE id=?",
                (result_json, _now(), call_id),
            )

    def finish_search(
        self, call_id: str, owner: str, epoch: int, results: list[dict],
    ) -> dict:
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            call = connection.execute(
                "SELECT run_id, tool_id, status FROM tool_invocations WHERE id=?",
                (call_id,),
            ).fetchone()
            if call is None or call["tool_id"] != "course.source.search":
                raise ValueError("不是来源检索调用")
            _require_lease(connection, call["run_id"], owner, epoch)
            if call["status"] != "STARTED":
                raise ValueError("来源检索调用已结束")
            candidates = []
            for item in results[:5]:
                try:
                    url = canonical_public_url(str(item["url"]))
                except (KeyError, ValueError):
                    continue
                candidate_id = sha256(
                    f"{call['run_id']}:{url}".encode("utf-8")
                ).hexdigest()[:32]
                title = str(item.get("title") or "")[:200]
                connection.execute(
                    "INSERT OR IGNORE INTO source_candidates "
                    "(id, run_id, search_call_id, url, title, status, "
                    "metadata_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?, 'candidate', ?, ?)",
                    (candidate_id, call["run_id"], call_id, url, title,
                     _hash(item), _now()),
                )
                candidates.append({
                    "candidate_id": candidate_id, "url": url, "title": title,
                })
            result = {"candidates": candidates}
            connection.execute(
                "UPDATE tool_invocations SET status='SUCCEEDED', result_json=?, "
                "updated_at=? WHERE id=?",
                (_json(result), _now(), call_id),
            )
            return result

    def get_candidate(self, run_id: str, candidate_id: str) -> dict:
        with self.facts.connect() as connection:
            row = connection.execute(
                "SELECT id, run_id, url, title, status, metadata_hash "
                "FROM source_candidates WHERE id=? AND run_id=?",
                (candidate_id, run_id),
            ).fetchone()
            if row is None:
                raise KeyError(candidate_id)
            return dict(row)

    def list_candidates(self, run_id: str) -> list[dict]:
        with self.facts.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT id, url, title, status, metadata_hash, created_at "
                "FROM source_candidates WHERE run_id=? ORDER BY created_at, id",
                (run_id,),
            ).fetchall()]

    def approved_identity(self, run_id: str, candidate_id: str) -> dict | None:
        with self.facts.connect() as connection:
            row = connection.execute(
                "SELECT d.id, c.url FROM source_candidates AS c "
                "JOIN source_decisions AS d ON d.candidate_id=c.id "
                "WHERE c.run_id=? AND c.id=? AND c.status='human_approved' "
                "AND d.action='approve' ORDER BY d.created_at DESC LIMIT 1",
                (run_id, candidate_id),
            ).fetchone()
            if row is None:
                return None
            return {"human_decision_id": row["id"], "official_host": (
                row["url"].split("/", 3)[2]
            )}

    def mark_needs_human(
        self, run_id: str, candidate_id: str, owner: str, epoch: int,
    ) -> None:
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_lease(connection, run_id, owner, epoch)
            connection.execute(
                "UPDATE source_candidates SET status='needs_human' "
                "WHERE run_id=? AND id=? AND status='candidate'",
                (run_id, candidate_id),
            )

    def finish_fetch(
        self, call_id: str, owner: str, epoch: int, candidate_id: str,
        title: str, content: str, identity: dict,
    ) -> dict:
        if not identity or len(content.encode("utf-8")) > 64 * 1024 or not content:
            raise ValueError("来源页面缺少身份凭据或超出上限")
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            call = connection.execute(
                "SELECT run_id, tool_id, status FROM tool_invocations WHERE id=?",
                (call_id,),
            ).fetchone()
            if call is None or call["tool_id"] != "course.source.fetch":
                raise ValueError("不是来源抓取调用")
            _require_lease(connection, call["run_id"], owner, epoch)
            if call["status"] != "STARTED":
                raise ValueError("来源抓取调用已结束")
            candidate = connection.execute(
                "SELECT url FROM source_candidates WHERE id=? AND run_id=?",
                (candidate_id, call["run_id"]),
            ).fetchone()
            if candidate is None:
                raise KeyError(candidate_id)
            if identity.get("official_host") != urlsplit(candidate["url"]).hostname:
                raise ValueError("来源身份与候选主机不一致")
            content_hash = sha256(content.encode("utf-8")).hexdigest()
            version = connection.execute(
                "SELECT COALESCE(MAX(version), 0)+1 FROM source_documents "
                "WHERE candidate_id=?", (candidate_id,),
            ).fetchone()[0]
            document_id = uuid4().hex
            connection.execute(
                "INSERT INTO source_documents "
                "(id, run_id, candidate_id, version, url, title, content, "
                "content_hash, identity_json, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'eligible', ?)",
                (document_id, call["run_id"], candidate_id, version,
                 candidate["url"], title[:200], content, content_hash,
                 _json(identity), _now()),
            )
            connection.execute(
                "UPDATE source_candidates SET status='eligible' WHERE id=?",
                (candidate_id,),
            )
            result = {
                "document_id": document_id,
                "url": candidate["url"],
                "title": title[:200],
                "content_hash": content_hash,
                "excerpt": content[:4000],
            }
            connection.execute(
                "UPDATE tool_invocations SET status='SUCCEEDED', result_json=?, "
                "updated_at=? WHERE id=?",
                (_json(result), _now(), call_id),
            )
            return result

    def list_documents(self, run_id: str) -> list[dict]:
        with self.facts.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT id, candidate_id, version, url, title, content, "
                "content_hash, identity_json, status, created_at "
                "FROM source_documents WHERE run_id=? ORDER BY created_at, id",
                (run_id,),
            ).fetchall()]

    def summary_pack(self, run_id: str) -> list[dict]:
        latest = {}
        for document in self.list_documents(run_id):
            if document["status"] == "eligible":
                latest[document["candidate_id"]] = document
        return [
            {
                "document_id": document["id"],
                "url": document["url"],
                "title": document["title"].strip() or document["url"][:200],
                "excerpt": document["content"][:1500],
                "content_hash": document["content_hash"],
            }
            for document in list(latest.values())[-3:]
        ]

    def record_claim_link(
        self, reference, line_number: int, claim_excerpt: str,
        document: dict | None, supporting_excerpt: str | None,
        status: str, owner: str, epoch: int,
    ) -> None:
        claim_hash = sha256(claim_excerpt.encode("utf-8")).hexdigest()
        excerpt_hash = (
            sha256(supporting_excerpt.encode("utf-8")).hexdigest()
            if supporting_excerpt else None
        )
        document_id = document["id"] if document else None
        record_id = sha256(
            f"{reference.artifact_id}:{reference.version}:{line_number}:"
            f"{claim_hash}:{document_id}:{status}".encode("utf-8")
        ).hexdigest()[:32]
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_lease(connection, reference.run_id, owner, epoch)
            connection.execute(
                "INSERT OR IGNORE INTO source_claim_links "
                "(id, run_id, lesson_artifact_id, lesson_version, lesson_hash, "
                "line_number, claim_hash, document_id, document_hash, "
                "excerpt_hash, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record_id, reference.run_id, reference.artifact_id,
                 reference.version, reference.content_hash, line_number,
                 claim_hash, document_id,
                 document["content_hash"] if document else None,
                 excerpt_hash, status, _now()),
            )

    def fail_call(
        self, call_id: str, owner: str, epoch: int, error_code: str,
    ) -> None:
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            call = connection.execute(
                "SELECT run_id, status FROM tool_invocations WHERE id=?", (call_id,),
            ).fetchone()
            if call is None:
                raise KeyError(call_id)
            _require_lease(connection, call["run_id"], owner, epoch)
            if call["status"] != "STARTED":
                return
            connection.execute(
                "UPDATE tool_invocations SET status='FAILED', error_code=?, "
                "updated_at=? WHERE id=?",
                (error_code[:80], _now(), call_id),
            )
