"""Durable Provider-call reservations; unknown crash outcomes count conservatively."""

from datetime import datetime, timezone
import json
from pathlib import Path
from time import monotonic
from uuid import uuid4

from pydantic import BaseModel

from app.v0.provider import AgentRequest, AgentResponse, Provider, ProviderError
from app.v0.storage import FactStore

DEFAULT_CALL_LIMIT = 60
WARNING_CALLS = 48


def warning_threshold(limit: int) -> int:
    return (limit * 4 + 4) // 5


class BudgetExceeded(ProviderError):
    code = "provider_budget_exceeded"


class TokenLimitReached(RuntimeError):
    def __init__(self, used: int, limit: int, next_node: str):
        super().__init__("token_limit_reached")
        self.used = used
        self.limit = limit
        self.next_node = next_node


class BudgetSummary(BaseModel):
    used: int
    limit: int
    warning_at: int
    warning: bool
    requires_human: bool
    unknown: int
    repair_used: int
    repair_limit: int
    repair_exhausted: bool
    tokens_used: int
    token_limit: int | None
    token_usage_unknown: int
    token_exhausted: bool


class BudgetStore:
    def __init__(self, path: Path):
        self.facts = FactStore(path)
        self.facts.migrate()

    @staticmethod
    def _event(connection, run_id: str, kind: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        event_id = connection.execute(
            "INSERT INTO events(run_id, type, created_at) VALUES (?, ?, ?)",
            (run_id, kind, now),
        ).lastrowid
        row = connection.execute(
            "SELECT projection_json FROM snapshots WHERE run_id=?", (run_id,)
        ).fetchone()
        if row:
            projection = json.loads(row["projection_json"])
            projection["revision"] = event_id
            connection.execute(
                "UPDATE snapshots SET revision=?, projection_json=?, updated_at=? "
                "WHERE run_id=?",
                (event_id, json.dumps(projection, ensure_ascii=False), now, run_id),
            )

    def reserve(
        self, run_id: str, role: str, owner: str, epoch: int,
        command_id: str | None, node_execution_id: str | None,
    ) -> str:
        now = datetime.now(timezone.utc).isoformat()
        exhausted = False
        call_id = ""
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            lease = connection.execute(
                "SELECT 1 FROM run_leases WHERE run_id=? AND owner=? AND epoch=? "
                "AND expires_at>?", (run_id, owner, epoch, now),
            ).fetchone()
            if lease is None:
                raise PermissionError("lease 已失效，禁止 Provider 调用")
            limit = connection.execute(
                "SELECT provider_limit FROM budget_limits WHERE run_id=?", (run_id,)
            ).fetchone()
            maximum = limit[0] if limit else DEFAULT_CALL_LIMIT
            used = connection.execute(
                "SELECT COUNT(*) FROM provider_calls WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            if used >= maximum:
                exhausted = True
                exists = connection.execute(
                    "SELECT 1 FROM events WHERE run_id=? AND type='budget.exhausted' "
                    "AND id>(SELECT COALESCE(MAX(id),0) FROM events WHERE run_id=? "
                    "AND type='budget.approved') LIMIT 1", (run_id, run_id),
                ).fetchone()
                if not exists:
                    self._event(connection, run_id, "budget.exhausted")
            else:
                call_id = uuid4().hex
                connection.execute(
                    "INSERT INTO provider_calls(id, run_id, command_id, "
                    "node_execution_id, role, status, started_at) "
                    "VALUES (?, ?, ?, ?, ?, 'RESERVED', ?)",
                    (call_id, run_id, command_id, node_execution_id, role, now),
                )
                if used + 1 == warning_threshold(maximum):
                    self._event(connection, run_id, "budget.warning")
        if exhausted:
            raise BudgetExceeded("Provider 调用预算耗尽，需要人工处理")
        return call_id

    def finish(
        self, call_id: str, owner: str, epoch: int, status: str,
        duration_ms: int, response: AgentResponse | None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.facts.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            call = connection.execute(
                "SELECT run_id FROM provider_calls WHERE id=?", (call_id,)
            ).fetchone()
            if call is None:
                raise KeyError(call_id)
            lease = connection.execute(
                "SELECT 1 FROM run_leases WHERE run_id=? AND owner=? AND epoch=? "
                "AND expires_at>?", (call["run_id"], owner, epoch, now),
            ).fetchone()
            if lease is None:
                raise PermissionError("lease 已失效，禁止提交 Provider 结果")
            connection.execute(
                "UPDATE provider_calls SET status=?, duration_ms=?, input_tokens=?, "
                "output_tokens=?, finished_at=? WHERE id=? AND status='RESERVED'",
                (status, duration_ms, response.input_tokens if response else None,
                 response.output_tokens if response else None, now, call_id),
            )

    def summary(self, run_id: str) -> BudgetSummary:
        with self.facts.connect() as connection:
            if connection.execute(
                "SELECT 1 FROM runs WHERE id=?", (run_id,)
            ).fetchone() is None:
                raise KeyError(run_id)
            limit = connection.execute(
                "SELECT provider_limit FROM budget_limits WHERE run_id=?", (run_id,)
            ).fetchone()
            used, unknown = connection.execute(
                "SELECT COUNT(*), SUM(CASE WHEN status='RESERVED' THEN 1 ELSE 0 END) "
                "FROM provider_calls WHERE run_id=?", (run_id,),
            ).fetchone()
            repair_used = connection.execute(
                "SELECT COUNT(*) FROM events WHERE run_id=? AND "
                "type='candidate.created'", (run_id,),
            ).fetchone()[0]
            repair_exhausted = connection.execute(
                "SELECT 1 FROM events WHERE run_id=? AND "
                "type='budget.repair_exhausted' LIMIT 1", (run_id,),
            ).fetchone() is not None
            tokens_used, token_limit, token_usage_unknown = self.token_state(
                connection, run_id
            )
        maximum = limit[0] if limit else DEFAULT_CALL_LIMIT
        return BudgetSummary(
            used=used, limit=maximum, warning_at=warning_threshold(maximum),
            warning=used >= warning_threshold(maximum),
            requires_human=used >= maximum,
            unknown=unknown or 0,
            repair_used=repair_used, repair_limit=3,
            repair_exhausted=repair_exhausted,
            tokens_used=tokens_used,
            token_limit=token_limit,
            token_usage_unknown=token_usage_unknown,
            token_exhausted=(
                token_limit is not None and tokens_used >= token_limit
            ),
        )

    @staticmethod
    def token_state(connection, run_id: str) -> tuple[int, int | None, int]:
        policy = connection.execute(
            "SELECT runs.constraints_version, intakes.token_limit FROM runs "
            "JOIN intakes ON intakes.run_id=runs.id WHERE runs.id=?",
            (run_id,),
        ).fetchone()
        if policy is None:
            raise KeyError(run_id)
        usage = connection.execute(
            "SELECT COALESCE(SUM(CASE WHEN status!='RESERVED' THEN "
            "COALESCE(input_tokens,0)+COALESCE(output_tokens,0) ELSE 0 END),0), "
            "COALESCE(SUM(CASE WHEN input_tokens IS NULL OR output_tokens IS NULL "
            "THEN 1 ELSE 0 END),0) "
            "FROM provider_calls WHERE run_id=?",
            (run_id,),
        ).fetchone()
        token_limit = policy["token_limit"] if policy["constraints_version"] == 1 else None
        return usage[0], token_limit, usage[1]


class BudgetedProvider:
    def __init__(self, provider: Provider, budget: BudgetStore):
        self.provider = provider
        self.budget = budget
        self.owner: str | None = None
        self.epoch: int | None = None
        self.command_id: str | None = None
        self.node_execution_id: str | None = None

    def bind(self, owner: str, epoch: int, command_id: str) -> None:
        self.owner, self.epoch, self.command_id = owner, epoch, command_id

    def invoke(self, request: AgentRequest) -> AgentResponse:
        if not request.run_id or self.owner is None or self.epoch is None:
            raise ValueError("预算调用缺少 Run 或 lease")
        call_id = self.budget.reserve(
            request.run_id, request.role, self.owner, self.epoch,
            self.command_id, self.node_execution_id,
        )
        started = monotonic()
        try:
            response = self.provider.invoke(request)
        except Exception:
            self.budget.finish(
                call_id, self.owner, self.epoch, "FAILED",
                int((monotonic() - started) * 1000), None,
            )
            raise
        self.budget.finish(
            call_id, self.owner, self.epoch, "SUCCEEDED",
            int((monotonic() - started) * 1000), response,
        )
        return response
