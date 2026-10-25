import pytest

from app.v0.graph import (
    WorkflowNodes,
    build_graph,
    route_after_generation,
    route_after_intake,
    route_after_quality,
    route_after_repair,
    route_after_verification,
    route_after_release,
    route_start,
)
from app.v0.batching import assign_blueprint_ids, build_batch_plan
from app.v0.provider import FakeProvider
from app.v0.provider import AgentResponse, ProviderError
from app.v0.quality_loop import check_markdown
from app.v0.runner import V0Runner
from app.v0.schemas import (
    ArtifactRef,
    BlueprintDraft,
    BlueprintLesson,
    CourseInput,
    Finding,
    FindingLocation,
    GraphState,
    LoopCounts,
    QualitySummary,
    ReleaseDecision,
)
from app.v0.storage import FactStore


COURSE = CourseInput(
    topic="Python 基础",
    audience="初学者",
    goal="完成四章练习",
    language="zh",
)


def execute_legacy(runner: V0Runner, run_id: str) -> None:
    # Existing graph tests exercise downstream routes as a pre-gate Run.
    run = runner.get(run_id)
    run.constraints_version = 0
    run.source_evidence_version = 0
    run.context_contract_version = 0
    run.langgraph_flow_version = 0
    with runner.store.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0, constraints_version=0, "
            "source_evidence_version=0, context_contract_version=0, langgraph_flow_version=0 WHERE id=?",
            (run_id,),
        )
        connection.execute(
            "UPDATE snapshots SET projection_json=? WHERE run_id=?",
            (run.model_dump_json(), run_id),
        )
    runner.execute(run_id)


def disable_source_evidence(runner: V0Runner, run_id: str) -> None:
    run = runner.get(run_id)
    run.source_evidence_version = 0
    run.context_contract_version = 0
    run.langgraph_flow_version = 0
    with runner.store.connect() as connection:
        connection.execute(
            "UPDATE runs SET source_evidence_version=0, context_contract_version=0, langgraph_flow_version=0 "
            "WHERE id=?", (run_id,),
        )
        connection.execute(
            "UPDATE snapshots SET projection_json=? WHERE run_id=?",
            (run.model_dump_json(), run_id),
        )


class MultiLessonProvider(FakeProvider):
    def __init__(
        self,
        lesson_count=4,
        fail_writer_call=None,
        manual_review=False,
        malformed_writer_call=None,
    ):
        super().__init__()
        self.lesson_count = lesson_count
        self.fail_writer_call = fail_writer_call
        self.manual_review = manual_review
        self.malformed_writer_call = malformed_writer_call
        self.blueprint_requests = []
        self.mission_requests = []
        self.writer_requests = []
        self.reviewer_requests = []

    def invoke(self, request):
        if request.role == "mission":
            self.mission_requests.append(request)
        if request.role == "blueprint":
            self.blueprint_requests.append(request)
            return AgentResponse(
                role="blueprint",
                payload={
                    "lessons": [
                        {
                            "title": f"第 {index + 1} 章",
                            "learning_goal": f"完成目标 {index + 1}",
                            "evidence": f"证据 {index + 1}",
                        }
                        for index in range(self.lesson_count)
                    ]
                },
            )
        if request.role == "writer":
            self.writer_requests.append(request)
            if self.fail_writer_call == len(self.writer_requests):
                raise ProviderError("writer 指定批次失败")
            brief = request.inputs[1].content["current_lesson_brief"]
            return AgentResponse(
                role="writer",
                payload={
                    "title": brief["title"],
                    "markdown": (
                        "缺少标题"
                        if self.malformed_writer_call == len(self.writer_requests)
                        else f"# {brief['title']}\n\n候选正文。"
                    ),
                    "continuity_summary": f"已完成{brief['title']}。",
                },
            )
        if request.role == "reviewer":
            self.reviewer_requests.append(request)
        if request.role == "reviewer" and self.manual_review:
            return AgentResponse(
                role="reviewer",
                payload=QualitySummary(
                    status="manual_review",
                    checks=["需要人工核对"],
                    language_risk="需要人工复读",
                    limitations=["事实未核验"],
                ).model_dump(),
            )
        return super().invoke(request)


