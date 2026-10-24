from datetime import datetime, timedelta, timezone

import pytest
from langgraph.graph import END, START, StateGraph

from app.v0.budget import BudgetedProvider, BudgetExceeded, BudgetStore, RetryStopped
from app.v0.provider import AgentInput, AgentRequest, FakeProvider, ProviderError, ToolTurn
from app.v0.provider import AgentResponse, TransientProviderError
from app.v0.worker import Worker
from app.v0.execution import ExecutionStore
from app.v0.schemas import CourseInput
from app.v0.storage import FactStore


class TurnProvider:
    def next_tool_turn(self, request, messages):
        return ToolTurn(content="{}", input_tokens=9, output_tokens=4)


class FlakyProvider:
    def __init__(self, failure: str, count: int):
        self.failure, self.remaining, self.calls = failure, count, 0

    def invoke(self, request):
        self.calls += 1
        if self.remaining:
            self.remaining -= 1
            raise TransientProviderError(self.failure)
        return AgentResponse(role=request.role, payload={})


def inside_graph(call):
    builder = StateGraph(dict)
    builder.add_node("provider_call", lambda _state: {"result": call()})
    builder.add_edge(START, "provider_call")
    builder.add_edge("provider_call", END)
    return builder.compile().invoke({})["result"]


def test_provider_call_outside_graph_does_not_run_a_private_retry_loop(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(CourseInput(
        topic="Vue", audience="初学者", goal="理解 state", language="zh",
    ), "outside-graph")
    expires = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO run_leases(run_id, owner, epoch, expires_at) "
            "VALUES (?, 'worker-a', 1, ?)", (run.id, expires),
        )
    raw = FlakyProvider("timeout", 1)
    provider = BudgetedProvider(raw, BudgetStore(facts.path))
    provider.bind("worker-a", 1, "command-1")
    provider.node_execution_id = "node-1"
    request = AgentRequest(
        role="mission", run_id=run.id, goal="plan", instructions=["plan"],
        inputs=[AgentInput(kind="intake", content={})],
        output_schema={"type": "object"},
    )
    with pytest.raises(TransientProviderError):
        provider.invoke(request)
    assert raw.calls == 1
    with facts.connect() as connection:
        statuses = [row[0] for row in connection.execute(
            "SELECT status FROM provider_calls WHERE run_id=? ORDER BY rowid", (run.id,),
        )]
    assert statuses == ["FAILED_TIMEOUT"]


def test_new_mission_provider_timeout_has_one_extra_budgeted_attempt(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(CourseInput(
        topic="Vue", audience="初学者", goal="理解 state", language="zh",
    ), "transient")
    expires = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO run_leases(run_id, owner, epoch, expires_at) "
            "VALUES (?, 'worker-a', 1, ?)", (run.id, expires),
        )
    flaky = FlakyProvider("timeout", 1)
    provider = BudgetedProvider(flaky, BudgetStore(facts.path))
    provider.bind("worker-a", 1, "command-1")
    provider.node_execution_id = "node-1"
    request = AgentRequest(
        role="mission", run_id=run.id, goal="plan", instructions=["plan"],
        inputs=[AgentInput(kind="intake", content={})],
        output_schema={"type": "object"},
    )
    assert inside_graph(lambda: provider.invoke(request)).role == "mission"
    assert flaky.calls == 2
    with facts.connect() as connection:
        statuses = [row[0] for row in connection.execute(
            "SELECT status FROM provider_calls WHERE run_id=? ORDER BY started_at, rowid",
            (run.id,),
        )]
    assert statuses == ["FAILED_TIMEOUT", "SUCCEEDED"]


def test_new_blueprint_429_stops_after_two_budgeted_calls(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(CourseInput(
        topic="Vue", audience="初学者", goal="理解 state", language="zh",
    ), "rate-limited")
    expires = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO run_leases(run_id, owner, epoch, expires_at) "
            "VALUES (?, 'worker-a', 1, ?)", (run.id, expires),
        )
    flaky = FlakyProvider("http_429", 3)
    provider = BudgetedProvider(flaky, BudgetStore(facts.path))
    provider.bind("worker-a", 1, "command-1")
    provider.node_execution_id = "node-1"
    request = AgentRequest(
        role="blueprint", run_id=run.id, goal="plan", instructions=["plan"],
        inputs=[AgentInput(kind="intake", content={})],
        output_schema={"type": "object"},
    )
    with pytest.raises(TransientProviderError):
        inside_graph(lambda: provider.invoke(request))
    assert flaky.calls == 2


