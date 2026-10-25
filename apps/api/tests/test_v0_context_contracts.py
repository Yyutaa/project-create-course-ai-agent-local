import pytest
from pydantic import ValidationError

from app.v0.context_contracts import (
    ContinuityNoteV1,
    RepairPackV1,
    ReviewerPackV1,
    WriterPackV1,
)


REF = {
    "run_id": "run-1", "artifact_id": "artifact-1", "version": 1,
    "kind": "lesson", "content_hash": "hash-1",
}
SOURCE = {
    "document_id": "doc-1", "url": "https://react.dev/reference/react/useState",
    "title": "useState", "excerpt": "React reference", "content_hash": "source-hash",
}


def writer_data():
    return {
        "chapter_number": 1,
        "min_effective_chars": 12_000,
        "brief": {"title": "State", "learning_goal": "解释状态", "evidence": "练习"},
        "mission_ref": {**REF, "kind": "mission"},
        "blueprint_ref": {**REF, "kind": "blueprint"},
        "batch_plan_ref": {**REF, "kind": "batch_plan"},
        "source_policy": "仅允许使用公开官方资料",
        "source_summaries": [],
        "source_evidence_status": "missing",
        "rule_ids": ["teach.writer"],
        "continuity_ledger": [],
    }


def test_writer_pack_rejects_invalid_external_chapter_and_excess_sources():
    assert WriterPackV1.model_validate(writer_data()).previous_summary is None
    for change in (
        {"chapter_number": 0},
        {"chapter_number": 2},
        {"min_effective_chars": 0},
        {"source_summaries": [SOURCE] * 4},
        {"brief": {"title": "", "learning_goal": "解释", "evidence": "练习"}},
        {"blueprint_ref": {**REF, "kind": "blueprint", "run_id": "other-run"}},
        {"extra": "leak"},
    ):
        with pytest.raises(ValidationError):
            WriterPackV1.model_validate({**writer_data(), **change})


def test_ledger_and_feedback_packs_do_not_accept_full_history_or_empty_excerpt():
    note = ContinuityNoteV1(
        lesson_id="lesson-1", key_facts=["已解释状态"], next_goals=["下一章写更新"]
    )
    assert set(note.model_dump()) == {"lesson_id", "key_facts", "next_goals"}
    with pytest.raises(ValidationError):
        ContinuityNoteV1.model_validate({**note.model_dump(), "markdown": "全文"})
    with pytest.raises(ValidationError):
        ReviewerPackV1.model_validate({
            "chapter_number": 1, "brief": writer_data()["brief"],
            "lesson_ref": REF, "candidate_markdown": "正文", "gate": "rubric",
            "rule_ids": ["teach.review"], "history": ["旧 Finding"],
        })
    with pytest.raises(ValidationError):
        RepairPackV1.model_validate({
            "finding_id": "finding-1", "lesson_ref": REF,
            "quality_ref": {**REF, "kind": "quality"},
            "line_number": 1, "excerpt": "", "excerpt_hash": "hash",
            "rule_id": "humanizer.language.filler", "target": "删去套话",
        })
