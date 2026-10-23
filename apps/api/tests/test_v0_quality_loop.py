import pytest
from pydantic import ValidationError

from app.v0.quality_loop import (
    GATE_ORDER,
    GateReport,
    apply_repair,
    check_markdown,
    effective_character_count,
    make_repair_task,
    review_gate,
)
from app.v0.provider import AgentInput, AgentResponse, FakeProvider
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
    run = runner.get(run_id)
    run.constraints_version = 0
    run.source_evidence_version = 0
    with runner.store.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0, constraints_version=0, "
            "source_evidence_version=0 WHERE id=?",
            (run_id,),
        )
        connection.execute(
            "UPDATE snapshots SET projection_json=? WHERE run_id=?",
            (run.model_dump_json(), run_id),
        )
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


def test_new_quality_summary_removes_source_limitation_only_after_source_pass():
    def report(source_status):
        return GateReport(results=[
            GateResult(
                gate="source", status=source_status,
                rule_id="source.claim_support", evidence="exact page excerpt",
                artifact_ref=LESSON_REF,
            ),
        ], findings=[])

    verified = WorkflowNodes._quality_summary(
        None, report("pass"), source_evidence_version=1,
    )
    unverified = WorkflowNodes._quality_summary(
        None, report("fail"), source_evidence_version=1,
    )
    legacy = WorkflowNodes._quality_summary(
        None, report("pass"), source_evidence_version=0,
    )

    assert "未核验事实来源" not in verified.limitations
    assert "未核验事实来源" in unverified.limitations
    assert "未核验事实来源" in legacy.limitations


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


def test_effective_count_strips_markup_and_whitespace_but_keeps_code():
    markdown = (
        "# 标题\r\n\r\n<strong>正文</strong>\r\n"
        "- **列表**与[链接](https://example.com)\r\n"
        "```py\r\nprint(1)\r\n```"
    )
    assert effective_character_count(markdown) == len("标题正文列表与链接print(1)")


def test_effective_count_keeps_markdown_and_html_symbols_inside_fenced_code():
    markdown = "# 标题\n\n```py\na*b <T> `x` _value_\n```"

    assert effective_character_count(markdown) == len("标题a*b<T>`x`_value_")


@pytest.mark.parametrize(
    ("markdown", "visible"),
    [
        (
            "# 标题\n\n````py\n```not-a-close\nvalue\n````",
            "标题```not-a-closevalue",
        ),
        (
            "# 标题\n\n~~~txt\n~~~not-a-close\nvalue\n~~~",
            "标题~~~not-a-closevalue",
        ),
    ],
)
def test_effective_count_only_closes_fence_with_valid_closing_line(
    markdown, visible
):
    assert effective_character_count(markdown) == len(visible)


def test_markdown_structure_accepts_valid_long_fence_with_short_inner_marker():
    report = check_markdown(
        "# 标题\n\n````py\n```not-a-close\nvalue\n````",
        LESSON_REF,
        "lesson-1",
    )

    assert not any(item.rule_id == "markdown.fence" for item in report.findings)


def test_markdown_structure_rejects_unclosed_tilde_fence():
    report = check_markdown(
        "# 标题\n\n~~~py\nvalue",
        LESSON_REF,
        "lesson-1",
    )

    finding = next(item for item in report.findings if item.rule_id == "markdown.fence")
    assert finding.location.line_start == 3


def test_effective_character_minimum_creates_blocking_finding():
    report = check_markdown(
        "# 标题\n\n正文",
        LESSON_REF,
        "lesson-1",
        min_effective_chars=20,
    )
    finding = next(
        item
        for item in report.findings
        if item.rule_id == "lesson.effective_chars.minimum"
    )
    assert finding.category == "structure"
    assert finding.severity == "blocker"
    assert "4" in finding.evidence
    assert "20" in finding.expected


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


