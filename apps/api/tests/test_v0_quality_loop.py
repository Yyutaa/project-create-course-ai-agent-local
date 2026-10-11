import pytest
from pydantic import ValidationError

from app.v0.quality_loop import (
    GATE_ORDER,
    apply_repair,
    check_markdown,
    make_repair_task,
    review_gate,
)
from app.v0.provider import AgentInput, FakeProvider
from app.v0.runner import V0Runner
from app.v0.storage import FactStore
from app.v0.graph import WorkflowNodes
from app.v0.agents import AGENT_DEFINITIONS
from app.v0.schemas import (
    ArtifactRef,
    CourseInput,
    Finding,
    FindingLocation,
    GateResult,
    GraphState,
    LessonDraft,
    LoopCounts,
)


def execute_legacy(runner: V0Runner, run_id: str) -> None:
    # Quality-loop fixtures represent pre-gate Runs; Mission gate is tested separately.
    with runner.store.connect() as connection:
        connection.execute("UPDATE runs SET mission_review_required=0 WHERE id=?", (run_id,))
    runner.execute(run_id)


LESSON_REF = ArtifactRef(
    run_id="run-1",
    artifact_id="lesson-1",
    version=2,
    kind="lesson",
    content_hash="sha256-value",
)


def test_gate_order_is_deterministic_then_rubric_then_humanizer():
    assert GATE_ORDER == ("deterministic", "rubric", "humanizer")


def test_gate_result_requires_an_explicit_status_and_evidence():
    result = GateResult(
        gate="deterministic",
        status="fail",
        rule_id="markdown.h1",
        evidence="第 1 行缺少一级标题",
        artifact_ref=LESSON_REF,
    )
    assert result.status == "fail"
    assert result.artifact_ref.version == 2
    with pytest.raises(ValidationError):
        GateResult(gate="deterministic", status="unknown", rule_id="x", evidence="x")
    with pytest.raises(ValidationError):
        GateResult(gate="deterministic", status="pass", rule_id="x", evidence="x")


def test_finding_is_tied_to_one_artifact_version_and_location():
    finding = Finding(
        finding_id="finding-1",
        run_id="run-1",
        gate="deterministic",
        rule_id="markdown.h1",
        artifact_ref=LESSON_REF,
        location=FindingLocation(
            lesson_id="lesson-1", line_start=1, line_end=1, excerpt_hash="excerpt-sha256"
        ),
        category="structure",
        severity="major",
        evidence="缺少标题",
        expected="首行应为一级标题",
    )
    assert finding.artifact_ref.version == 2
    assert finding.location.line_start == 1
    with pytest.raises(ValidationError):
        Finding.model_validate({**finding.model_dump(), "run_id": "other"})


def test_markdown_structure_reports_repeatable_locations():
    report = check_markdown("正文\n```python\nprint(1)", LESSON_REF, "lesson-1")
    assert [item.rule_id for item in report.findings] == ["markdown.h1", "markdown.fence"]
    assert report.findings[0].location.line_start == 1
    assert report.findings[1].location.line_start == 2
    assert all(item.artifact_ref == LESSON_REF for item in report.findings)


def test_markdown_structure_passes_valid_minimal_lesson():
    report = check_markdown("# 标题\n\n正文。", LESSON_REF, "lesson-1")
    assert report.results[0].status == "pass"
    assert report.findings == []


class GateProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.requests = []

    def invoke(self, request):
        if request.role == "reviewer":
            self.requests.append(request)
        return super().invoke(request)


def test_model_gates_have_separate_instructions_and_humanizer_sees_only_lesson():
    provider = GateProvider()
    runner = V0Runner(provider)
    rubric = review_gate(
        runner,
        "rubric",
        LESSON_REF,
        "lesson-1",
        "# 标题\n\n讲解与练习。",
        [
            AgentInput(
                kind="lesson",
                reference=LESSON_REF,
                content={"markdown": "# 标题\n\n讲解与练习。"},
            )
        ],
    )
    humanizer = review_gate(
        runner, "humanizer", LESSON_REF, "lesson-1", "# 标题\n\n讲解与练习。", []
    )
    assert rubric.results[0].status == "pass"
    assert humanizer.results[0].status == "pass"
    assert "教学" in " ".join(provider.requests[0].instructions)
    assert "表达" in " ".join(provider.requests[1].instructions)
    assert [item.kind for item in provider.requests[1].inputs] == ["lesson"]


def test_repair_task_contains_only_exact_problem_line_and_patch_keeps_other_lines():
    assert "单行" in AGENT_DEFINITIONS["repair"].goal
    original = LessonDraft(
        title="一章",
        lesson_id="lesson-1",
        markdown="正文\n第二行保持原样\n第三行也保持原样",
    )
    finding = check_markdown(original.markdown, LESSON_REF, "lesson-1").findings[0]
    task = make_repair_task(finding, original.markdown)
    assert task.excerpt == "正文"
    assert "第二行" not in task.model_dump_json()
    candidate = apply_repair(task, "# 一章", original)
    assert candidate.markdown == "# 一章\n第二行保持原样\n第三行也保持原样"
    assert original.markdown.startswith("正文")


def test_repair_rejects_stale_source_excerpt():
    original = LessonDraft(title="一章", markdown="正文\n保留")
    finding = check_markdown(original.markdown, LESSON_REF, "lesson-1").findings[0]
    task = make_repair_task(finding, original.markdown)
    with pytest.raises(ValueError, match="片段"):
        apply_repair(
            task, "# 一章", original.model_copy(update={"markdown": "已变更\n保留"})
        )


