from app.v0.provider import AgentResponse, FakeProvider
from app.v0.schemas import CourseInput
from app.v0.storage import FactStore
from app.v0.worker import Worker


class ManualThenReady(FakeProvider):
    def __init__(self):
        super().__init__()
        self.reviewer_calls = 0

    def invoke(self, request):
        if request.role == "reviewer":
            self.reviewer_calls += 1
            if self.reviewer_calls == 1:
                return AgentResponse(role="reviewer", payload={
                    "status": "manual_review",
                    "checks": ["需要人工确认"],
                    "findings": [],
                    "language_risk": "需人工复读",
                    "limitations": ["未核验事实来源"],
                })
        return super().invoke(request)


def make_run(facts: FactStore):
    run, _ = facts.create_run(
        CourseInput(
            topic="变量", audience="初学者", goal="解释变量", language="zh",
            expected_chapters=1, min_effective_chars=1,
        ),
        "quality-gate-run",
        enqueue_start=True,
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0, "
            "source_evidence_version=0 WHERE id=?", (run.id,),
        )
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run.id,))
    return run


def accept_payload(review):
    return {
        "action": "accept",
        "reason": "接受本章人工风险",
        "quality_ref": review.quality_ref.model_dump(mode="json"),
        "lesson_ref": review.lesson_ref.model_dump(mode="json"),
        "expected_checkpoint_id": review.checkpoint_id,
    }


def retry_payload(review):
    return {
        "action": "retry",
        "quality_ref": review.quality_ref.model_dump(mode="json"),
        "lesson_ref": review.lesson_ref.model_dump(mode="json"),
        "expected_checkpoint_id": review.checkpoint_id,
    }


def test_quality_gate_interrupts_and_accepts_risk(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run = make_run(facts)
    provider = ManualThenReady()
    worker = Worker(facts.path, provider=provider, owner="worker-a")
    assert worker.run_once()
    commands = worker.execution

    current = facts.get_run(run.id)
    assert current.status == "waiting_for_human"
    assert current.stages[5].status == "waiting_for_human"
    with facts.connect() as connection:
        execution = connection.execute(
            "SELECT status, pending_interrupt_id FROM node_executions "
            "WHERE run_id=? AND node='quality_gate' ORDER BY rowid DESC LIMIT 1",
            (run.id,),
        ).fetchone()
    assert execution["status"] == "WAITING"
    assert execution["pending_interrupt_id"]

    review = commands.read_model(run.id).quality_review
    assert review is not None and review.status == "pending"
    assert review.quality_ref is not None

    commands.accept(
        run.id, "QUALITY_REVIEW", accept_payload(review), "quality-accept",
    )
    assert worker.run_once()
    resumed = facts.get_run(run.id)
    assert resumed.stages[5].status == "succeeded"
    assert resumed.status == "waiting_for_human"


def test_quality_gate_retry_rechecks_same_lesson(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run = make_run(facts)
    provider = ManualThenReady()
    worker = Worker(facts.path, provider=provider, owner="worker-a")
    assert worker.run_once()
    commands = worker.execution
    review = commands.read_model(run.id).quality_review
    assert review is not None

    commands.accept(
        run.id, "QUALITY_REVIEW", retry_payload(review), "quality-retry",
    )
    assert worker.run_once()
    resumed = facts.get_run(run.id)
    assert provider.reviewer_calls >= 2
    assert resumed.stages[5].status == "succeeded"
    assert resumed.status == "waiting_for_human"


class VerificationGateProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.humanizer_calls = 0

    def invoke(self, request):
        if request.role == "reviewer" and request.goal.startswith("humanizer"):
            self.humanizer_calls += 1
            if self.humanizer_calls == 1:
                return AgentResponse(role="reviewer", payload={
                    "status": "manual_review",
                    "checks": ["有填充句"],
                    "findings": [{
                        "code": "humanizer.language.filler",
                        "category": "language",
                        "severity": "minor",
                        "evidence": "变量保存一个值",
                        "recommendation": "删去空泛句并保留事实",
                    }],
                    "language_risk": "需修订",
                    "limitations": ["表达问题"],
                })
            return AgentResponse(role="reviewer", payload={
                "status": "manual_review",
                "checks": ["表达仍需人工确认"],
                "findings": [],
                "language_risk": "需人工",
                "limitations": ["表达问题"],
            })
        if request.role == "repair":
            return AgentResponse(role="repair", payload={
                "title": "Python 变量入门",
                "markdown": "变量可以保存并更新一个值。练习：修改变量并观察输出。",
            })
        return super().invoke(request)


def test_verification_gate_accepts_candidate(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run = make_run(facts)
    provider = VerificationGateProvider()
    worker = Worker(facts.path, provider=provider, owner="worker-a")
    assert worker.run_once()
    commands = worker.execution

    review = commands.read_model(run.id).quality_review
    assert review is not None and review.status == "pending"
    assert review.lesson_ref.kind == "lesson"
    with facts.connect() as connection:
        execution = connection.execute(
            "SELECT status FROM node_executions WHERE run_id=? "
            "AND node='quality_gate' ORDER BY rowid DESC LIMIT 1",
            (run.id,),
        ).fetchone()
    assert execution["status"] == "WAITING"

    commands.accept(
        run.id, "QUALITY_REVIEW", accept_payload(review), "candidate-accept",
    )
    assert worker.run_once()
    resumed = facts.get_run(run.id)
    assert resumed.stages[5].status == "succeeded"
    assert resumed.lesson.markdown.startswith("# Python 变量入门")
    assert "变量可以保存并更新一个值" in resumed.lesson.markdown
