"""Deterministic batch identities and continuity ledger updates."""

from hashlib import sha256
import json

from app.v0.schemas import (
    ArtifactRef,
    BatchPlanDraft,
    BlueprintDraft,
    ContinuityEntry,
    LessonDraft,
)


def _stable_id(prefix: str, value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{prefix}-{sha256(canonical.encode('utf-8')).hexdigest()[:16]}"


def assign_blueprint_ids(
    blueprint: BlueprintDraft, *, batch_size: int = 3
) -> BlueprintDraft:
    if batch_size < 1:
        raise ValueError("batch_size 必须大于 0")

    lessons = []
    for lesson in blueprint.lessons:
        lesson_id = _stable_id(
            "lesson",
            {
                "title": lesson.title,
                "learning_goal": lesson.learning_goal,
                "evidence": lesson.evidence,
            },
        )
        lessons.append(lesson.model_copy(update={"lesson_id": lesson_id}))

    lesson_ids = [lesson.lesson_id for lesson in lessons]
    if len(set(lesson_ids)) != len(lesson_ids):
        raise ValueError("Blueprint 生成了重复 lesson_id，请合并或区分重复章节")

    for start in range(0, len(lessons), batch_size):
        group = lessons[start : start + batch_size]
        batch_id = _stable_id("batch", [lesson.lesson_id for lesson in group])
        lessons[start : start + batch_size] = [
            lesson.model_copy(update={"batch_id": batch_id}) for lesson in group
        ]
    return blueprint.model_copy(update={"lessons": lessons})


def build_batch_plan(blueprint: BlueprintDraft) -> BatchPlanDraft:
    batches: list[list[int]] = []
    batch_ids: list[str] = []
    lesson_ids: list[list[str]] = []
    for index, lesson in enumerate(blueprint.lessons):
        if lesson.lesson_id is None or lesson.batch_id is None:
            raise ValueError("Blueprint 缺少稳定 lesson_id 或 batch_id")
        if not batch_ids or batch_ids[-1] != lesson.batch_id:
            batch_ids.append(lesson.batch_id)
            batches.append([])
            lesson_ids.append([])
        batches[-1].append(index)
        lesson_ids[-1].append(lesson.lesson_id)
    return BatchPlanDraft(
        batches=batches,
        batch_ids=batch_ids,
        lesson_ids=lesson_ids,
    )


def complete_batch(
    plan: BatchPlanDraft,
    batch_id: str,
    completed: list[tuple[LessonDraft, ArtifactRef]],
) -> BatchPlanDraft:
    try:
        batch_index = plan.batch_ids.index(batch_id)
    except ValueError as error:
        raise ValueError("Batch Plan 不包含当前 batch_id") from error

    expected = plan.lesson_ids[batch_index]
    actual = [lesson.lesson_id for lesson, _ in completed]
    if any(lesson.batch_id != batch_id for lesson, _ in completed):
        raise ValueError("Lesson batch_id 与当前批次不一致")
    if actual != expected:
        raise ValueError("批次必须完整并按计划顺序完成")
    if any(entry.batch_id == batch_id for entry in plan.continuity_ledger):
        raise ValueError("批次已经写入 continuity ledger")

    entries = [
        ContinuityEntry(
            batch_id=batch_id,
            lesson_id=lesson.lesson_id,
            lesson_ref=reference,
            summary=lesson.continuity_summary,
            terminology=lesson.terminology,
            next_promises=lesson.next_promises,
        )
        for lesson, reference in completed
        if lesson.lesson_id is not None
    ]
    return plan.model_copy(
        update={"continuity_ledger": [*plan.continuity_ledger, *entries]},
        deep=True,
    )