def test_legacy_run_mission_omits_generation_constraint_defaults(tmp_path):
    provider = MultiLessonProvider(lesson_count=1)
    runner = V0Runner(provider, store=FactStore(tmp_path / "facts.sqlite3"))
    run = runner.create(COURSE, request_key="legacy-mission-context")

    execute_legacy(runner, run.id)

    content = provider.mission_requests[0].inputs[0].content
    assert "expected_chapters" not in content
    assert "min_effective_chars" not in content
    assert "token_limit" not in content


@pytest.mark.parametrize("lesson_count", [11, 13])
def test_blueprint_chapter_count_allows_one_chapter_tolerance(
    tmp_path, lesson_count
):
    provider = MultiLessonProvider(lesson_count=lesson_count)
    runner = V0Runner(provider, store=FactStore(tmp_path / "facts.sqlite3"))
    created = runner.create(COURSE, request_key=f"chapter-boundary-{lesson_count}")
    disable_source_evidence(runner, created.id)
    with runner.store.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0 WHERE id=?", (created.id,)
        )

    runner.execute(created.id)

    run = runner.get(created.id)
    assert run.batch_plan is not None
    assert run.stages[2].status == "succeeded"
    assert run.stages[3].status == "succeeded"
    blueprint_input = provider.blueprint_requests[0].inputs[0].content
    assert blueprint_input["generation_constraints"] == {"expected_chapters": 12}
    assert blueprint_input["source_policy"] == "仅允许使用公开官方资料"
    assert "topic" not in blueprint_input
    assert provider.writer_requests[0].inputs[0].content == {
        "generation_constraints": {"min_effective_chars": 12_000},
        "source_policy": "仅允许使用公开官方资料",
    }


def test_new_run_without_source_runtime_waits_before_blueprint_artifact(tmp_path):
    runner = V0Runner(FakeProvider(), store=FactStore(tmp_path / "facts.sqlite3"))
    created = runner.create(COURSE, request_key="source-runtime-required")
    with runner.store.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0 WHERE id=?", (created.id,)
        )

    runner.execute(created.id)

    run = runner.get(created.id)
    assert run.stages[2].status == "waiting_for_human"
    assert run.blueprint is None
    assert run.stages[2].failure_reason == "source_evidence_insufficient"


def test_blueprint_chapter_count_outlier_waits_before_batch_plan(tmp_path):
    provider = MultiLessonProvider(lesson_count=14)
    store = FactStore(tmp_path / "facts.sqlite3")
    runner = V0Runner(provider, store=store)
    created = runner.create(COURSE, request_key="chapter-outlier")
    disable_source_evidence(runner, created.id)
    with store.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0 WHERE id=?", (created.id,)
        )

    runner.execute(created.id)

    run = runner.get(created.id)
    assert run.status == "waiting_for_human"
    assert run.stages[3].status == "waiting_for_human"
    assert run.stages[3].failure_reason == "blueprint_chapter_deviation"
    assert run.batch_plan is None
    assert provider.writer_requests == []
    with store.connect() as connection:
        event = connection.execute(
            "SELECT artifact_id, artifact_version FROM events "
            "WHERE run_id=? AND type='blueprint.chapter_count_observed'",
            (created.id,),
        ).fetchone()
    blueprint = next(item for item in run.artifacts if item.kind == "blueprint")
    assert (event["artifact_id"], event["artifact_version"]) == (
        blueprint.artifact_id,
        blueprint.version,
    )


def test_short_lesson_waits_for_human_without_auto_repair(tmp_path):
    provider = MultiLessonProvider(lesson_count=1, malformed_writer_call=1)
    store = FactStore(tmp_path / "facts.sqlite3")
    runner = V0Runner(provider, store=store)
    created = runner.create(
        CourseInput(
            topic="Python 基础",
            audience="初学者",
            goal="完成练习",
            language="zh",
            expected_chapters=1,
            min_effective_chars=20,
        ),
        request_key="short-lesson",
    )
    disable_source_evidence(runner, created.id)
    with store.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0 WHERE id=?", (created.id,)
        )

    runner.execute(created.id)

    run = runner.get(created.id)
    assert run.status == "waiting_for_human"
    assert run.stages[5].failure_reason == "lesson_effective_chars_below_minimum"
    assert run.quality is not None
    assert run.quality.repair_tasks == []
    assert any(
        item.rule_id == "lesson.effective_chars.minimum"
        for item in run.quality.evidence_findings
    )
    assert not any(item.producer_role == "repair" for item in run.artifacts)


