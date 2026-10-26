"""Decision-only payloads for human approval gates.

Only the current artifact summary, bounded metrics, allowed actions and short
guidance belong here. Checkpoint content, secrets and raw model output must
never be copied into this module's output.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.v0.schemas import ApprovalAction, ArtifactRef, V0Run
from app.v0.source_tools import is_direct_document_host


ApprovalType = Literal[
    "MISSION_APPROVAL",
    "QUALITY_APPROVAL",
    "SOURCE_APPROVAL",
    "RELEASE_APPROVAL",
]
ApprovalStep = Literal["mission", "blueprint", "generation", "quality", "release"]
MetricValue = str | int | float | bool | None


class ApprovalCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    url: str
    title: str
    status: str
    metadata_hash: str


class ApprovalOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    metrics: dict[str, MetricValue] = Field(default_factory=dict)
    refs: list[ArtifactRef] = Field(default_factory=list)
    candidates: list[ApprovalCandidate] = Field(default_factory=list)


class ApprovalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ApprovalType
    step: ApprovalStep
    title: str
    output: ApprovalOutput
    actions: list[ApprovalAction] = Field(min_length=1)
    guidance: str
    checkpoint_id: str | None = None


def _clip(value: str, limit: int = 500) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"


def _latest_ref(run: V0Run, kind: str) -> ArtifactRef | None:
    matches = [item for item in run.artifacts if item.kind == kind]
    if not matches:
        return None
    latest = max(matches, key=lambda item: item.version)
    return ArtifactRef(
        run_id=run.id,
        artifact_id=latest.artifact_id,
        version=latest.version,
        kind=latest.kind,
        content_hash=latest.content_hash,
    )


def mission_approval(
    run: V0Run, checkpoint_id: str | None = None,
) -> ApprovalPayload | None:
    mission = run.mission
    if mission is None:
        return None
    ref = _latest_ref(run, "mission")
    return ApprovalPayload(
        type="MISSION_APPROVAL",
        step="mission",
        title="确认课程任务定义",
        output=ApprovalOutput(
            summary=_clip(f"{mission.audience}：{mission.learning_goal}"),
            metrics={
                "scope_chars": len(mission.scope),
                "stop_conditions": len(mission.stop_conditions),
            },
            refs=[ref] if ref is not None else [],
        ),
        actions=["approve", "revise", "stop"],
        guidance="确认任务定义与需求一致；需要修改请填写修改意见。",
        checkpoint_id=checkpoint_id,
    )


def quality_approval(
    run: V0Run,
    *,
    checkpoint_id: str | None,
    retry_only: bool,
    quality_ref: ArtifactRef | None,
    lesson_ref: ArtifactRef,
) -> ApprovalPayload | None:
    if retry_only:
        return ApprovalPayload(
            type="QUALITY_APPROVAL",
            step="quality",
            title="重新检查当前章节",
            output=ApprovalOutput(
                summary="Reviewer 输出格式校验失败；当前章节需要重新检查。",
                metrics={
                    "status": "retry_only",
                    "finding_count": 0,
                    "gate_count": 0,
                    "limitation_count": 0,
                },
                refs=[lesson_ref],
            ),
            actions=["retry"],
            guidance="Reviewer 输出格式校验失败；可显式重新检查当前章节。",
            checkpoint_id=checkpoint_id,
        )
    quality = run.quality
    if quality is None:
        return None
    refs = [ref for ref in (quality_ref, lesson_ref) if ref is not None]
    return ApprovalPayload(
        type="QUALITY_APPROVAL",
        step="quality",
        title="处理课程质量结论",
        output=ApprovalOutput(
            summary=(
                f"质量状态 {quality.status}；{len(quality.findings)} 个发现；"
                f"{len(quality.limitations)} 条限制。"
            ),
            metrics={
                "status": quality.status,
                "finding_count": len(quality.findings),
                "gate_count": len(quality.gate_results),
                "limitation_count": len(quality.limitations),
            },
            refs=refs,
        ),
        actions=["retry", "accept", "stop"],
        guidance="核对质量结论与证据；接受风险必须填写说明，且不等同于质量通过。",
        checkpoint_id=checkpoint_id,
    )


def source_approval(
    *,
    step: Literal["blueprint", "generation"],
    checkpoint_id: str | None,
    candidates: list[dict],
    retry_remaining: int,
) -> ApprovalPayload:
    reviewable = [
        item
        for item in candidates
        if item.get("status") == "needs_human"
        and is_direct_document_host(str(item.get("url") or ""))
    ]
    shown = reviewable[:3]
    hidden = len(candidates) - len(shown)
    actions: list[ApprovalAction] = ["approve", "reject", "propose_url", "stop"]
    if retry_remaining > 0:
        actions.insert(3, "retry_search")
    return ApprovalPayload(
        type="SOURCE_APPROVAL",
        step=step,
        title="补充或确认官方来源",
        output=ApprovalOutput(
            summary=(
                f"{len(shown)} 个来源需人工判断；{hidden} 条检索记录已收起。"
                if shown
                else "没有可人工确认的候选；可继续自动查找或提供官方地址。"
            ),
            metrics={
                "candidate_count": len(shown),
                "hidden_candidate_count": hidden,
                "retry_remaining": retry_remaining,
            },
            candidates=[
                ApprovalCandidate(
                    id=str(item["id"]),
                    url=str(item["url"]),
                    title=str(item.get("title") or ""),
                    status=str(item["status"]),
                    metadata_hash=str(item["metadata_hash"]),
                )
                for item in shown
            ],
        ),
        actions=actions,
        guidance="只确认网站的官方归属；课程中的具体事实会另行核验。",
        checkpoint_id=checkpoint_id,
    )


def release_approval(
    run: V0Run, checkpoint_id: str | None = None,
) -> ApprovalPayload | None:
    quality = run.quality
    if quality is None:
        return None
    ref = _latest_ref(run, "quality")
    return ApprovalPayload(
        type="RELEASE_APPROVAL",
        step="release",
        title="决定是否准备发布",
        output=ApprovalOutput(
            summary=f"质量状态 {quality.status}；{len(quality.limitations)} 条限制。",
            metrics={
                "quality_status": quality.status,
                "finding_count": len(quality.findings),
                "limitation_count": len(quality.limitations),
            },
            refs=[ref] if ref is not None else [],
        ),
        actions=["prepare", "stop"],
        guidance="“准备发布”只记录人工意向，不会自动发布课程；发布仍需单独操作。",
        checkpoint_id=checkpoint_id,
    )
