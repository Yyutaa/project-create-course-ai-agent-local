from app.v0.approval import (
    mission_approval,
    quality_approval,
    release_approval,
    source_approval,
)
from app.v0.schemas import (
    ArtifactRef,
    CourseInput,
    MissionDraft,
    QualitySummary,
    V0Run,
)


def course_input() -> CourseInput:
    return CourseInput(
        topic="变量", audience="初学者", goal="解释变量", language="zh",
    )


def lesson_ref() -> ArtifactRef:
    return ArtifactRef(
        run_id="run-1", artifact_id="lesson-1", version=1,
        kind="lesson", content_hash="lesson-hash",
    )


def test_mission_approval_is_decision_only():
    run = V0Run(
        id="run-1",
        course_input=course_input(),
        mission=MissionDraft(
            audience="初学者",
            learning_goal="解释变量并完成练习",
            scope="基础语法",
            stop_conditions=["完成练习", "通过测验"],
        ),
    )

    payload = mission_approval(run, checkpoint_id="cp-1")

    assert payload is not None
    assert payload.type == "MISSION_APPROVAL"
    assert payload.step == "mission"
    assert payload.actions == ["approve", "revise", "stop"]
    assert payload.checkpoint_id == "cp-1"
    assert "解释变量" in payload.output.summary
    serialized = payload.model_dump_json()
    for forbidden in (
        "state_json", "waiting_state_json", "payload_json",
        "api_key", "Authorization", "markdown",
    ):
        assert forbidden not in serialized


def test_quality_approval_never_offers_approve():
    run = V0Run(
        id="run-1",
        course_input=course_input(),
        quality=QualitySummary(
            status="manual_review",
            checks=["需要人工复核"],
            findings=[],
            language_risk="需人工复读",
            limitations=["未核验事实来源"],
        ),
    )

    payload = quality_approval(
        run, checkpoint_id="cp-1", retry_only=False,
        quality_ref=None, lesson_ref=lesson_ref(),
    )

    assert payload is not None
    assert "approve" not in payload.actions
    assert payload.actions == ["retry", "accept", "stop"]
    assert "接受风险" in payload.guidance


def test_quality_retry_only_has_no_accept():
    run = V0Run(
        id="run-1",
        course_input=course_input(),
        quality=QualitySummary(
            status="manual_review",
            checks=["Reviewer 输出校验失败"],
            findings=[],
            language_risk="未知",
            limitations=["需重新检查"],
        ),
    )

    payload = quality_approval(
        run, checkpoint_id="cp-1", retry_only=True,
        quality_ref=None, lesson_ref=lesson_ref(),
    )

    assert payload is not None
    assert payload.actions == ["retry"]


def test_quality_retry_only_works_without_quality_summary():
    run = V0Run(id="run-1", course_input=course_input())

    payload = quality_approval(
        run, checkpoint_id="cp-1", retry_only=True,
        quality_ref=None, lesson_ref=lesson_ref(),
    )

    assert payload is not None
    assert payload.actions == ["retry"]
    assert payload.output.metrics["status"] == "retry_only"


def test_quality_retry_only_ignores_previous_lesson_summary():
    run = V0Run(
        id="run-1",
        course_input=course_input(),
        quality=QualitySummary(
            status="manual_review",
            checks=["上一课次的人工复核"],
            findings=[],
            language_risk="上一课次",
            limitations=["上一课次限制"],
        ),
    )

    payload = quality_approval(
        run, checkpoint_id="cp-1", retry_only=True,
        quality_ref=None, lesson_ref=lesson_ref(),
    )

    assert payload is not None
    assert payload.actions == ["retry"]
    assert payload.output.metrics["status"] == "retry_only"
    assert "manual_review" not in payload.output.summary
    assert "上一课次" not in payload.output.summary