def test_unlocatable_reviewer_finding_becomes_manual_gate_error():
    class UnlocatableReviewer(FakeProvider):
        def invoke(self, request):
            if request.role == "reviewer":
                return AgentResponse(role="reviewer", payload={
                    "status": "manual_review",
                    "checks": ["练习需要加强"],
                    "findings": [{
                        "code": "teaching.practice",
                        "category": "teaching",
                        "severity": "major",
                        "evidence": "正文虽然解释概念，但缺少分步练习",
                        "recommendation": "增加一组分步练习",
                    }],
                    "language_risk": "尚未检查",
                    "limitations": ["事实未核验"],
                })
            return super().invoke(request)

    markdown = "# 标题\n\n这里解释概念，也提供了一道练习。"
    report = review_gate(
        V0Runner(UnlocatableReviewer()),
        "rubric",
        LESSON_REF,
        "lesson-1",
        markdown,
        [AgentInput(
            kind="lesson",
            reference=LESSON_REF,
            content={"markdown": markdown},
        )],
    )

    assert report.results[0].status == "error"
    assert report.results[0].rule_id == "rubric.evidence_location"
    assert report.findings == []


def test_exact_reviewer_evidence_still_creates_a_precise_finding():
    class ExactReviewer(FakeProvider):
        def invoke(self, request):
            if request.role == "reviewer":
                return AgentResponse(role="reviewer", payload={
                    "status": "manual_review",
                    "checks": ["练习需要加强"],
                    "findings": [{
                        "code": "teaching.practice",
                        "category": "teaching",
                        "severity": "major",
                        "evidence": "提供了一道练习",
                        "recommendation": "增加一组分步练习",
                    }],
                    "language_risk": "尚未检查",
                    "limitations": ["事实未核验"],
                })
            return super().invoke(request)

    markdown = "# 标题\n\n这里解释概念，也提供了一道练习。"
    report = review_gate(
        V0Runner(ExactReviewer()),
        "rubric",
        LESSON_REF,
        "lesson-1",
        markdown,
        [AgentInput(
            kind="lesson",
            reference=LESSON_REF,
            content={"markdown": markdown},
        )],
    )

    assert report.results[0].status == "fail"
    assert report.findings[0].location.line_start == 3
    assert report.findings[0].evidence == "提供了一道练习"


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


class AdvancingFindingProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.humanizer_calls = 0
        self.repair_source_versions = []

    def invoke(self, request):
        if request.role == "writer":
            response = super().invoke(request)
            response.payload["markdown"] = (
                "# 标题\n\n面向开发。\n\n执行操作。\n\n练习：复述本章内容。"
            )
            return response
        if request.role == "reviewer" and request.goal.startswith("humanizer"):
            self.humanizer_calls += 1
            findings = {
                1: [
                    {
                        "code": "audience-reference",
                        "category": "language",
                        "severity": "minor",
                        "evidence": "面向开发。",
                        "recommendation": "改为“面向开发者。”",
                    }
                ],
                2: [
                    {
                        "code": "verb-object",
                        "category": "language",
                        "severity": "minor",
                        "evidence": "执行操作。",
                        "recommendation": "改为“执行这项操作。”",
                    }
                ],
                3: [],
            }[self.humanizer_calls]
            return AgentResponse(
                role="reviewer",
                payload={
                    "status": "ready" if not findings else "manual_review",
                    "checks": ["中文表达检查"],
                    "findings": findings,
                    "language_risk": "无" if not findings else "存在局部表达问题",
                    "limitations": ["仅检查中文表达"],
                },
            )
        if request.role == "repair":
            lesson_input = next(item for item in request.inputs if item.kind == "lesson")
            self.repair_source_versions.append(lesson_input.reference.version)
            replacement = (
                "面向开发者。"
                if len(self.repair_source_versions) == 1
                else "执行这项操作。"
            )
            response = super().invoke(request)
            response.payload["markdown"] = replacement
            return response
        return super().invoke(request)


def test_failed_verification_advances_to_candidate_finding(tmp_path):
    provider = AdvancingFindingProvider()
    runner = V0Runner(provider, FactStore(tmp_path / "facts.sqlite3"))
    run = runner.create(
        CourseInput(topic="Python", audience="初学者", goal="变量", language="zh"),
        request_key="advance-candidate-finding",
    )

    execute_legacy(runner, run.id)

    result = runner.get(run.id)
    assert provider.repair_source_versions == [1, 2]
    assert "面向开发者。" in result.lesson.markdown
    assert "执行这项操作。" in result.lesson.markdown
    assert result.stages[5].status == "succeeded"


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