def test_verification_character_shortage_waits_without_second_repair(tmp_path):
    class ShortCandidateProvider(MultiLessonProvider):
        def __init__(self):
            super().__init__(lesson_count=1)
            self.repair_requests = []

        def invoke(self, request):
            response = super().invoke(request)
            if request.role == "writer":
                response.payload["markdown"] = "正文" * 10
            elif request.role == "repair":
                self.repair_requests.append(request)
                response.payload["markdown"] = "# 短"
            return response

    provider = ShortCandidateProvider()
    runner = V0Runner(provider, store=FactStore(tmp_path / "facts.sqlite3"))
    run = runner.create(
        CourseInput(
            topic="Python",
            audience="初学者",
            goal="完成练习",
            language="zh",
            expected_chapters=1,
            min_effective_chars=20,
        ),
        request_key="short-verification-candidate",
    )
    disable_source_evidence(runner, run.id)
    with runner.store.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0 WHERE id=?", (run.id,)
        )

    runner.execute(run.id)

    result = runner.get(run.id)
    assert result.status == "waiting_for_human"
    assert result.stages[5].failure_reason == "lesson_effective_chars_below_minimum"
    assert len(provider.repair_requests) == 1


def test_recover_quality_keeps_character_shortage_out_of_repair():
    runner = V0Runner(FakeProvider())
    run = runner.create(COURSE)
    lesson_ref = ArtifactRef(
        run_id=run.id,
        artifact_id="lesson-1",
        version=1,
        kind="lesson",
        content_hash="lesson-hash",
    )
    quality_ref = ArtifactRef(
        run_id=run.id,
        artifact_id="quality-1",
        version=1,
        kind="quality",
        content_hash="quality-hash",
    )
    report = check_markdown(
        "# 短", lesson_ref, "lesson-1", min_effective_chars=20
    )
    current = runner._runs[run.id]
    current.blueprint = BlueprintDraft(lessons=[BlueprintLesson(
        title="一章",
        learning_goal="完成练习",
        evidence="提交结果",
        lesson_id="lesson-1",
    )])
    current.quality = WorkflowNodes._quality_summary(None, report)
    state = GraphState(
        run_id=run.id,
        current_node="quality",
        artifact_refs={
            "lesson:lesson-1": lesson_ref,
            "quality": quality_ref,
        },
    )

    result = WorkflowNodes(runner).recover_quality(state, {
        "type": "artifact.created",
        "artifact_id": quality_ref.artifact_id,
        "artifact_version": quality_ref.version,
    })

    assert result["last_outcome"] == "waiting_for_human"
    assert runner.get(run.id).stages[5].failure_reason == (
        "lesson_effective_chars_below_minimum"
    )


def test_recover_verification_keeps_character_shortage_out_of_repair():
    runner = V0Runner(FakeProvider())
    run = runner.create(COURSE)
    candidate_ref = ArtifactRef(
        run_id=run.id,
        artifact_id="lesson-1",
        version=2,
        kind="lesson",
        content_hash="candidate-hash",
    )
    quality_ref = ArtifactRef(
        run_id=run.id,
        artifact_id="quality-1",
        version=2,
        kind="quality",
        content_hash="quality-hash",
    )
    report = check_markdown(
        "# 短", candidate_ref, "lesson-1", min_effective_chars=20
    )
    current = runner._runs[run.id]
    current.quality = WorkflowNodes._quality_summary(None, report)
    state = GraphState(
        run_id=run.id,
        current_node="verification",
        active_finding_id="original-finding",
        artifact_refs={"candidate": candidate_ref, "quality": quality_ref},
    )

    result = WorkflowNodes(runner).recover_verification(state, {
        "type": "artifact.created",
        "artifact_id": quality_ref.artifact_id,
        "artifact_version": quality_ref.version,
    })

    assert result["last_outcome"] == "waiting_for_human"
    assert runner.get(run.id).stages[5].failure_reason == (
        "lesson_effective_chars_below_minimum"
    )