def test_source_approval_exposes_only_reviewable_candidates():
    payload = source_approval(
        step="blueprint",
        checkpoint_id="cp-1",
        candidates=[
            {
                "id": "candidate-1",
                "url": "https://docs.python.org/3/",
                "title": "Python 文档",
                "status": "needs_human",
                "metadata_hash": "hash-1",
            },
            {
                "id": "candidate-2",
                "url": "https://raw.githubusercontent.com/user/repo/main/x.md",
                "title": "Raw",
                "status": "needs_human",
                "metadata_hash": "hash-2",
            },
        ],
        retry_remaining=1,
    )

    assert payload.type == "SOURCE_APPROVAL"
    assert [item.id for item in payload.output.candidates] == ["candidate-1"]
    assert payload.output.metrics["hidden_candidate_count"] == 1
    assert "retry_search" in payload.actions
    assert "propose_url" in payload.actions


def test_release_approval_has_no_approve():
    run = V0Run(
        id="run-1",
        course_input=course_input(),
        quality=QualitySummary(
            status="ready",
            checks=["通过"],
            findings=[],
            language_risk="低",
            limitations=["未执行完整构建"],
        ),
    )

    payload = release_approval(run, checkpoint_id="cp-1")

    assert payload is not None
    assert payload.type == "RELEASE_APPROVAL"
    assert payload.actions == ["prepare", "stop"]
    assert "approve" not in payload.actions


FORBIDDEN_KEYS = {
    "state_json", "waiting_state_json", "after_state_json",
    "payload_json", "api_key", "Authorization", "raw", "prompt", "markdown",
}


def _keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def _assert_decision_only(payload):
    assert payload is not None
    assert FORBIDDEN_KEYS.isdisjoint(_keys(payload.model_dump()))
    assert "TOPSECRET_731" not in payload.model_dump_json()


def test_all_approval_payloads_hide_free_text_and_forbidden_keys():
    mission_run = V0Run(
        id="run-1",
        course_input=course_input(),
        mission=MissionDraft(
            audience="初学者",
            learning_goal="解释变量",
            scope="TOPSECRET_731",
            stop_conditions=["完成练习"],
        ),
    )
    quality_run = V0Run(
        id="run-2",
        course_input=course_input(),
        quality=QualitySummary(
            status="manual_review",
            checks=["TOPSECRET_731"],
            findings=[],
            language_risk="TOPSECRET_731",
            limitations=["TOPSECRET_731"],
        ),
    )
    source_payload = source_approval(
        step="blueprint",
        checkpoint_id="cp-3",
        candidates=[{
            "id": "candidate-1",
            "url": "https://docs.python.org/3/",
            "title": "Python 文档",
            "status": "needs_human",
            "metadata_hash": "hash-1",
            "raw_content": "TOPSECRET_731",
        }],
        retry_remaining=1,
    )
    payloads = [
        mission_approval(mission_run, checkpoint_id="cp-1"),
        quality_approval(
            quality_run, checkpoint_id="cp-2", retry_only=False,
            quality_ref=None, lesson_ref=lesson_ref(),
        ),
        source_payload,
        release_approval(quality_run, checkpoint_id="cp-4"),
    ]
    for payload in payloads:
        _assert_decision_only(payload)


def test_quality_manual_review_never_exposes_approve():
    run = V0Run(
        id="run-1",
        course_input=course_input(),
        quality=QualitySummary(
            status="manual_review",
            checks=["需要人工复核"],
            findings=[],
            language_risk="需人工复读",
            limitations=["返工预算耗尽，需要人工处理"],
        ),
    )
    payload = quality_approval(
        run, checkpoint_id="cp-1", retry_only=False,
        quality_ref=None, lesson_ref=lesson_ref(),
    )
    assert payload is not None
    assert payload.output.metrics["status"] == "manual_review"
    assert payload.output.metrics["limitation_count"] == 1
    assert "approve" not in payload.actions
    assert {"retry", "accept", "stop"} == set(payload.actions)