def test_candidate_version_is_not_active_until_independent_acceptance(tmp_path):
    runner = V0Runner(FakeProvider(), FactStore(tmp_path / "facts.sqlite3"))
    run = runner.create_once(
        CourseInput(topic="Python", audience="初学者", goal="变量", language="zh"),
        "quality-candidate-test",
    )[0]
    execute_legacy(runner, run.id)
    original = runner.get(run.id).lesson
    original_ref = runner._source_refs(run.id, ("lesson",))[0]
    candidate = original.model_copy(update={"markdown": original.markdown + "\n新增修订"})
    candidate_ref = runner._persist_repair_candidate(run.id, candidate, [original_ref])
    assert candidate_ref.version == original_ref.version + 1
    assert runner.get(run.id).lesson == original
    assert V0Runner(FakeProvider(), runner.store).get(run.id).lesson == original
    runner._accept_repair_candidate(run.id, candidate_ref)
    assert V0Runner(FakeProvider(), runner.store).get(run.id).lesson == candidate


class RepairingProvider(FakeProvider):
    def __init__(self, replacement):
        super().__init__()
        self.replacement = replacement
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        if request.role == "writer":
            response = super().invoke(request)
            response.payload["markdown"] = "标题缺失\n\n正文和练习。"
            return response
        if request.role == "repair":
            response = super().invoke(request)
            response.payload["markdown"] = self.replacement
            return response
        return super().invoke(request)


def test_repair_candidate_requires_independent_verification(tmp_path):
    provider = RepairingProvider("# 修好的标题")
    runner = V0Runner(provider, FactStore(tmp_path / "facts.sqlite3"))
    run = runner.create(
        CourseInput(topic="Python", audience="初学者", goal="变量", language="zh"),
        request_key="verify-candidate",
    )
    execute_legacy(runner, run.id)
    result = runner.get(run.id)
    assert result.status == "waiting_for_human"
    assert result.stages[5].status == "succeeded"
    assert result.quality.resolved_finding_ids
    from app.v0.delivery import DeliveryStore

    evidence = DeliveryStore(runner.store.path).read(run.id)
    assert evidence.verifications
    assert all(item.finding_id == result.quality.resolved_finding_ids[0]
               for item in evidence.verifications)
    from app.v0.graph import WorkflowNodes
    from app.v0.quality_loop import GateReport

    next_summary = WorkflowNodes._quality_summary(
        result.quality, GateReport(result.quality.verification_results[:1], [])
    )
    assert next_summary.verification_links == result.quality.verification_links
    assert [request.role for request in provider.requests].count("repair") == 1
    assert [request.role for request in provider.requests].count("reviewer") == 2
    lessons = [item for item in result.artifacts if item.kind == "lesson"]
    assert [item.version for item in lessons] == [1, 2]
    assert (
        runner._load_artifact(lessons[0].artifact_id, 1)
        .content["markdown"]
        .startswith("标题缺失")
    )
    assert result.lesson.markdown.startswith("# 修好的标题")
    latest_quality = [item for item in result.artifacts if item.kind == "quality"][-1]
    assert [ref.kind for ref in latest_quality.source_refs[:3]] == [
        "mission",
        "blueprint",
        "lesson",
    ]


def test_repeated_failed_verification_exhausts_finding_budget(tmp_path):
    provider = RepairingProvider("仍然没有标题")
    runner = V0Runner(provider, FactStore(tmp_path / "facts.sqlite3"))
    run = runner.create(
        CourseInput(topic="Python", audience="初学者", goal="变量", language="zh"),
        request_key="budget-candidate",
    )
    execute_legacy(runner, run.id)
    result = runner.get(run.id)
    assert result.status == "waiting_for_human"
    assert result.stages[5].status == "waiting_for_human"
    assert "Candidate 未通过独立验证" in result.stages[5].failure_reason
    assert [request.role for request in provider.requests].count("repair") == 2
    assert result.lesson.markdown.startswith("标题缺失")


def test_repair_budget_has_independent_finding_and_run_caps():
    nodes = WorkflowNodes(V0Runner(FakeProvider()))
    assert nodes._has_repair_budget(
        GraphState(
            run_id="r", loop_counts=LoopCounts(repair_attempts=2, finding_attempts={"a": 1})
        ),
        "a",
    )
    assert not nodes._has_repair_budget(
        GraphState(
            run_id="r", loop_counts=LoopCounts(repair_attempts=2, finding_attempts={"a": 2})
        ),
        "a",
    )
    assert not nodes._has_repair_budget(
        GraphState(
            run_id="r",
            loop_counts=LoopCounts(
                repair_attempts=3, finding_attempts={"a": 1, "b": 1, "c": 1}
            ),
        ),
        "new-finding",
    )


def test_reviewer_schema_failure_does_not_expose_raw_payload(tmp_path):
    class InvalidReviewer(FakeProvider):
        def invoke(self, request):
            if request.role == "reviewer":
                response = super().invoke(request)
                response.payload["status"] = "SECRET-RAW-PAYLOAD"
                return response
            return super().invoke(request)

    runner = V0Runner(InvalidReviewer(), FactStore(tmp_path / "facts.sqlite3"))
    run = runner.create(
        CourseInput(topic="Python", audience="初学者", goal="变量", language="zh"),
        request_key="bad-reviewer",
    )
    execute_legacy(runner, run.id)
    result = runner.get(run.id)
    assert result.stages[5].status == "failed"
    assert "SECRET-RAW-PAYLOAD" not in result.stages[5].failure_reason