def test_recover_verification_advances_to_candidate_finding():
    runner = V0Runner(FakeProvider())
    run = runner.create(COURSE)
    candidate_ref = ArtifactRef(
        run_id=run.id,
        artifact_id="lesson-1",
        version=2,
        kind="lesson",
        content_hash="candidate-hash",
    )
    quality_ref = ArtifactRef(
        run_id=run.id,
        artifact_id="quality-1",
        version=2,
        kind="quality",
        content_hash="quality-hash",
    )
    next_finding = Finding(
        finding_id="candidate-finding",
        run_id=run.id,
        gate="humanizer",
        rule_id="language.next",
        artifact_ref=candidate_ref,
        location=FindingLocation(
            lesson_id="lesson-1",
            line_start=2,
            line_end=2,
            excerpt_hash="excerpt-hash",
        ),
        category="language",
        severity="minor",
        evidence="需要修订",
        expected="改为自然表达",
    )
    runner._runs[run.id].quality = QualitySummary(
        status="manual_review",
        checks=["humanizer:language.next:fail"],
        language_risk="存在局部表达问题",
        limitations=["仅检查中文表达"],
        evidence_findings=[next_finding],
    )
    state = GraphState(
        run_id=run.id,
        current_node="verification",
        active_finding_id="original-finding",
        artifact_refs={"candidate": candidate_ref, "quality": quality_ref},
        loop_counts=LoopCounts(
            repair_attempts=1,
            finding_attempts={"original-finding": 1},
        ),
    )

    result = WorkflowNodes(runner).recover_verification(state, {
        "type": "artifact.created",
        "artifact_id": quality_ref.artifact_id,
        "artifact_version": quality_ref.version,
    })

    assert result["last_outcome"] == "succeeded"
    assert result["exit_reason"] == "repair_needed"
    assert result["active_finding_id"] == "candidate-finding"


def state(**updates):
    return GraphState(run_id="run-1").model_copy(update=updates)


def test_graph_declares_seven_stages_and_quality_loop_nodes():
    compiled = build_graph(V0Runner(FakeProvider()))
    graph = compiled.get_graph()

    assert set(graph.nodes) == {
        "__start__",
        "intake",
        "mission",
        "mission_gate",
        "blueprint",
        "batch_plan",
        "generation",
        "quality",
        "repair",
        "verification",
        "release",
        "route_error",
        "__end__",
    }


@pytest.mark.parametrize(
    ("outcome", "target"),
    [
        ("succeeded", "mission"),
        ("failed", "__end__"),
        ("waiting_for_human", "__end__"),
        ("stopped", "route_error"),
        ("unknown", "route_error"),
    ],
)
def test_standard_router_is_exhaustive(outcome, target):
    assert route_after_intake(state(last_outcome=outcome)) == target


@pytest.mark.parametrize(
    ("outcome", "reason", "target"),
    [
        ("succeeded", "more_batches", "generation"),
        ("succeeded", "all_batches_complete", "quality"),
        ("succeeded", None, "route_error"),
        ("failed", None, "__end__"),
        ("waiting_for_human", None, "__end__"),
        ("stopped", None, "route_error"),
        ("unknown", None, "route_error"),
    ],
)
def test_generation_router_distinguishes_repeat_complete_and_terminal_states(
    outcome, reason, target
):
    assert (
        route_after_generation(state(last_outcome=outcome, exit_reason=reason)) == target
    )


def test_generation_cursor_invariant_routes_to_internal_error():
    runner = V0Runner(FakeProvider())
    created = runner.create(COURSE)
    blueprint = assign_blueprint_ids(
        BlueprintDraft(
            lessons=[
                BlueprintLesson(title="第一章", learning_goal="完成", evidence="通过")
            ]
        )
    )
    runner._runs[created.id].blueprint = blueprint
    runner._runs[created.id].batch_plan = build_batch_plan(blueprint)

    result = WorkflowNodes(runner).generation(
        GraphState(run_id=created.id, batch_cursor=1)
    )

    invalid = GraphState(run_id=created.id).model_copy(update=result)
    assert invalid.last_outcome == "unknown"
    assert route_after_generation(invalid) == "route_error"


