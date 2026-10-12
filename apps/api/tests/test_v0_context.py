import pytest

from app.v0.context import ContextBudgetError, ContextPackBuilder
from app.v0.schemas import ArtifactRecord, ArtifactRef, CourseInput


def record(kind, artifact_id, content, content_hash):
    return ArtifactRecord(
        artifact_id=artifact_id,
        version=1,
        run_id="run-1",
        kind=kind,
        content=content,
        content_hash=content_hash,
    )


def reference(item):
    return ArtifactRef(
        run_id=item.run_id,
        artifact_id=item.artifact_id,
        version=item.version,
        kind=item.kind,
        content_hash=item.content_hash,
    )


def fixture_builder():
    records = {
        "mission": record(
            "mission",
            "mission-1",
            {
                "audience": "初学者",
                "learning_goal": "完成四章练习",
                "scope": "Python 基础",
                "stop_conditions": ["来源不足时停止"],
                "private_notes": "writer 不应看见这一段",
            },
            "mission-hash",
        ),
        "blueprint": record(
            "blueprint",
            "blueprint-1",
            {
                "lessons": [
                    {
                        "title": "变量基础",
                        "learning_goal": "修改变量",
                        "evidence": "输出变化",
                        "lesson_id": "lesson-a",
                        "batch_id": "batch-a",
                    },
                    {
                        "title": "条件控制",
                        "learning_goal": "解释分支",
                        "evidence": "两个分支均触发",
                        "lesson_id": "lesson-b",
                        "batch_id": "batch-b",
                    },
                ]
            },
            "blueprint-hash",
        ),
        "batch_plan": record(
            "batch_plan",
            "batch-1",
            {
                "batches": [[0], [1]],
                "batch_ids": ["batch-a", "batch-b"],
                "lesson_ids": [["lesson-a"], ["lesson-b"]],
                "continuity_ledger": [
                    {
                        "batch_id": "batch-a",
                        "lesson_id": "lesson-a",
                        "lesson_ref": {
                            "run_id": "run-1",
                            "artifact_id": "lesson-1",
                            "version": 1,
                            "kind": "lesson",
                            "content_hash": "lesson-hash",
                        },
                        "summary": "已经解释变量赋值。",
                        "terminology": ["变量"],
                        "next_promises": ["下一章解释条件分支"],
                    }
                ],
            },
            "batch-hash",
        ),
        "lesson": record(
            "lesson",
            "lesson-1",
            {
                "title": "变量基础",
                "markdown": "# 变量基础\n\n这是一段候选正文。",
                "lesson_id": "lesson-a",
                "batch_id": "batch-a",
                "continuity_summary": "已经解释变量赋值。",
            },
            "lesson-hash",
        ),
    }
    return ContextPackBuilder(
        lambda artifact_id, version: next(
            item
            for item in records.values()
            if item.artifact_id == artifact_id and item.version == version
        )
    ), records


def test_mission_pack_contains_only_intake():
    builder, _ = fixture_builder()
    course_input = CourseInput(
        topic="Python",
        audience="初学者",
        goal="完成练习",
        language="zh",
    )

    pack = builder.for_mission(course_input)

    assert [item.kind for item in pack.inputs] == ["intake"]
    assert pack.inputs[0].content == course_input.model_dump()
    assert pack.total_chars <= 4_000


def test_legacy_mission_pack_omits_generation_constraint_defaults():
    builder, _ = fixture_builder()
    course_input = CourseInput(
        topic="Python",
        audience="初学者",
        goal="完成练习",
        language="zh",
    )

    pack = builder.for_mission(
        course_input,
        include_generation_constraints=False,
    )

    assert pack.inputs[0].content == {
        "topic": "Python",
        "audience": "初学者",
        "goal": "完成练习",
        "language": "zh",
    }


