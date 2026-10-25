"""Delivery evidence is linked by Run ID without copying private content."""

from app.v0.execution import ExecutionStore
from app.v0.schemas import ArtifactRef, CourseInput, GraphState
from app.v0.storage import FactStore
import pytest


def test_trace_links_command_and_node_without_intake_text(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(
            topic="PRIVATE_TOPIC_731", audience="初学者",
            goal="会解释变量", language="zh",
        ),
        "create", enqueue_start=True,
    )
    execution = ExecutionStore(facts.path)
    command = execution.claim("worker-a")
    epoch = execution.acquire(run.id, "worker-a")
    execution.start_node(
        run.id, "intake", GraphState(run_id=run.id), "worker-a", epoch,
        command_id=command.id,
    )

    from app.v0.delivery import DeliveryStore

    evidence = DeliveryStore(facts.path).read(run.id)
    assert evidence.trace_id == run.id
    assert evidence.nodes[0].command_id == command.id
    assert command.id in {item.id for item in evidence.commands}
    assert "PRIVATE_TOPIC_731" not in evidence.model_dump_json()
    assert evidence.integrity_issues == []
    assert {item.scenario for item in evidence.paths} == {
        "normal", "recovery", "human",
    }


def test_trace_reports_broken_command_reference(tmp_path):
    from app.v0.delivery import DeliveryStore

    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="变量", audience="初学者", goal="解释变量", language="zh"),
        "create", enqueue_start=True,
    )
    execution = ExecutionStore(facts.path)
    epoch = execution.acquire(run.id, "worker-a")
    node_id = execution.start_node(
        run.id, "intake", GraphState(run_id=run.id), "worker-a", epoch,
        command_id="missing-command",
    )
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO provider_calls(id,run_id,command_id,node_execution_id,"
            "role,status,started_at) VALUES (?,?,?,?,?,'RESERVED','now')",
            ("call-broken", run.id, "missing-command", node_id, "mission"),
        )
    evidence = DeliveryStore(facts.path).read(run.id)
    assert f"node:{node_id}:missing_command" in evidence.integrity_issues
    assert "provider_call:call-broken:missing_command" in evidence.integrity_issues


def test_constraint_finding_with_missing_artifact_reports_integrity_issue(tmp_path):
    from app.v0.delivery import DeliveryStore
    from app.v0.schemas import Finding, FindingLocation, QualitySummary

    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="变量", audience="初学者", goal="解释变量", language="zh"),
        "missing-finding-artifact",
    )
    missing_ref = ArtifactRef(
        run_id=run.id,
        artifact_id="missing-lesson",
        version=1,
        kind="lesson",
        content_hash="missing-hash",
    )
    finding = Finding(
        finding_id="missing-finding",
        run_id=run.id,
        gate="deterministic",
        rule_id="lesson.effective_chars.minimum",
        artifact_ref=missing_ref,
        location=FindingLocation(
            lesson_id="lesson-1",
            line_start=1,
            line_end=1,
            excerpt_hash="excerpt-hash",
        ),
        category="structure",
        severity="blocker",
        evidence="当前有效字符数为 1",
        expected="有效字符数至少为 12000",
    )
    quality = QualitySummary(
        status="manual_review",
        checks=["deterministic:lesson.effective_chars.minimum:fail"],
        language_risk="表达 Gate 尚未通过",
        limitations=["测试"],
        evidence_findings=[finding],
    )
    run.quality = quality
    facts.record(
        run,
        "artifact.created",
        "quality",
        artifact=quality,
        producer_role="system",
        source_refs=[missing_ref],
    )

    evidence = DeliveryStore(facts.path).read(run.id)

    assert evidence.findings[0].actual_value is None
    assert "finding:missing-finding:missing_artifact" in evidence.integrity_issues


