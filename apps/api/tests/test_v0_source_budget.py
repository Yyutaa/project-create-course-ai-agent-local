from datetime import datetime, timedelta, timezone

from app.v0.budget import BudgetedProvider, BudgetStore
from app.v0.provider import AgentInput, AgentRequest, ToolTurn
from app.v0.schemas import CourseInput
from app.v0.storage import FactStore


class TurnProvider:
    def next_tool_turn(self, request, messages):
        return ToolTurn(content="{}", input_tokens=9, output_tokens=4)


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
