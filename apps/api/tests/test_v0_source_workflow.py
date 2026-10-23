import json

from app.v0.provider import AgentResponse, FakeProvider, ToolCall, ToolTurn
from app.v0.delivery import DeliveryStore
from app.v0.schemas import CourseInput
from app.v0.source_facts import SourceFacts
from app.v0.storage import FactStore
from app.v0.worker import Worker


class SourceCourseProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.blueprint_turn = 0

    def next_tool_turn(self, request, messages):
        if request.role == "blueprint":
            self.blueprint_turn += 1
            if self.blueprint_turn == 1:
                return ToolTurn(tool_calls=[ToolCall(
                    id="search-1", name="course_source_search",
                    arguments={"query": "Vue state official guide"},
                )])
            if self.blueprint_turn == 2:
                candidate = json.loads(messages[-1]["content"])["result"]["candidates"][0]
                return ToolTurn(tool_calls=[ToolCall(
                    id="fetch-1", name="course_source_fetch",
                    arguments={"candidate_id": candidate["candidate_id"]},
                )])
            return ToolTurn(content=json.dumps({"lessons": [{
                "title": "Vue state", "learning_goal": "理解 state",
                "evidence": "解释 state 更新如何影响视图",
            }]}, ensure_ascii=False))
        if request.role == "writer":
            return ToolTurn(content=json.dumps({
                "title": "Vue state",
                "markdown": "# Vue state\n\nstate changes update views",
            }))
        raise AssertionError(f"Unexpected tool role {request.role}")

    def invoke(self, request):
        if request.role == "reviewer" and "独立核验" in request.goal:
            document = request.inputs[0].content["official_sources"][0]
            return AgentResponse(role="reviewer", payload={
                "complete": True, "claims": [{
                    "line_number": 3,
                    "claim_excerpt": "state changes update views",
                    "document_id": document["document_id"],
                    "supporting_excerpt": "state changes update views",
                    "status": "supported",
                }],
            })
        return super().invoke(request)


class SourceClient:
    def search(self, query):
        return [{"url": "https://vuejs.org/guide", "title": "Vue Guide"}]

    def fetch(self, url, timeout_seconds=20):
        return {"title": "Vue Guide", "content": "state changes update views"}


class Identity:
    def official_host(self, topic):
        return "vuejs.org"

    def verify(self, topic, url, deadline=None):
        return {"registry_package": "vue", "repository": "vuejs/core",
                "official_host": "vuejs.org",
                "verified_content": "state changes update views"}


def test_new_run_reaches_human_release_only_with_supported_source_claim(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(
            topic="Vue state", audience="初学者", goal="理解 state", language="zh",
            expected_chapters=1, min_effective_chars=1,
        ),
        "official-run", enqueue_start=True,
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0 WHERE id=?", (run.id,),
        )
    worker = Worker(facts.path, provider=SourceCourseProvider())
    worker.source_runtime.client = SourceClient()
    worker.source_runtime.identity = Identity()

    assert worker.run_once()

    current = facts.get_run(run.id)
    assert current.status == "waiting_for_human"
    assert current.stages[6].status == "waiting_for_human"
    assert current.quality is not None and current.quality.status == "ready"
    assert "未核验事实来源" not in current.quality.limitations
    assert len(SourceFacts(facts).list_documents(run.id)) == 1
    evidence = DeliveryStore(facts.path).read(run.id)
    assert [item.tool_id for item in evidence.tool_calls] == [
        "course.source.search", "course.source.fetch",
    ]
    assert evidence.source_claims[0].status == "supported"