@pytest.mark.parametrize(
    ("content_json", "issue"),
    [
        ("{}", "invalid_lesson_content"),
        ("{", "invalid_json"),
    ],
)
def test_constraint_finding_with_malformed_lesson_stays_readable(
    tmp_path, content_json, issue
):
    from app.v0.delivery import DeliveryStore
    from app.v0.quality_loop import check_markdown
    from app.v0.schemas import LessonDraft, QualitySummary

    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="变量", audience="初学者", goal="解释变量", language="zh"),
        f"malformed-lesson-{issue}",
    )
    lesson = LessonDraft(title="变量", markdown="# 变量\n\n正文", lesson_id="lesson-1")
    facts.record(run, "artifact.created", "generation", artifact=lesson)
    current = facts.get_run(run.id)
    summary = next(item for item in current.artifacts if item.kind == "lesson")
    lesson_ref = ArtifactRef(
        run_id=run.id,
        artifact_id=summary.artifact_id,
        version=summary.version,
        kind="lesson",
        content_hash=summary.content_hash,
    )
    report = check_markdown(
        lesson.markdown, lesson_ref, "lesson-1", min_effective_chars=12_000
    )
    quality = QualitySummary(
        status="manual_review",
        checks=["deterministic:lesson.effective_chars.minimum:fail"],
        language_risk="表达 Gate 尚未通过",
        limitations=["测试"],
        evidence_findings=report.findings,
    )
    current.quality = quality
    facts.record(current, "artifact.created", "quality", artifact=quality)
    with facts.connect() as connection:
        connection.execute(
            "UPDATE artifacts SET content_json=? WHERE artifact_id=? AND version=?",
            (content_json, lesson_ref.artifact_id, lesson_ref.version),
        )

    evidence = DeliveryStore(facts.path).read(run.id)

    assert evidence.findings[0].actual_value is None
    assert any(item.endswith(issue) for item in evidence.integrity_issues)


def test_constraint_event_with_malformed_blueprint_stays_readable(tmp_path):
    from app.v0.delivery import DeliveryStore
    from app.v0.schemas import BlueprintDraft, BlueprintLesson

    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="变量", audience="初学者", goal="解释变量", language="zh"),
        "malformed-blueprint",
    )
    blueprint = BlueprintDraft(lessons=[BlueprintLesson(
        title="变量",
        learning_goal="解释变量",
        evidence="完成练习",
    )])
    facts.record(run, "artifact.created", "blueprint", artifact=blueprint)
    current = facts.get_run(run.id)
    summary = next(item for item in current.artifacts if item.kind == "blueprint")
    blueprint_ref = ArtifactRef(
        run_id=run.id,
        artifact_id=summary.artifact_id,
        version=summary.version,
        kind="blueprint",
        content_hash=summary.content_hash,
    )
    facts.record(
        current,
        "blueprint.chapter_count_observed",
        "batch_plan",
        accepted_ref=blueprint_ref,
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE artifacts SET content_json='{}' "
            "WHERE artifact_id=? AND version=?",
            (blueprint_ref.artifact_id, blueprint_ref.version),
        )

    evidence = DeliveryStore(facts.path).read(run.id)

    assert evidence.constraint_events[0].actual_value is None
    assert any(
        item.endswith("invalid_blueprint_content")
        for item in evidence.integrity_issues
    )


def test_recovery_and_human_paths_are_indexed_from_durable_facts(tmp_path):
    from app.v0.delivery import DeliveryStore

    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="变量", audience="初学者", goal="解释变量", language="zh"),
        "create", enqueue_start=True,
    )
    execution = ExecutionStore(facts.path)
    command = execution.claim("worker-a")
    epoch = execution.acquire(run.id, "worker-a")
    execution.start_node(
        run.id, "intake", GraphState(run_id=run.id), "worker-a", epoch,
        command_id=command.id,
    )
    execution.expire_for_test(run.id)
    epoch_2 = execution.acquire(run.id, "worker-b")
    execution.start_node(
        run.id, "intake", GraphState(run_id=run.id), "worker-b", epoch_2,
        command_id=command.id,
    )
    execution.accept(run.id, "STOP", {}, "stop")
    paths = {item.scenario: item for item in DeliveryStore(facts.path).read(run.id).paths}
    assert paths["recovery"].status == "observed"
    assert paths["human"].status == "observed"
    assert paths["normal"].status == "not_observed"


def test_new_command_after_resume_is_not_mislabeled_crash_takeover(tmp_path):
    from app.v0.delivery import DeliveryStore

    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="变量", audience="初学者", goal="解释变量", language="zh"),
        "create", enqueue_start=True,
    )
    execution = ExecutionStore(facts.path)
    first = execution.claim("worker-a")
    epoch = execution.acquire(run.id, "worker-a")
    execution.start_node(
        run.id, "intake", GraphState(run_id=run.id), "worker-a", epoch,
        command_id=first.id,
    )
    execution.expire_for_test(run.id)
    second = execution.accept(run.id, "RESUME", {}, "resume")
    epoch = execution.acquire(run.id, "worker-b")
    execution.start_node(
        run.id, "intake", GraphState(run_id=run.id), "worker-b", epoch,
        command_id=second.id,
    )
    recovery = next(item for item in DeliveryStore(facts.path).read(run.id).paths
                    if item.scenario == "recovery")
    assert recovery.status == "not_observed"


