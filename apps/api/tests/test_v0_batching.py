import pytest

from app.v0.batching import assign_blueprint_ids, build_batch_plan, complete_batch
from app.v0.schemas import ArtifactRef, BlueprintDraft, BlueprintLesson, LessonDraft


RAW_BLUEPRINT = {
    "lessons": [
        {
            "title": "环境准备",
            "learning_goal": "运行示例",
            "evidence": "命令退出码为 0",
        },
        {
            "title": "变量基础",
            "learning_goal": "修改变量",
            "evidence": "输出发生变化",
        },
        {
            "title": "条件控制",
            "learning_goal": "解释分支",
            "evidence": "两个分支均可触发",
        },
        {
            "title": "综合练习",
            "learning_goal": "完成练习",
            "evidence": "测试通过",
        },
    ]
}


def test_assigns_content_stable_lesson_and_batch_ids():
    first = assign_blueprint_ids(BlueprintDraft.model_validate(RAW_BLUEPRINT), batch_size=2)
    repeated = assign_blueprint_ids(
        BlueprintDraft.model_validate(RAW_BLUEPRINT), batch_size=2
    )

    assert [lesson.lesson_id for lesson in first.lessons] == [
        "lesson-e54a832c1970bd62",
        "lesson-0769aeaaf2855467",
        "lesson-2b2dacbc84e08adb",
        "lesson-a1726398aacdbc14",
    ]
    assert [lesson.batch_id for lesson in first.lessons] == [
        "batch-4667e41ac7c717a4",
        "batch-4667e41ac7c717a4",
        "batch-12631a1df5370b50",
        "batch-12631a1df5370b50",
    ]
    assert first == repeated


def test_batch_plan_preserves_order_and_stable_ids():
    blueprint = assign_blueprint_ids(
        BlueprintDraft.model_validate(RAW_BLUEPRINT), batch_size=2
    )

    plan = build_batch_plan(blueprint)

    assert plan.batches == [[0, 1], [2, 3]]
    assert plan.lesson_ids == [
        ["lesson-e54a832c1970bd62", "lesson-0769aeaaf2855467"],
        ["lesson-2b2dacbc84e08adb", "lesson-a1726398aacdbc14"],
    ]
    assert plan.batch_ids == [
        "batch-4667e41ac7c717a4",
        "batch-12631a1df5370b50",
    ]


def test_complete_batch_requires_every_planned_lesson_and_appends_ledger():
    blueprint = assign_blueprint_ids(
        BlueprintDraft.model_validate(RAW_BLUEPRINT), batch_size=2
    )
    plan = build_batch_plan(blueprint)
    first_batch_lessons = [
        LessonDraft(
            title=blueprint.lessons[index].title,
            markdown=f"# {blueprint.lessons[index].title}",
            lesson_id=blueprint.lessons[index].lesson_id,
            batch_id=blueprint.lessons[index].batch_id,
            continuity_summary=f"完成{blueprint.lessons[index].title}",
            terminology=[f"术语{index}"],
            next_promises=[f"承诺{index}"],
        )
        for index in plan.batches[0]
    ]
    refs = [
        ArtifactRef(
            run_id="run-1",
            artifact_id="lesson-artifact",
            version=index + 1,
            kind="lesson",
            content_hash=f"hash-{index + 1}",
        )
        for index in range(2)
    ]

    with pytest.raises(ValueError, match="完整"):
        complete_batch(plan, plan.batch_ids[0], [(first_batch_lessons[0], refs[0])])

    completed = complete_batch(
        plan,
        plan.batch_ids[0],
        list(zip(first_batch_lessons, refs, strict=True)),
    )

    assert [entry.lesson_id for entry in completed.continuity_ledger] == plan.lesson_ids[0]
    assert [entry.lesson_ref for entry in completed.continuity_ledger] == refs
    assert completed.continuity_ledger[0].terminology == ["术语0"]
    assert completed.continuity_ledger[1].next_promises == ["承诺1"]
    assert plan.continuity_ledger == []


def test_continuity_summary_is_bounded():
    with pytest.raises(ValueError, match="800"):
        LessonDraft(
            title="过长摘要",
            markdown="# 过长摘要",
            continuity_summary="字" * 801,
        )


def test_new_batch_ledger_uses_facts_and_goals_without_full_prose():
    blueprint = assign_blueprint_ids(BlueprintDraft.model_validate(RAW_BLUEPRINT))
    plan = build_batch_plan(blueprint)
    completed = []
    for index in plan.batches[0]:
        lesson = blueprint.lessons[index]
        completed.append((LessonDraft(
            title=lesson.title, markdown="# 不能进入台账的全文",
            lesson_id=lesson.lesson_id, batch_id=lesson.batch_id,
            key_facts=[f"事实 {index}"], next_goals=[f"目标 {index}"],
        ), ArtifactRef(
            run_id="run-1", artifact_id=f"artifact-{index}", version=1,
            kind="lesson", content_hash=f"hash-{index}",
        )))

    updated = complete_batch(
        plan, plan.batch_ids[0], completed, context_contract_version=1,
    )

    assert plan.continuity_ledger_v1 == []
    assert [note.key_facts for note in updated.continuity_ledger_v1] == [
        ["事实 0"], ["事实 1"], ["事实 2"],
    ]
    assert "不能进入台账的全文" not in updated.model_dump_json()


def test_identical_lessons_are_rejected_instead_of_sharing_identity():
    duplicate = BlueprintDraft(
        lessons=[
            BlueprintLesson(title="重复", learning_goal="相同目标", evidence="相同证据"),
            BlueprintLesson(title="重复", learning_goal="相同目标", evidence="相同证据"),
        ]
    )

    with pytest.raises(ValueError, match="lesson_id"):
        assign_blueprint_ids(duplicate)


def test_complete_batch_rejects_lesson_from_another_batch():
    blueprint = assign_blueprint_ids(BlueprintDraft.model_validate(RAW_BLUEPRINT))
    plan = build_batch_plan(blueprint)
    lesson = LessonDraft(
        title="错批次",
        markdown="# 错批次",
        lesson_id=plan.lesson_ids[0][0],
        batch_id="batch-other",
    )
    reference = ArtifactRef(
        run_id="run-1",
        artifact_id="artifact-1",
        version=1,
        kind="lesson",
        content_hash="hash-1",
    )

    with pytest.raises(ValueError, match="batch_id"):
        complete_batch(plan, plan.batch_ids[0], [(lesson, reference)])
