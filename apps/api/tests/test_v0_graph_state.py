from app.v0.schemas import (
    ArtifactRef,
    BatchPlanDraft,
    BlueprintDraft,
    GraphState,
    LessonDraft,
)


def test_graph_state_has_only_frozen_control_fields_and_artifact_references():
    reference = ArtifactRef(
        run_id="run-1",
        artifact_id="artifact-1",
        version=1,
        kind="lesson",
        content_hash="hash-1",
    )
    state = GraphState(
        run_id="run-1",
        artifact_refs={"lesson:lesson-a": reference},
    )

    assert set(GraphState.model_fields) == {
        "run_id",
        "current_node",
        "artifact_refs",
        "batch_cursor",
        "quality_cursor",
        "active_finding_id",
        "approval_status",
        "mission_decision",
        "approval_action",
        "gate_context",
        "gate_reason",
        "source_gate_context",
        "release_decision",
        "pending_interrupt_id",
        "loop_counts",
        "last_outcome",
        "exit_reason",
    }
    assert "markdown" not in state.model_dump_json()
    assert len(state.model_dump_json()) < 600


def test_legacy_artifacts_remain_readable_while_new_batch_fields_are_supported():
    legacy_blueprint = BlueprintDraft.model_validate(
        {
            "lessons": [
                {
                    "title": "第一课",
                    "learning_goal": "完成示例",
                    "evidence": "示例可运行",
                }
            ]
        }
    )
    legacy_batch = BatchPlanDraft.model_validate({"batches": [[0]]})
    legacy_lesson = LessonDraft.model_validate(
        {"title": "第一课", "markdown": "# 第一课"}
    )

    assert legacy_blueprint.lessons[0].lesson_id is None
    assert legacy_blueprint.lessons[0].batch_id is None
    assert legacy_batch.batch_ids == []
    assert legacy_batch.continuity_ledger == []
    assert legacy_lesson.lesson_id is None
    assert legacy_lesson.continuity_summary == ""

    current = LessonDraft(
        title="第二课",
        markdown="# 第二课",
        lesson_id="lesson-1234567890abcdef",
        batch_id="batch-1234567890abcdef",
        continuity_summary="已经定义变量。",
    )
    assert current.batch_id == "batch-1234567890abcdef"


def test_graph_state_size_does_not_depend_on_lesson_body_size():
    reference = ArtifactRef(
        run_id="run-1",
        artifact_id="artifact-1",
        version=1,
        kind="lesson",
        content_hash="hash-1",
    )
    state_for_short_lesson = GraphState(
        run_id="run-1", artifact_refs={"lesson:lesson-a": reference}
    )
    state_for_long_lesson = GraphState(
        run_id="run-1", artifact_refs={"lesson:lesson-a": reference}
    )

    short_body = "x" * 1_000
    long_body = "x" * 100_000
    assert len(short_body) != len(long_body)
    assert len(state_for_short_lesson.model_dump_json()) == len(
        state_for_long_lesson.model_dump_json()
    )