def test_normal_delivery_path_requires_human_release_decision(tmp_path):
    from app.v0.delivery import DeliveryStore
    from app.v0.provider import FakeProvider
    from app.v0.runner import V0Runner
    from app.v0.schemas import ReleaseDecision
    from app.v0.worker import Worker

    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="变量", audience="初学者", goal="解释变量", language="zh"),
        "create", enqueue_start=True,
    )
    run.constraints_version = 0
    run.source_evidence_version = 0
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0, constraints_version=0, "
            "source_evidence_version=0 WHERE id=?",
            (run.id,),
        )
        connection.execute(
            "UPDATE snapshots SET projection_json=? WHERE run_id=?",
            (run.model_dump_json(), run.id),
        )
    Worker(facts.path, provider=FakeProvider()).run_once()
    before = DeliveryStore(facts.path).read(run.id)
    assert next(item for item in before.paths if item.scenario == "normal").status == "not_observed"
    V0Runner(FakeProvider(), facts).decide(
        run.id, ReleaseDecision(action="prepare", reason="人工已审阅"), "release-1"
    )
    after = DeliveryStore(facts.path).read(run.id)
    assert next(item for item in after.paths if item.scenario == "normal").status == "observed"
    assert after.decisions[0].action == "prepare"
    assert after.provider_calls
    assert all(call.node_execution_id and call.command_id for call in after.provider_calls)
    assert after.integrity_issues == []


def test_provider_budget_reserves_calls_and_requires_human_at_limit(tmp_path):
    from app.v0.budget import BudgetedProvider, BudgetExceeded, BudgetStore
    from app.v0.provider import AgentInput, AgentRequest, FakeProvider

    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="变量", audience="初学者", goal="解释变量", language="zh"),
        "create", enqueue_start=True,
    )
    execution = ExecutionStore(facts.path)
    command = execution.claim("worker-a")
    epoch = execution.acquire(run.id, "worker-a")
    budget = BudgetStore(facts.path)
    provider = BudgetedProvider(FakeProvider(), budget)
    provider.bind("worker-a", epoch, command.id)
    request = AgentRequest(
        run_id=run.id, role="mission", goal="任务定义", instructions=["仅测试"],
        inputs=[AgentInput(kind="intake", content={"topic": "变量"})],
        output_schema={},
    )
    for _ in range(60):
        provider.invoke(request)
    with pytest.raises(BudgetExceeded):
        provider.invoke(request)
    assert budget.summary(run.id).used == 60
    assert budget.summary(run.id).requires_human
    from app.v0.delivery import DeliveryStore

    assert len(DeliveryStore(facts.path).read(run.id).provider_calls) == 60
    with facts.connect() as connection:
        kinds = [row[0] for row in connection.execute(
            "SELECT type FROM events WHERE run_id=? AND type LIKE 'budget.%' "
            "ORDER BY id", (run.id,),
        )]
    assert kinds == ["budget.warning", "budget.exhausted"]


def test_budget_summary_reports_known_and_unknown_token_usage(tmp_path):
    from app.v0.budget import BudgetStore

    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(
            topic="变量",
            audience="初学者",
            goal="解释变量",
            language="zh",
            token_limit=180,
        ),
        "token-summary",
    )
    with facts.connect() as connection:
        connection.executemany(
            "INSERT INTO provider_calls(id,run_id,role,status,input_tokens,"
            "output_tokens,started_at) VALUES (?,?,?,?,?,?,'now')",
            [
                ("call-1", run.id, "mission", "SUCCEEDED", 100, 20),
                ("call-2", run.id, "writer", "SUCCEEDED", None, None),
                ("call-3", run.id, "reviewer", "SUCCEEDED", 50, 10),
                ("call-4", run.id, "repair", "RESERVED", None, None),
            ],
        )

    summary = BudgetStore(facts.path).summary(run.id)
    assert summary.tokens_used == 180
    assert summary.token_limit == 180
    assert summary.token_usage_unknown == 2
    assert summary.token_exhausted is True