def test_legacy_mission_revision_omits_generation_constraint_defaults():
    builder, records = fixture_builder()
    course_input = CourseInput(
        topic="Python",
        audience="初学者",
        goal="完成练习",
        language="zh",
    )

    pack = builder.for_mission_revision(
        "run-1",
        course_input,
        reference(records["mission"]),
        "缩小范围",
        include_generation_constraints=False,
    )

    content = pack.inputs[0].content
    assert "expected_chapters" not in content
    assert "min_effective_chars" not in content
    assert "token_limit" not in content
    assert content["revision_request"]["feedback"] == "缩小范围"


def test_blueprint_pack_contains_mission_and_explicit_empty_source_summary():
    builder, records = fixture_builder()

    pack = builder.for_blueprint(
        "run-1",
        reference(records["mission"]),
        expected_chapters=12,
    )

    assert [item.kind for item in pack.inputs] == ["mission"]
    assert pack.inputs[0].content["mission"]["learning_goal"] == "完成四章练习"
    assert pack.inputs[0].content["source_summaries"] == []
    assert "未提供" in pack.inputs[0].content["source_limitations"][0]
    assert pack.inputs[0].content["generation_constraints"] == {
        "expected_chapters": 12
    }
    assert "topic" not in pack.inputs[0].content
    assert pack.total_chars <= 8_000


def test_writer_pack_uses_current_brief_and_previous_summary_not_full_context():
    builder, records = fixture_builder()

    pack = builder.for_writer(
        "run-1",
        reference(records["mission"]),
        reference(records["blueprint"]),
        reference(records["batch_plan"]),
        lesson_index=1,
        previous_lesson_ref=reference(records["lesson"]),
        min_effective_chars=12_000,
    )

    assert [item.kind for item in pack.inputs] == [
        "mission",
        "blueprint",
        "batch_plan",
    ]
    serialized = pack.model_dump_json()
    assert "条件控制" in serialized
    assert "已经解释变量赋值" in serialized
    assert "下一章解释条件分支" in serialized
    assert "这是一段候选正文" not in serialized
    assert "private_notes" not in serialized
    assert pack.inputs[0].content == {
        "generation_constraints": {"min_effective_chars": 12_000}
    }
    assert "token_limit" not in serialized
    assert pack.total_chars <= 12_000


def test_reviewer_pack_contains_candidate_and_minimum_rubric():
    builder, records = fixture_builder()

    pack = builder.for_reviewer(
        "run-1",
        reference(records["mission"]),
        reference(records["blueprint"]),
        reference(records["lesson"]),
        lesson_index=0,
    )

    serialized = pack.model_dump_json()
    assert "这是一段候选正文" in serialized
    assert "结构" in serialized
    assert "private_notes" not in serialized
    assert pack.total_chars <= 24_000


def test_mandatory_content_over_budget_escalates_instead_of_truncating():
    builder, _ = fixture_builder()
    oversized = CourseInput(
        topic="主题",
        audience="受众",
        goal="字" * 4_100,
        language="zh",
    )

    with pytest.raises(ContextBudgetError) as caught:
        builder.for_mission(oversized)

    assert caught.value.code == "context_budget_exceeded"


def test_writer_trimming_keeps_all_ids_and_latest_continuity_constraints():
    builder, records = fixture_builder()
    records["batch_plan"].content["continuity_ledger"] = [
        {
            "lesson_id": f"lesson-{index}",
            "summary": "摘" * 400,
            "terminology": ["术" * 80] * 5,
            "next_promises": ["承" * 100] * 2,
        }
        for index in range(40)
    ]

    pack = builder.for_writer(
        "run-1",
        reference(records["mission"]),
        reference(records["blueprint"]),
        reference(records["batch_plan"]),
        lesson_index=1,
        previous_lesson_ref=reference(records["lesson"]),
    )
    ledger = pack.inputs[2].content["continuity_ledger"]

    assert pack.truncated is True
    assert pack.total_chars <= 12_000
    assert [entry["lesson_id"] for entry in ledger] == [
        f"lesson-{index}" for index in range(40)
    ]
    assert ledger[0]["summary"] == ""
    assert ledger[0]["terminology"] == []
    assert ledger[-1]["terminology"]
