import pytest
from pydantic import ValidationError

from app.v0 import schemas
from app.v0.schemas import (
    BlueprintDraft,
    CourseInput,
    LessonDraft,
    MissionDraft,
    QualitySummary,
    ReviewFinding,
    ReleaseDecision,
    StageRecord,
    V0Run,
)


VALID_INPUT = {
    "topic": "Python 变量",
    "audience": "零基础学习者",
    "goal": "能解释并修改变量",
    "language": "zh",
}
STAGE_NAMES = [
    "intake",
    "mission",
    "blueprint",
    "batch_plan",
    "generation",
    "quality",
    "release",
]


def test_course_input_rejects_blank_fields():
    for field in ("topic", "audience", "goal"):
        with pytest.raises(ValidationError):
            CourseInput(**{**VALID_INPUT, field: "   "})


def test_course_input_has_generation_constraint_defaults():
    value = CourseInput(**VALID_INPUT)

    assert value.expected_chapters == 12
    assert value.min_effective_chars == 12_000
    assert value.token_limit is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_chapters", 0),
        ("expected_chapters", 101),
        ("min_effective_chars", 0),
        ("token_limit", 0),
    ],
)
def test_course_input_rejects_invalid_generation_constraints(field, value):
    with pytest.raises(ValidationError):
        CourseInput.model_validate({**VALID_INPUT, field: value})


def test_run_starts_with_exactly_seven_pending_stages():
    run = V0Run(id="run-1", course_input=CourseInput(**VALID_INPUT))

    assert [stage.name for stage in run.stages] == STAGE_NAMES
    assert all(stage.status == "pending" for stage in run.stages)


def test_stage_rejects_unknown_name_and_release_reason_is_required():
    with pytest.raises(ValidationError):
        StageRecord(name="research")
    with pytest.raises(ValidationError):
        ReleaseDecision(action="prepare", reason=" ")


def test_quality_cannot_claim_ready_without_language_risk_and_limitations():
    valid = {
        "status": "ready",
        "checks": ["标题存在"],
        "language_risk": "需要人工复读",
        "limitations": ["未核验事实"],
    }
    with pytest.raises(ValidationError):
        QualitySummary(**{**valid, "language_risk": " "})
    with pytest.raises(ValidationError):
        QualitySummary(**{**valid, "limitations": []})


def test_persistent_records_have_explicit_ownership_and_ids():
    course = schemas.CourseRecord(id="c1", title="Python 变量", workspace_key="c1")
    run = schemas.RunRecord(id="r1", course_id=course.id, status="running")
    intake = schemas.IntakeRecord(run_id=run.id, course_input=CourseInput(**VALID_INPUT))
    artifact = schemas.ArtifactRecord(
        artifact_id="a1",
        version=1,
        run_id=run.id,
        kind="lesson",
        content={"title": "第一课", "markdown": "# 第一课"},
        content_hash="hash",
    )
    event = schemas.EventRecord(
        id=1, run_id=run.id, type="stage.succeeded", stage="generation"
    )
    snapshot = schemas.SnapshotRecord(
        run_id=run.id,
        revision=event.id,
        run=V0Run(
            id=run.id,
            course_id=course.id,
            course_input=intake.course_input,
        ),
    )
    workspace = schemas.WorkspaceRecord(course_id=course.id, relative_path="workspaces/c1")

    assert artifact.kind == "lesson"
    assert artifact.version == 1
    assert snapshot.run.course_id == workspace.course_id


def test_artifact_version_must_be_positive():
    with pytest.raises(ValidationError):
        schemas.ArtifactRecord(
            artifact_id="a1",
            version=0,
            run_id="r1",
            kind="lesson",
            content={},
            content_hash="hash",
        )


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (
            MissionDraft,
            {
                "audience": "初学者",
                "learning_goal": "完成一个页面",
                "scope": "React 基础",
                "stop_conditions": ["目标冲突时停止"],
                "unexpected": "不能接受",
            },
        ),
        (
            BlueprintDraft,
            {
                "lessons": [
                    {
                        "title": "第一课",
                        "learning_goal": "完成页面",
                        "evidence": "页面可运行",
                        "unexpected": "不能接受",
                    }
                ]
            },
        ),
        (
            LessonDraft,
            {"title": "第一课", "markdown": "# 第一课", "unexpected": "不能接受"},
        ),
        (
            QualitySummary,
            {
                "status": "ready",
                "checks": ["结构完整"],
                "findings": [],
                "language_risk": "需要人工复读",
                "limitations": ["事实未核验"],
                "unexpected": "不能接受",
            },
        ),
    ],
)
def test_agent_outputs_reject_extra_fields(schema, payload):
    with pytest.raises(ValidationError, match="extra_forbidden"):
        schema.model_validate(payload)


def test_review_finding_uses_a_strict_bounded_vocabulary():
    with pytest.raises(ValidationError):
        ReviewFinding(
            code="language-1",
            category="style",
            severity="urgent",
            evidence="句子重复",
            recommendation="删去重复句",
        )


def test_batch_plan_rejects_negative_lesson_index():
    with pytest.raises(ValidationError):
        schemas.BatchPlanDraft(batches=[[-1]])


def test_lesson_continuity_terms_are_bounded():
    with pytest.raises(ValidationError):
        LessonDraft(title="课程", markdown="# 课程", terminology=["字" * 121])
