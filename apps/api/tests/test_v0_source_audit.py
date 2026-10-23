from datetime import datetime, timedelta, timezone

from app.v0.provider import AgentResponse
from app.v0.schemas import ArtifactRef, CourseInput
from app.v0.source_audit import source_gate
from app.v0.source_facts import SourceFacts
from app.v0.storage import FactStore


class AuditProvider:
    def __init__(self, excerpt):
        self.excerpt = excerpt

    def invoke(self, request):
        return AgentResponse(role="reviewer", payload={
            "complete": True,
            "claims": [{
                "line_number": 3,
                "claim_excerpt": "state changes update views",
                "document_id": self.document_id,
                "supporting_excerpt": self.excerpt,
                "status": "supported",
            }],
        })


def prepared_source(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="Vue", audience="初学者", goal="理解 state", language="zh"),
        "audit-source",
    )
    expires = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO run_leases(run_id, owner, epoch, expires_at) "
            "VALUES (?, 'worker-a', 1, ?)", (run.id, expires),
        )
    sources = SourceFacts(facts)
    search_id, _ = sources.begin_call(
        run.id, "course.source.search", {"query": "Vue"},
        "worker-a", 1, "node-1", "command-1",
    )
    candidate = sources.finish_search(
        search_id, "worker-a", 1,
        [{"url": "https://vuejs.org/guide", "title": "Vue Guide"}],
    )["candidates"][0]
    fetch_id, _ = sources.begin_call(
        run.id, "course.source.fetch",
        {"candidate_id": candidate["candidate_id"]},
        "worker-a", 1, "node-1", "command-1",
    )
    document = sources.finish_fetch(
        fetch_id, "worker-a", 1, candidate["candidate_id"],
        "Vue Guide", "Official docs: state changes update views.",
        {"registry_package": "vue", "repository": "vuejs/core",
         "official_host": "vuejs.org"},
    )
    reference = ArtifactRef(
        run_id=run.id, artifact_id="lesson-1", version=1,
        kind="lesson", content_hash="lesson-hash",
    )
    return sources, reference, document


def test_source_gate_passes_only_claim_with_exact_page_excerpt(tmp_path):
    sources, reference, document = prepared_source(tmp_path)
    provider = AuditProvider("state changes update views")
    provider.document_id = document["document_id"]

    report = source_gate(
        provider, sources, reference, "lesson-1",
        "# Vue state\n\nstate changes update views", "worker-a", 1,
    )

    assert report.results[0].status == "pass"
    assert report.findings == []
    with sources.facts.connect() as connection:
        row = connection.execute(
            "SELECT status, document_hash FROM source_claim_links WHERE run_id=?",
            (reference.run_id,),
        ).fetchone()
    assert tuple(row) == ("supported", document["content_hash"])


def test_source_gate_rejects_model_claim_when_page_does_not_contain_excerpt(tmp_path):
    sources, reference, document = prepared_source(tmp_path)
    provider = AuditProvider("not in the official page")
    provider.document_id = document["document_id"]

    report = source_gate(
        provider, sources, reference, "lesson-1",
        "# Vue state\n\nstate changes update views", "worker-a", 1,
    )

    assert report.results[0].status == "fail"
    assert report.findings[0].category == "fact"


def test_source_gate_blocks_internal_source_status_from_student_lesson(tmp_path):
    sources, reference, _ = prepared_source(tmp_path)
    provider = AuditProvider("state changes update views")

    report = source_gate(
        provider, sources, reference, "lesson-1",
        "# Vue state\n\n当前 Run 未提供已批准来源摘要。",
        "worker-a", 1,
    )

    assert report.results[0].rule_id == "source.internal_status_in_lesson"
    assert report.results[0].status == "fail"
    assert report.findings[0].category == "fact"


def test_source_gate_keeps_conflicting_or_incomplete_evidence_unverified(tmp_path):
    sources, reference, document = prepared_source(tmp_path)

    class ConflictProvider:
        def invoke(self, request):
            return AgentResponse(role="reviewer", payload={
                "complete": True,
                "claims": [{
                    "line_number": 3,
                    "claim_excerpt": "state changes update views",
                    "document_id": document["document_id"],
                    "supporting_excerpt": "state changes update views",
                    "status": "conflict",
                }],
            })

    report = source_gate(
        ConflictProvider(), sources, reference, "lesson-1",
        "# Vue state\n\nstate changes update views", "worker-a", 1,
    )
    assert report.results[0].status == "fail"
    assert report.findings[0].category == "fact"

    class IncompleteProvider:
        def invoke(self, request):
            return AgentResponse(role="reviewer", payload={
                "complete": False, "claims": [],
            })

    incomplete = source_gate(
        IncompleteProvider(), sources, reference, "lesson-1",
        "# Vue state\n\nstate changes update views", "worker-a", 1,
    )
    assert incomplete.results[0].rule_id == "source.claim_inventory_incomplete"