def test_legacy_run_does_not_activate_token_limit(tmp_path):
    from app.v0.budget import BudgetStore

    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(
            topic="变量",
            audience="初学者",
            goal="解释变量",
            language="zh",
            token_limit=1,
        ),
        "legacy-token-summary",
    )
    with facts.connect() as connection:
        connection.execute("UPDATE runs SET constraints_version=0 WHERE id=?", (run.id,))
        connection.execute(
            "INSERT INTO provider_calls(id,run_id,role,status,input_tokens,"
            "output_tokens,started_at) VALUES (?,?,?,'SUCCEEDED',10,10,'now')",
            ("legacy-call", run.id, "mission"),
        )

    summary = BudgetStore(facts.path).summary(run.id)
    assert summary.tokens_used == 20
    assert summary.token_limit is None
    assert summary.token_exhausted is False


def test_human_revision_can_approve_exactly_twenty_more_calls(tmp_path):
    from app.v0.budget import BudgetStore

    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="变量", audience="初学者", goal="解释变量", language="zh"),
        "create", enqueue_start=True,
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET langgraph_flow_version=0 WHERE id=?", (run.id,),
        )
    execution = ExecutionStore(facts.path)
    execution.accept(run.id, "START", {}, "seed-checkpoint")
    epoch = execution.acquire(run.id, "worker-a")
    waiting = facts.get_run(run.id)
    waiting.status = "waiting_for_human"
    waiting.stages[1].status = "waiting_for_human"
    facts.record(waiting, "stage.waiting", "mission")
    with facts.connect() as connection:
        for index in range(60):
            connection.execute(
                "INSERT INTO provider_calls(id,run_id,role,status,started_at) "
                "VALUES (?,?,?,'SUCCEEDED','now')",
                (f"call-{index}", run.id, "mission"),
            )
    checkpoint_id = execution.last_checkpoint(run.id)["id"]
    command = execution.accept(run.id, "REVISE", {
        "text": "批准继续", "expected_checkpoint_id": checkpoint_id,
        "provider_limit": 80,
    }, "revise-1")
    with pytest.raises(ValueError, match="预算耗尽"):
        execution.record_revision(command, "worker-a", epoch)
    waiting = facts.get_run(run.id)
    waiting.stages[1].failure_reason = "Provider 调用预算耗尽，需要人工处理"
    facts.record(waiting, "stage.waiting", "mission")
    with facts.connect() as connection:
        from app.v0.budget import BudgetStore

        BudgetStore._event(connection, run.id, "budget.exhausted")
    execution.record_revision(command, "worker-a", epoch)
    assert BudgetStore(facts.path).summary(run.id).limit == 80
    with facts.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM events WHERE run_id=? AND type='budget.approved'",
            (run.id,),
        ).fetchone()[0] == 1


def test_provider_error_never_exposes_secret_in_run_or_command(tmp_path):
    from app.v0.provider import FakeProvider, ProviderError
    from app.v0.worker import Worker

    class LeakingProvider(FakeProvider):
        def invoke(self, request):
            raise ProviderError("api_key=TOPSECRET_731")

    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="变量", audience="初学者", goal="解释变量", language="zh"),
        "create", enqueue_start=True,
    )
    assert Worker(facts.path, provider=LeakingProvider()).run_once()
    execution = ExecutionStore(facts.path)
    assert "TOPSECRET_731" not in facts.get_run(run.id).model_dump_json()
    assert "TOPSECRET_731" not in execution.read_model(run.id).model_dump_json()


def test_repair_budget_wait_emits_durable_manual_alert(tmp_path):
    from app.v0.provider import FakeProvider
    from app.v0.runner import V0Runner

    facts = FactStore(tmp_path / "facts.sqlite3")
    runner = V0Runner(FakeProvider(), facts)
    run = runner.create(
        CourseInput(topic="变量", audience="初学者", goal="解释变量", language="zh")
    )
    runner._mark_waiting(run.id, 5, "返工预算耗尽，需要人工处理")
    with facts.connect() as connection:
        kinds = [row[0] for row in connection.execute(
            "SELECT type FROM events WHERE run_id=? ORDER BY id", (run.id,),
        )]
    assert "budget.repair_exhausted" in kinds
    from app.v0.budget import BudgetStore

    assert BudgetStore(facts.path).summary(run.id).repair_limit == 3


