from datetime import datetime, timedelta, timezone

from app.v0.provider import AgentInput, AgentRequest, ToolCall, ToolTurn
from app.v0.schemas import CourseInput
from app.v0.source_facts import SourceFacts
from app.v0.source_runtime import SourceToolRuntime
from app.v0.storage import FactStore


class ScriptedProvider:
    def __init__(self):
        self.messages = []
        self.turns = [
            ToolTurn(tool_calls=[ToolCall(
                id="search-1", name="course_source_search",
                arguments={"query": "Vue state official guide"},
            )]),
            ToolTurn(tool_calls=[ToolCall(
                id="fetch-1", name="course_source_fetch",
                arguments={"candidate_id": "candidate-placeholder"},
            )]),
            ToolTurn(content='{"lessons":[{"title":"Vue state",'
                             '"learning_goal":"Understand state",'
                             '"evidence":"Explain state"}]}'),
        ]

    def next_tool_turn(self, request, messages):
        self.messages.append(list(messages))
        if len(self.messages) == 2:
            import json

            search_result = json.loads(messages[-1]["content"])
            self.turns[0].tool_calls[0].arguments["candidate_id"] = (
                search_result["result"]["candidates"][0]["candidate_id"]
            )
        return self.turns.pop(0)


class FakeSourceClient:
    def __init__(self):
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return [
            {"url": "https://vuejs.org/guide", "title": "Vue Guide"},
            {"url": "https://third-party.example.org/vue", "title": "Third party"},
        ]

    def fetch(self, url, timeout_seconds=20):
        return {"title": "Vue Guide", "content": "redirected untrusted page"}


class FakeIdentity:
    def official_host(self, topic):
        return "vuejs.org"

    def verify(self, topic, url, deadline=None):
        return {"registry_package": "vue", "repository": "vuejs/core",
                "official_host": "vuejs.org",
                "verified_content": "# Guide\n\nState changes update views."}

    def verify_manual(self, url, decision, deadline=None):
        return {**decision, "verified_content": "# Guide\n\nState changes update views."}


def test_model_tool_loop_persists_source_and_returns_valid_json(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="Vue state", audience="初学者", goal="理解 state", language="zh"),
        "tool-loop",
    )
    expires = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO run_leases(run_id, owner, epoch, expires_at) "
            "VALUES (?, 'worker-a', 1, ?)", (run.id, expires),
        )
    provider = ScriptedProvider()
    client = FakeSourceClient()
    runtime = SourceToolRuntime(SourceFacts(facts), client, FakeIdentity())
    runtime.bind("worker-a", 1, "command-1", "node-1")
    request = AgentRequest(
        role="blueprint", run_id=run.id, goal="Plan Vue course",
        instructions=["Use official evidence"],
        inputs=[AgentInput(kind="intake", content={"topic": "Vue state"})],
        output_schema={"type": "object"},
    )

    result = runtime.run(request, provider, "workflow.blueprint", "Vue state")

    assert result.payload["lessons"][0]["title"] == "Vue state"
    documents = SourceFacts(facts).list_documents(run.id)
    assert len(documents) == 1
    assert documents[0]["content"] == "# Guide\n\nState changes update views."
    assert "verified_content" not in documents[0]["identity_json"]
    assert "untrusted_source_material" in provider.messages[2][-1]["content"]
    assert client.queries == ["site:vuejs.org Vue state official guide"]
    assert [item["url"] for item in SourceFacts(facts).list_candidates(run.id)] == [
        "https://vuejs.org/guide",
    ]


def test_retry_rechecks_prior_official_candidate_before_model_turn(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="Vue", audience="初学者", goal="理解 state", language="zh"),
        "tool-recheck",
    )
    expires = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO run_leases(run_id, owner, epoch, expires_at) "
            "VALUES (?, 'worker-a', 1, ?)", (run.id, expires),
        )
        for index, (url, status) in enumerate((
            ("https://vuejs.org/guide", "candidate"),
            ("https://vuejs.org/reference/state", "needs_human"),
            ("https://raw.githubusercontent.com/user/repo/main/vue.md", "needs_human"),
        )):
            connection.execute(
                "INSERT INTO source_candidates "
                "(id, run_id, url, title, status, metadata_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"prior-{index}", run.id, url, "Vue", status,
                 f"hash-{index}", f"2026-01-01T00:00:0{index}+00:00"),
            )

    class FinalProvider:
        messages = None

        def next_tool_turn(self, request, messages):
            self.messages = messages
            return ToolTurn(content='{"lessons": []}')

    runtime = SourceToolRuntime(
        SourceFacts(facts), FakeSourceClient(), FakeIdentity(),
    )
    runtime.bind("worker-a", 1, "command-1", "node-1")
    request = AgentRequest(
        role="blueprint", run_id=run.id, goal="Plan Vue course",
        instructions=["Use official evidence"],
        inputs=[AgentInput(kind="intake", content={"topic": "Vue"})],
        output_schema={"type": "object"},
    )
    provider = FinalProvider()
    runtime.run(request, provider, "workflow.blueprint", "Vue")
    assert [item["url"] for item in SourceFacts(facts).list_documents(run.id)] == [
        "https://vuejs.org/reference/state",
    ]
    import json

    source_evidence = json.loads(provider.messages[1]["content"])["source_evidence"]
    assert source_evidence[0]["url"] == "https://vuejs.org/reference/state"


def test_human_approved_candidate_is_fetched_on_resume_without_model_tool_call(
    tmp_path,
):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="Vue", audience="初学者", goal="学习", language="zh"),
        "approved-recheck",
    )
    expires = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO run_leases(run_id, owner, epoch, expires_at) "
            "VALUES (?, 'worker-a', 1, ?)", (run.id, expires),
        )
        connection.execute(
            "INSERT INTO source_candidates "
            "(id, run_id, url, title, status, metadata_hash, created_at) "
            "VALUES ('approved-1', ?, 'https://vuejs.org/guide', 'Vue', "
            "'human_approved', 'hash-1', '2026-01-01T00:00:00+00:00')",
            (run.id,),
        )
        connection.execute(
            "INSERT INTO source_decisions "
            "(id, run_id, candidate_id, checkpoint_id, action, reason, "
            "command_id, created_at) VALUES "
            "('decision-1', ?, 'approved-1', 'checkpoint-1', 'approve', "
            "'人工确认归属', 'command-1', '2026-01-01T00:00:00+00:00')",
            (run.id,),
        )

    class FinalProvider:
        def next_tool_turn(self, request, messages):
            return ToolTurn(content='{"lessons": []}')

    runtime = SourceToolRuntime(
        SourceFacts(facts), FakeSourceClient(), FakeIdentity(),
    )
    runtime.bind("worker-a", 1, "command-1", "node-1")
    runtime.run(AgentRequest(
        role="blueprint", run_id=run.id, goal="Plan Vue course",
        instructions=["Use official evidence"],
        inputs=[AgentInput(kind="intake", content={"topic": "Vue"})],
        output_schema={"type": "object"},
    ), FinalProvider(), "workflow.blueprint", "Vue")
    assert len(SourceFacts(facts).list_documents(run.id)) == 1