@pytest.mark.parametrize("legacy", [False, True])
def test_schema_error_and_legacy_timeout_never_auto_retry(tmp_path, legacy):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(CourseInput(
        topic="Vue", audience="初学者", goal="理解 state", language="zh",
    ), "non-retry")
    expires = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO run_leases(run_id, owner, epoch, expires_at) "
            "VALUES (?, 'worker-a', 1, ?)", (run.id, expires),
        )
        if legacy:
            connection.execute(
                "UPDATE runs SET planning_loop_version=0 WHERE id=?", (run.id,),
            )

    class InvalidProvider:
        calls = 0

        def invoke(self, _request):
            self.calls += 1
            raise ProviderError("blueprint 输出校验失败：lessons (missing)")

    raw = FlakyProvider("timeout", 1) if legacy else InvalidProvider()
    provider = BudgetedProvider(raw, BudgetStore(facts.path))
    provider.bind("worker-a", 1, "command-1")
    provider.node_execution_id = "node-1"
    request = AgentRequest(
        role="blueprint", run_id=run.id, goal="plan", instructions=["plan"],
        inputs=[AgentInput(kind="intake", content={})],
        output_schema={"type": "object"},
    )
    with pytest.raises(ProviderError):
        provider.invoke(request)
    assert raw.calls == 1


def test_retry_cannot_bypass_provider_budget(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(CourseInput(
        topic="Vue", audience="初学者", goal="理解 state", language="zh",
    ), "budget-boundary")
    expires = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO run_leases(run_id, owner, epoch, expires_at) "
            "VALUES (?, 'worker-a', 1, ?)", (run.id, expires),
        )
        connection.execute(
            "INSERT INTO budget_limits(run_id, provider_limit) VALUES (?, 1)",
            (run.id,),
        )
    raw = FlakyProvider("timeout", 1)
    provider = BudgetedProvider(raw, BudgetStore(facts.path))
    provider.bind("worker-a", 1, "command-1")
    provider.node_execution_id = "node-1"
    request = AgentRequest(
        role="mission", run_id=run.id, goal="plan", instructions=["plan"],
        inputs=[AgentInput(kind="intake", content={})],
        output_schema={"type": "object"},
    )
    with pytest.raises(BudgetExceeded):
        inside_graph(lambda: provider.invoke(request))
    assert raw.calls == 1


def test_worker_timeout_twice_waits_with_stable_reason(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(CourseInput(
        topic="Vue", audience="初学者", goal="理解 state", language="zh",
    ), "worker-timeout", enqueue_start=True)
    raw = FlakyProvider("timeout", 2)
    worker = Worker(facts.path, provider=raw, owner="worker-a")
    assert worker.run_once()
    waiting = facts.get_run(run.id)
    assert waiting.stages[1].status == "waiting_for_human"
    assert waiting.stages[1].failure_reason == "provider_transient_exhausted_timeout"
    assert ExecutionStore(facts.path).read_model(run.id).waiting_reason == (
        "provider_transient_exhausted_timeout"
    )
    assert waiting.mission is None
    assert raw.calls == 2
    with facts.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM provider_calls WHERE run_id=?", (run.id,),
        ).fetchone()[0] == 2