def test_provider_limit_stops_graph_at_human_gate(tmp_path):
    from app.v0.provider import FakeProvider
    from app.v0.worker import Worker

    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="变量", audience="初学者", goal="解释变量", language="zh"),
        "create", enqueue_start=True,
    )
    with facts.connect() as connection:
        connection.execute("UPDATE runs SET mission_review_required=0 WHERE id=?", (run.id,))
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO budget_limits(run_id,provider_limit) VALUES (?,1)", (run.id,)
        )
    Worker(facts.path, provider=FakeProvider()).run_once()
    result = facts.get_run(run.id)
    assert result.status == "waiting_for_human"
    assert result.stages[2].status == "waiting_for_human"
    with facts.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM events WHERE run_id=? AND type='budget.exhausted'",
            (run.id,),
        ).fetchone()[0] == 1


def test_trace_rule_identifier_does_not_echo_model_text():
    from app.v0.delivery import safe_rule_id

    result = safe_rule_id("api_key=TOPSECRET_731")
    assert result.startswith("rule-")
    assert "TOPSECRET_731" not in result


def test_execution_read_model_hides_historical_wait_reason(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(topic="变量", audience="初学者", goal="解释变量", language="zh"),
        "create", enqueue_start=True,
    )
    waiting = facts.get_run(run.id)
    waiting.status = "waiting_for_human"
    waiting.stages[1].status = "waiting_for_human"
    waiting.stages[1].failure_reason = "api_key=TOPSECRET_731"
    facts.record(waiting, "stage.waiting", "mission")
    assert "TOPSECRET_731" not in ExecutionStore(facts.path).read_model(run.id).model_dump_json()


def test_constraint_evidence_indexes_events_without_copying_course_content(tmp_path):
    from app.v0.delivery import DeliveryStore, safe_rule_id
    from app.v0.provider import FakeProvider
    from app.v0.worker import Worker

    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(
            topic="PRIVATE_TOPIC_731",
            audience="初学者",
            goal="解释变量",
            language="zh",
            expected_chapters=1,
            min_effective_chars=12_000,
            token_limit=100_000,
        ),
        "constraint-evidence",
        enqueue_start=True,
    )
    with facts.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0, source_evidence_version=0 "
            "WHERE id=?", (run.id,)
        )
        connection.execute("DELETE FROM snapshots WHERE run_id=?", (run.id,))
    Worker(facts.path, provider=FakeProvider()).run_once()
    current = facts.get_run(run.id)
    blueprint = next(item for item in current.artifacts if item.kind == "blueprint")
    blueprint_ref = ArtifactRef(
        run_id=run.id,
        artifact_id=blueprint.artifact_id,
        version=blueprint.version,
        kind="blueprint",
        content_hash=blueprint.content_hash,
    )
    facts.record(
        current,
        "blueprint.chapter_deviation_accepted",
        "batch_plan",
        accepted_ref=blueprint_ref,
    )
    current = facts.get_run(run.id)
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO provider_calls(id,run_id,role,status,input_tokens,"
            "output_tokens,started_at) VALUES (?,?,?,'SUCCEEDED',300,100,'now')",
            ("constraint-token-count", run.id, "reviewer"),
        )
    current.status = "stopped"
    current.stages[5].status = "stopped"
    current.stages[5].failure_reason = "token_limit_reached"
    facts.record(current, "budget.token_exhausted", "quality")

    evidence = DeliveryStore(facts.path).read(run.id)
    kinds = {item.kind for item in evidence.constraint_events}
    assert kinds == {
        "blueprint.chapter_count_observed",
        "blueprint.chapter_deviation_accepted",
        "budget.token_exhausted",
    }
    accepted = next(
        item
        for item in evidence.constraint_events
        if item.kind == "blueprint.chapter_deviation_accepted"
    )
    assert accepted.artifact_id == blueprint.artifact_id
    assert accepted.artifact_version == blueprint.version
    observed = next(
        item
        for item in evidence.constraint_events
        if item.kind == "blueprint.chapter_count_observed"
    )
    assert (observed.expected_value, observed.actual_value) == (1, 1)
    token_stop = next(
        item
        for item in evidence.constraint_events
        if item.kind == "budget.token_exhausted"
    )
    assert token_stop.expected_value == 100_000
    assert token_stop.actual_value == 400
    character_finding = next(
        item
        for item in evidence.findings
        if item.rule_id == safe_rule_id("lesson.effective_chars.minimum")
    )
    assert character_finding.expected_value == 12_000
    assert 0 < character_finding.actual_value < 12_000
    serialized = evidence.model_dump_json()
    assert "PRIVATE_TOPIC_731" not in serialized
    assert "候选正文" not in serialized
    assert "prompt" not in serialized.lower()
