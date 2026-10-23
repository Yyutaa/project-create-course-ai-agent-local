from app.v0.execution import ExecutionStore
from app.v0.provider import FakeProvider
from app.v0.schemas import CourseInput
from app.v0.source_facts import SourceFacts
from app.v0.storage import FactStore
from app.v0.worker import Worker
from app.api.run_routes import SourceReviewInput


def test_proposed_url_waits_then_exact_human_approval_records_identity(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="Vue", audience="初学者", goal="理解 state", language="zh"),
        "source-review", enqueue_start=True,
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0 WHERE id=?", (run.id,),
        )
    worker = Worker(facts.path, provider=FakeProvider())
    assert worker.run_once()
    commands = ExecutionStore(facts.path)
    review = commands.read_model(run.id).source_review
    assert review is not None
    assert review.candidates == []

    commands.accept(run.id, "SOURCE_REVIEW", {
        "action": "propose_url", "url": "https://vuejs.org/guide",
        "reason": "请核对该页面的维护方归属",
        "expected_checkpoint_id": review.checkpoint_id,
    }, "propose-1")
    assert worker.run_once()
    waiting = commands.read_model(run.id).source_review
    assert waiting is not None
    assert len(waiting.candidates) == 1
    candidate = waiting.candidates[0]
    assert candidate.status == "needs_human"
    assert facts.get_run(run.id).status == "waiting_for_human"

    commands.accept(run.id, "SOURCE_REVIEW", {
        "action": "approve", "candidate_id": candidate.id,
        "metadata_hash": candidate.metadata_hash,
        "reason": "已人工核对官方归属，仍需逐项核验正文事实",
        "expected_checkpoint_id": waiting.checkpoint_id,
    }, "approve-1")
    assert worker.run_once()
    approved = SourceFacts(facts).get_candidate(run.id, candidate.id)
    assert approved["status"] == "human_approved"
    assert SourceFacts(facts).list_documents(run.id) == []


def test_resume_does_not_approve_source_wait(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="Vue", audience="初学者", goal="理解 state", language="zh"),
        "source-resume", enqueue_start=True,
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0 WHERE id=?", (run.id,),
        )
    worker = Worker(facts.path, provider=FakeProvider())
    assert worker.run_once()
    commands = ExecutionStore(facts.path)
    assert commands.read_model(run.id).source_review is not None
    commands.accept(run.id, "RESUME", {}, "resume-source")
    assert worker.run_once()
    assert facts.get_run(run.id).stages[2].status == "waiting_for_human"


def test_source_review_only_shows_attempted_reviewable_candidates(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="React state", audience="初学者", goal="学习", language="zh"),
        "source-queue", enqueue_start=True,
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0 WHERE id=?", (run.id,),
        )
    worker = Worker(facts.path, provider=FakeProvider())
    assert worker.run_once()
    with facts.connect() as connection:
        for index, (url, status) in enumerate((
            ("https://react.dev/learn/state", "candidate"),
            ("https://zh-hans.react.dev/learn/state", "needs_human"),
            ("https://raw.githubusercontent.com/user/repo/main/state.md",
             "needs_human"),
        )):
            connection.execute(
                "INSERT INTO source_candidates "
                "(id, run_id, url, title, status, metadata_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"candidate-{index}", run.id, url, "State", status,
                 f"hash-{index}", f"2026-01-01T00:00:0{index}+00:00"),
            )
    review = ExecutionStore(facts.path).read_model(run.id).source_review
    assert review is not None
    assert [item.url for item in review.candidates] == [
        "https://zh-hans.react.dev/learn/state",
    ]
    assert review.hidden_candidate_count == 2
    assert review.retry_remaining == 2


def test_source_retry_is_bounded_and_reject_does_not_restart_workflow(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="Vue", audience="初学者", goal="理解 state", language="zh"),
        "source-retry", enqueue_start=True,
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0 WHERE id=?", (run.id,),
        )
    worker = Worker(facts.path, provider=FakeProvider())
    assert worker.run_once()
    commands = ExecutionStore(facts.path)
    first = commands.read_model(run.id).source_review
    assert first is not None
    commands.accept(run.id, "SOURCE_REVIEW", {
        "action": "retry_search", "expected_checkpoint_id": first.checkpoint_id,
    }, "retry-search-1")
    assert worker.run_once()
    second = commands.read_model(run.id).source_review
    assert second is not None
    assert second.retry_remaining == 1
    commands.accept(run.id, "SOURCE_REVIEW", {
        "action": "retry_search", "expected_checkpoint_id": second.checkpoint_id,
    }, "retry-search-2")
    assert worker.run_once()
    exhausted = commands.read_model(run.id).source_review
    assert exhausted is not None
    assert exhausted.retry_remaining == 0
    commands.accept(run.id, "SOURCE_REVIEW", {
        "action": "retry_search", "expected_checkpoint_id": exhausted.checkpoint_id,
    }, "retry-search-3")
    assert worker.run_once()
    assert commands.read_model(run.id).source_review.retry_remaining == 0
    assert any(item.status == "REJECTED" for item in commands.read_model(run.id).commands)


def test_reject_candidate_needs_no_written_reason_and_stays_waiting(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="Vue", audience="初学者", goal="理解 state", language="zh"),
        "source-reject", enqueue_start=True,
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0 WHERE id=?", (run.id,),
        )
    worker = Worker(facts.path, provider=FakeProvider())
    assert worker.run_once()
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO source_candidates "
            "(id, run_id, url, title, status, metadata_hash, created_at) "
            "VALUES ('candidate-1', ?, 'https://vuejs.org/guide', 'Vue', "
            "'needs_human', 'hash-1', '2026-01-01T00:00:00+00:00')",
            (run.id,),
        )
    commands = ExecutionStore(facts.path)
    review = commands.read_model(run.id).source_review
    assert review is not None
    payload = SourceReviewInput(
        action="reject", expected_checkpoint_id=review.checkpoint_id,
        candidate_id="candidate-1", metadata_hash="hash-1",
    ).model_dump(exclude_none=True)
    commands.accept(run.id, "SOURCE_REVIEW", payload, "reject-without-reason")
    assert worker.run_once()
    assert facts.get_run(run.id).status == "waiting_for_human"
    assert SourceFacts(facts).get_candidate(run.id, "candidate-1")["status"] == "rejected"
    assert commands.read_model(run.id).source_review.candidates == []


def test_shared_host_cannot_be_approved_as_official_site(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="React", audience="初学者", goal="学习", language="zh"),
        "source-shared", enqueue_start=True,
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0 WHERE id=?", (run.id,),
        )
    worker = Worker(facts.path, provider=FakeProvider())
    assert worker.run_once()
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO source_candidates "
            "(id, run_id, url, title, status, metadata_hash, created_at) "
            "VALUES ('raw-candidate', ?, "
            "'https://raw.githubusercontent.com/user/repo/main/state.md', "
            "'Raw', 'needs_human', 'hash-raw', '2026-01-01T00:00:00+00:00')",
            (run.id,),
        )
    commands = ExecutionStore(facts.path)
    review = commands.read_model(run.id).source_review
    assert review is not None
    commands.accept(run.id, "SOURCE_REVIEW", {
        "action": "approve", "expected_checkpoint_id": review.checkpoint_id,
        "candidate_id": "raw-candidate", "metadata_hash": "hash-raw",
        "reason": "误认为官方文档",
    }, "approve-raw")
    assert worker.run_once()
    assert SourceFacts(facts).get_candidate(run.id, "raw-candidate")["status"] == "needs_human"
    assert any(item.status == "REJECTED" for item in commands.read_model(run.id).commands)