def test_quality_and_release_routers_preserve_human_control():
    assert route_after_quality(state(last_outcome="succeeded", exit_reason="all_lessons_ready")) == "release"
    assert route_after_quality(state(last_outcome="succeeded", exit_reason="repair_needed")) == "repair"
    assert route_after_repair(state(last_outcome="succeeded")) == "verification"
    assert route_after_verification(state(last_outcome="succeeded", exit_reason="candidate_accepted")) == "quality"
    assert route_after_verification(state(last_outcome="succeeded", exit_reason="repair_needed")) == "repair"
    assert route_after_verification(state(last_outcome="unknown")) == "route_error"
    assert route_after_quality(state(last_outcome="waiting_for_human")) == "__end__"
    assert route_after_release(state(last_outcome="waiting_for_human")) == "__end__"
    assert route_after_release(state(last_outcome="succeeded")) == "__end__"
    assert route_after_release(state(last_outcome="stopped")) == "__end__"
    assert route_after_release(state(last_outcome="unknown")) == "route_error"


def test_start_router_accepts_only_new_run_or_explicit_release_decision():
    assert route_start(state()) == "intake"
    assert (
        route_start(state(current_node="release", approval_status="prepare"))
        == "release"
    )
    assert (
        route_start(state(current_node="release", approval_status="stop")) == "release"
    )
    assert (
        route_start(state(current_node="mission", approval_status="not_requested"))
        == "route_error"
    )


def test_two_batches_update_ledger_and_pass_previous_summary(tmp_path):
    provider = MultiLessonProvider()
    runner = V0Runner(provider, store=FactStore(tmp_path / "facts.sqlite3"))
    created = runner.create(COURSE, request_key="two-batches")

    execute_legacy(runner, created.id)
    run = runner.get(created.id)

    assert run.status == "waiting_for_human"
    assert run.batch_plan is not None
    assert len(run.batch_plan.batches) == 2
    assert len(run.batch_plan.continuity_ledger) == 4
    assert len(provider.writer_requests) == 4
    second_batch_first = provider.writer_requests[3]
    assert (
        second_batch_first.inputs[2].content["previous_lesson_summary"]
        == "已完成第 3 章。"
    )


def test_new_run_repairs_only_current_humanizer_finding_and_verifies(tmp_path):
    class CurrentFindingProvider(FakeProvider):
        def __init__(self):
            super().__init__()
            self.requests = []
            self.humanizer_calls = 0

        def invoke(self, request):
            self.requests.append(request)
            if request.role == "reviewer" and request.goal.startswith("humanizer"):
                self.humanizer_calls += 1
                if self.humanizer_calls == 1:
                    return AgentResponse(role="reviewer", payload={
                        "status": "manual_review", "checks": ["有填充句"],
                        "findings": [{
                            "code": "humanizer.language.filler", "category": "language",
                            "severity": "minor", "evidence": "变量保存一个值",
                            "recommendation": "删去空泛句并保留事实",
                        }],
                        "language_risk": "需修订", "limitations": ["表达问题"],
                    })
            if request.role == "repair":
                return AgentResponse(role="repair", payload={
                    "title": "Python 变量入门",
                    "markdown": "变量可以保存并更新一个值。练习：修改变量并观察输出。",
                })
            return super().invoke(request)

    provider = CurrentFindingProvider()
    facts = FactStore(tmp_path / "facts.sqlite3")
    runner = V0Runner(provider, store=facts)
    created = runner.create(CourseInput(
        topic="Python 变量", audience="初学者", goal="解释变量", language="zh",
        expected_chapters=1, min_effective_chars=1,
    ), request_key="new-role-pack")
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0, source_evidence_version=0 "
            "WHERE id=?", (created.id,),
        )
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (created.id,))

    runner.execute(created.id)
    result = runner.get(created.id)

    assert result.stages[5].status == "succeeded"
    assert result.stages[6].status == "waiting_for_human"
    assert result.batch_plan.continuity_ledger == []
    assert result.batch_plan.continuity_ledger_v1[0].key_facts
    lesson_versions = [
        item for item in facts.list_artifacts(created.id) if item.kind == "lesson"
    ]
    assert len(lesson_versions) == 2
    assert "变量保存一个值" in facts.get_artifact(
        lesson_versions[0].artifact_id, lesson_versions[0].version,
    ).content["markdown"]
    writer = next(item for item in provider.requests if item.role == "writer")
    repair = next(item for item in provider.requests if item.role == "repair")
    assert writer.context_contract_version == 1
    assert "45/50" not in writer.model_dump_json()
    assert [item.kind for item in repair.inputs] == ["lesson", "quality"]
    assert "humanizer.language.filler" in repair.model_dump_json()
    assert "humanizer.language.promotion" not in repair.model_dump_json()