def test_mission_success_after_timeout_still_requires_human_approval(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(CourseInput(
        topic="Vue", audience="初学者", goal="理解 state", language="zh",
    ), "mission-timeout-success", enqueue_start=True)

    class OnceTimeout(FakeProvider):
        mission_calls = 0

        def invoke(self, request):
            if request.role == "mission":
                self.mission_calls += 1
                if self.mission_calls == 1:
                    raise TransientProviderError("timeout")
            return super().invoke(request)

    raw = OnceTimeout()
    worker = Worker(facts.path, provider=raw, owner="worker-a")
    assert worker.run_once()
    waiting = facts.get_run(run.id)
    assert raw.mission_calls == 2
    assert waiting.mission is not None
    assert waiting.stages[1].status == "waiting_for_human"
    assert waiting.stages[1].failure_reason == "Mission 待人工确认"
    assert waiting.blueprint is None


def test_stop_request_prevents_extra_transient_attempt(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(CourseInput(
        topic="Vue", audience="初学者", goal="理解 state", language="zh",
    ), "stop-retry")
    expires = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    with facts.connect() as connection:
        connection.execute("INSERT INTO run_controls(run_id) VALUES (?)", (run.id,))
        connection.execute(
            "INSERT INTO run_leases(run_id, owner, epoch, expires_at) "
            "VALUES (?, 'worker-a', 1, ?)", (run.id, expires),
        )

    class StopOnFailure:
        calls = 0

        def invoke(self, _request):
            self.calls += 1
            with facts.connect() as connection:
                connection.execute(
                    "UPDATE run_controls SET stop_requested=1 WHERE run_id=?",
                    (run.id,),
                )
            raise TransientProviderError("timeout")

    raw = StopOnFailure()
    provider = BudgetedProvider(raw, BudgetStore(facts.path))
    provider.bind("worker-a", 1, "command-1")
    provider.node_execution_id = "node-1"
    request = AgentRequest(
        role="mission", run_id=run.id, goal="plan", instructions=["plan"],
        inputs=[AgentInput(kind="intake", content={})],
        output_schema={"type": "object"},
    )
    with pytest.raises(TransientProviderError):
        inside_graph(lambda: provider.invoke(request))
    assert raw.calls == 1


def test_blueprint_tool_turn_429_retries_only_failed_turn(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(CourseInput(
        topic="Vue", audience="初学者", goal="理解 state", language="zh",
    ), "tool-turn-retry")
    expires = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO run_leases(run_id, owner, epoch, expires_at) "
            "VALUES (?, 'worker-a', 1, ?)", (run.id, expires),
        )

    class FlakyTurn:
        calls = 0

        def next_tool_turn(self, _request, _messages):
            self.calls += 1
            if self.calls == 1:
                raise TransientProviderError("http_429")
            return ToolTurn(content="{}", input_tokens=9, output_tokens=4)

    raw = FlakyTurn()
    provider = BudgetedProvider(raw, BudgetStore(facts.path))
    provider.bind("worker-a", 1, "command-1")
    provider.node_execution_id = "node-1"
    request = AgentRequest(
        role="blueprint", run_id=run.id, goal="plan", instructions=["plan"],
        inputs=[AgentInput(kind="intake", content={})],
        output_schema={"type": "object"},
    )
    assert inside_graph(lambda: provider.next_tool_turn(
        request, [{"role": "user", "content": "docs"}],
    )).content == "{}"
    assert raw.calls == 2
    with facts.connect() as connection:
        statuses = [row[0] for row in connection.execute(
            "SELECT status FROM provider_calls WHERE run_id=? ORDER BY rowid",
            (run.id,),
        )]
    assert statuses == ["FAILED_429", "SUCCEEDED"]


def test_stop_between_retry_decision_and_reservation_blocks_second_call(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(CourseInput(
        topic="Vue", audience="初学者", goal="理解 state", language="zh",
    ), "stop-race", enqueue_start=True)
    expires = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO run_leases(run_id, owner, epoch, expires_at) "
            "VALUES (?, 'worker-a', 1, ?)", (run.id, expires),
        )
    raw = FlakyProvider("timeout", 1)
    provider = BudgetedProvider(raw, BudgetStore(facts.path))
    provider.bind("worker-a", 1, "command-1")
    provider.node_execution_id = "node-1"
    original = provider._may_retry

    def stop_after_check(request):
        allowed = original(request)
        with facts.connect() as connection:
            connection.execute(
                "UPDATE run_controls SET stop_requested=1 WHERE run_id=?",
                (run.id,),
            )
        return allowed

    provider._may_retry = stop_after_check
    request = AgentRequest(
        role="mission", run_id=run.id, goal="plan", instructions=["plan"],
        inputs=[AgentInput(kind="intake", content={})],
        output_schema={"type": "object"},
    )
    with pytest.raises(RetryStopped):
        inside_graph(lambda: provider.invoke(request))
    assert raw.calls == 1


def test_tool_turn_uses_existing_provider_call_budget(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="Vue", audience="初学者", goal="理解 state", language="zh"),
        "source-budget",
    )
    expires = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO run_leases(run_id, owner, epoch, expires_at) "
            "VALUES (?, 'worker-a', 1, ?)", (run.id, expires),
        )
    provider = BudgetedProvider(TurnProvider(), BudgetStore(facts.path))
    provider.bind("worker-a", 1, "command-1")
    request = AgentRequest(
        role="blueprint", run_id=run.id, goal="plan", instructions=["official"],
        inputs=[AgentInput(kind="intake", content={"topic": "Vue"})],
        output_schema={"type": "object"},
    )

    assert provider.next_tool_turn(
        request, [{"role": "user", "content": "Find Vue docs"}]
    ).content == "{}"
    with facts.connect() as connection:
        row = connection.execute(
            "SELECT status, input_tokens, output_tokens FROM provider_calls "
            "WHERE run_id=?", (run.id,),
        ).fetchone()
    assert tuple(row) == ("SUCCEEDED", 9, 4)
