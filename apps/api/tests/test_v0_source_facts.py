from datetime import datetime, timedelta, timezone

import pytest

from app.v0.schemas import CourseInput
from app.v0.context_contracts import SourceSummaryV1
from app.v0.source_facts import SourceFacts, ToolBudgetExceeded
from app.v0.storage import FactStore


@pytest.fixture
def source_store(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="Vue", audience="初学者", goal="理解 state", language="zh"),
        "source-run",
    )
    expires = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO run_leases(run_id, owner, epoch, expires_at) "
            "VALUES (?, 'worker-a', 1, ?)",
            (run.id, expires),
        )
    return facts, SourceFacts(facts), run.id


def test_completed_search_reuses_persisted_result_without_new_attempt(source_store):
    facts, sources, run_id = source_store
    call_id, previous = sources.begin_call(
        run_id, "course.source.search", {"query": "Vue state"},
        "worker-a", 1, "blueprint", "command-1",
    )
    assert previous is None
    sources.finish_call(call_id, "worker-a", 1, {"results": []})
    replay_id, result = sources.begin_call(
        run_id, "course.source.search", {"query": "Vue state"},
        "worker-a", 1, "blueprint", "command-2",
    )
    assert replay_id == call_id
    assert result == {"results": []}
    with facts.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM tool_invocations WHERE run_id=?", (run_id,)
        ).fetchone()[0] == 1


def test_stale_lease_cannot_commit_tool_result(source_store):
    facts, sources, run_id = source_store
    call_id, _ = sources.begin_call(
        run_id, "course.source.search", {"query": "Vue"},
        "worker-a", 1, "blueprint", "command-1",
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE run_leases SET owner='worker-b', epoch=2 WHERE run_id=?",
            (run_id,),
        )
    with pytest.raises(PermissionError):
        sources.finish_call(call_id, "worker-a", 1, {"results": []})
    with facts.connect() as connection:
        assert connection.execute(
            "SELECT status FROM tool_invocations WHERE id=?", (call_id,)
        ).fetchone()[0] == "STARTED"


def test_tool_limit_counts_crashed_attempts(source_store):
    _, sources, run_id = source_store
    for attempt in range(20):
        sources.begin_call(
            run_id, "course.source.search", {"query": f"Vue {attempt}"},
            "worker-a", 1, "blueprint", "command-1",
        )
    with pytest.raises(ToolBudgetExceeded):
        sources.begin_call(
            run_id, "course.source.search", {"query": "Vue overflow"},
            "worker-a", 1, "blueprint", "command-1",
        )


def test_search_and_fetch_record_exact_candidate_and_page_versions(source_store):
    _, sources, run_id = source_store
    search_id, _ = sources.begin_call(
        run_id, "course.source.search", {"query": "Vue official"},
        "worker-a", 1, "blueprint", "command-1",
    )
    result = sources.finish_search(
        search_id, "worker-a", 1,
        [{"url": "https://vuejs.org/guide", "title": "Vue Guide"},
         {"url": "file:///etc/passwd", "title": "unsafe"}],
    )
    assert len(result["candidates"]) == 1
    candidate = result["candidates"][0]
    assert candidate["url"] == "https://vuejs.org/guide"
    assert sources.get_candidate(run_id, candidate["candidate_id"])["status"] == (
        "candidate"
    )

    fetch_id, _ = sources.begin_call(
        run_id, "course.source.fetch",
        {"candidate_id": candidate["candidate_id"]},
        "worker-a", 1, "blueprint", "command-1",
    )
    page = sources.finish_fetch(
        fetch_id, "worker-a", 1, candidate["candidate_id"],
        "Vue Guide", "# Guide\n\nref() stores reactive state.",
        {"registry_package": "vue", "repository": "vuejs/core",
         "official_host": "vuejs.org"},
    )
    assert page["document_id"]
    assert sources.list_documents(run_id)[0]["content_hash"] == page["content_hash"]
    assert sources.list_documents(run_id)[0]["status"] == "eligible"
    assert sources.summary_pack(run_id) == [{
        "document_id": page["document_id"],
        "url": "https://vuejs.org/guide", "title": "Vue Guide",
        "excerpt": "# Guide\n\nref() stores reactive state.",
        "content_hash": page["content_hash"],
    }]


@pytest.mark.parametrize("missing_title", ["", "   "])
def test_titleless_eligible_document_has_valid_summary_without_rewriting_fact(
    source_store, missing_title,
):
    _, sources, run_id = source_store
    search_id, _ = sources.begin_call(
        run_id, "course.source.search", {"query": "Vue official"},
        "worker-a", 1, "blueprint", "command-1",
    )
    candidate = sources.finish_search(
        search_id, "worker-a", 1,
        [{"url": "https://vuejs.org/guide", "title": missing_title}],
    )["candidates"][0]
    fetch_id, _ = sources.begin_call(
        run_id, "course.source.fetch",
        {"candidate_id": candidate["candidate_id"]},
        "worker-a", 1, "blueprint", "command-1",
    )
    sources.finish_fetch(
        fetch_id, "worker-a", 1, candidate["candidate_id"],
        missing_title, "# Guide\n\nOfficial content.",
        {"official_host": "vuejs.org"},
    )

    assert sources.list_documents(run_id)[0]["title"] == missing_title
    summary = sources.summary_pack(run_id)[0]
    assert summary["title"] == "https://vuejs.org/guide"
    SourceSummaryV1.model_validate(summary)


def test_fetch_rejects_identity_for_different_host(source_store):
    _, sources, run_id = source_store
    search_id, _ = sources.begin_call(
        run_id, "course.source.search", {"query": "Vue official"},
        "worker-a", 1, "blueprint", "command-1",
    )
    candidate = sources.finish_search(
        search_id, "worker-a", 1,
        [{"url": "https://vuejs.org/guide", "title": "Vue Guide"}],
    )["candidates"][0]
    fetch_id, _ = sources.begin_call(
        run_id, "course.source.fetch",
        {"candidate_id": candidate["candidate_id"]},
        "worker-a", 1, "blueprint", "command-1",
    )
    with pytest.raises(ValueError):
        sources.finish_fetch(
            fetch_id, "worker-a", 1, candidate["candidate_id"],
            "Vue Guide", "state changes update views",
            {"official_host": "example.com", "repository": "vuejs/core"},
        )
    assert sources.list_documents(run_id) == []
