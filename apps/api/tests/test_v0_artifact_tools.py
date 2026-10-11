import pytest

from app.v0.agents import AGENT_DEFINITIONS
from app.v0.artifact_tools import ArtifactTools, ToolPermissionError
from app.v0.schemas import ArtifactRecord, ArtifactRef


def artifact(kind, artifact_id, content, content_hash):
    return ArtifactRecord(
        artifact_id=artifact_id,
        version=1,
        run_id="r1",
        kind=kind,
        content=content,
        content_hash=content_hash,
    )


def test_read_artifact_checks_role_run_kind_version_and_hash():
    mission = artifact(
        "mission",
        "a-mission",
        {
            "audience": "初学者",
            "learning_goal": "完成页面",
            "scope": "React 基础",
            "stop_conditions": ["目标冲突时停止"],
        },
        "mission-hash",
    )
    tools = ArtifactTools(AGENT_DEFINITIONS, lambda artifact_id, version: mission)
    valid = ArtifactRef(
        run_id="r1",
        artifact_id="a-mission",
        version=1,
        kind="mission",
        content_hash="mission-hash",
    )

    assert tools.read_artifact("blueprint", "r1", valid).content == mission.content
    with pytest.raises(ToolPermissionError, match="Run"):
        tools.read_artifact("blueprint", "r2", valid.model_copy(update={"run_id": "r2"}))
    with pytest.raises(ToolPermissionError, match="hash"):
        tools.read_artifact(
            "blueprint", "r1", valid.model_copy(update={"content_hash": "wrong"})
        )
    with pytest.raises(ToolPermissionError, match="无权读取"):
        tools.read_artifact("reviewer", "r1", valid.model_copy(update={"kind": "quality"}))


def test_write_permission_is_checked_before_persist_callback():
    calls = []
    tools = ArtifactTools(
        AGENT_DEFINITIONS,
        lambda artifact_id, version: (_ for _ in ()).throw(AssertionError("不应读取")),
    )

    with pytest.raises(ToolPermissionError, match="无权写入"):
        tools.write_candidate_artifact(
            "reviewer",
            "r1",
            "lesson",
            {"title": "第一课", "markdown": "# 第一课"},
            [],
            calls.append,
        )

    assert calls == []


def test_write_validates_every_source_before_persisting_candidate():
    records = {
        "mission": artifact(
            "mission",
            "a-mission",
            {
                "audience": "初学者",
                "learning_goal": "完成页面",
                "scope": "React 基础",
                "stop_conditions": ["目标冲突时停止"],
            },
            "mission-hash",
        ),
        "blueprint": artifact(
            "blueprint",
            "a-blueprint",
            {
                "lessons": [
                    {
                        "title": "第一课",
                        "learning_goal": "完成页面",
                        "evidence": "页面可运行",
                    }
                ]
            },
            "blueprint-hash",
        ),
        "lesson": artifact(
            "lesson",
            "a-lesson",
            {"title": "第一课", "markdown": "# 第一课"},
            "lesson-hash",
        ),
    }
    refs = [
        ArtifactRef(
            run_id="r1",
            artifact_id=record.artifact_id,
            version=1,
            kind=record.kind,
            content_hash=record.content_hash,
        )
        for record in records.values()
    ]
    tools = ArtifactTools(
        AGENT_DEFINITIONS,
        lambda artifact_id, version: next(
            record for record in records.values() if record.artifact_id == artifact_id
        ),
    )
    persisted = []

    result = tools.write_candidate_artifact(
        "reviewer",
        "r1",
        "quality",
        {
            "status": "ready",
            "checks": ["结构完整"],
            "findings": [],
            "language_risk": "需要人工复读",
            "limitations": ["事实未核验"],
        },
        refs,
        lambda candidate: persisted.append(candidate) or candidate,
    )

    assert result.producer_role == "reviewer"
    assert result.kind == "quality"
    assert result.source_refs == refs
    assert len(persisted) == 1