def test_new_run_unknown_language_rule_waits_instead_of_guessing_repair(tmp_path):
    class UnknownRuleProvider(FakeProvider):
        repair_calls = 0

        def invoke(self, request):
            if request.role == "repair":
                self.repair_calls += 1
            if request.role == "reviewer" and request.goal.startswith("humanizer"):
                return AgentResponse(role="reviewer", payload={
                    "status": "manual_review", "checks": ["表达问题"],
                    "findings": [{
                        "code": "language.unmapped", "category": "language",
                        "severity": "minor", "evidence": "变量保存一个值",
                        "recommendation": "请人工判断",
                    }],
                    "language_risk": "规则未登记", "limitations": ["待人工"],
                })
            return super().invoke(request)

    provider = UnknownRuleProvider()
    facts = FactStore(tmp_path / "facts.sqlite3")
    runner = V0Runner(provider, store=facts)
    created = runner.create(CourseInput(
        topic="Python 变量", audience="初学者", goal="解释变量", language="zh",
        expected_chapters=1, min_effective_chars=1,
    ), request_key="unknown-language-rule")
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0, source_evidence_version=0 "
            "WHERE id=?", (created.id,),
        )
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (created.id,))

    runner.execute(created.id)
    result = runner.get(created.id)
    assert result.stages[5].status == "waiting_for_human"
    assert result.stages[5].failure_reason == "quality_rule_requires_human"
    assert provider.repair_calls == 0


def test_failed_first_batch_never_schedules_second_batch(tmp_path):
    provider = MultiLessonProvider(fail_writer_call=2)
    runner = V0Runner(provider, store=FactStore(tmp_path / "facts.sqlite3"))
    created = runner.create(COURSE, request_key="batch-failure")

    execute_legacy(runner, created.id)
    run = runner.get(created.id)

    assert run.status == "failed"
    assert len(provider.writer_requests) == 2
    assert provider.writer_requests[-1].inputs[1].content["current_lesson_brief"][
        "title"
    ] == "第 2 章"
    assert run.batch_plan is not None
    assert run.batch_plan.continuity_ledger == []


def test_batch_loop_stops_after_twenty_iterations(tmp_path):
    provider = MultiLessonProvider(lesson_count=63)
    runner = V0Runner(provider, store=FactStore(tmp_path / "facts.sqlite3"))
    created = runner.create(COURSE, request_key="batch-limit")

    execute_legacy(runner, created.id)
    run = runner.get(created.id)

    assert run.status == "waiting_for_human"
    assert run.stages[4].status == "waiting_for_human"
    assert "20" in (run.stages[4].failure_reason or "")
    assert len(provider.writer_requests) == 60
    assert run.stages[5].status == "pending"


def test_manual_review_waits_before_release(tmp_path):
    provider = MultiLessonProvider(lesson_count=1, manual_review=True)
    runner = V0Runner(provider, store=FactStore(tmp_path / "facts.sqlite3"))
    created = runner.create(COURSE, request_key="manual-review")

    execute_legacy(runner, created.id)
    run = runner.get(created.id)

    assert run.status == "waiting_for_human"
    assert run.stages[5].status == "waiting_for_human"
    assert run.stages[6].status == "pending"


def test_human_release_decision_reenters_release_node(tmp_path):
    runner = V0Runner(
        MultiLessonProvider(lesson_count=1),
        store=FactStore(tmp_path / "facts.sqlite3"),
    )
    created = runner.create(COURSE, request_key="release-reentry")
    execute_legacy(runner, created.id)

    prepared = runner.decide(
        created.id,
        ReleaseDecision(action="prepare", reason="人工确认"),
        request_key="release-decision",
    )

    assert prepared.status == "ready_for_release"
    assert prepared.stages[-1].status == "succeeded"


def test_quality_validates_every_lesson_candidate(tmp_path):
    provider = MultiLessonProvider(lesson_count=2, malformed_writer_call=1)
    runner = V0Runner(provider, store=FactStore(tmp_path / "facts.sqlite3"))
    created = runner.create(COURSE, request_key="malformed-first-lesson")

    execute_legacy(runner, created.id)
    run = runner.get(created.id)

    assert run.status == "failed"
    assert run.stages[5].status == "failed"
    assert provider.reviewer_requests == []
