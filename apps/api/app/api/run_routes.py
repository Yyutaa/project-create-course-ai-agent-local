from typing import Annotated, Literal
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.v0.provider import LocalConfiguredProvider
from app.v0.local_config import ConfigError, LocalConfigStore
from app.v0.runner import V0Runner
from app.v0.schemas import (
    ArtifactRecord,
    ArtifactRef,
    ArtifactSummary,
    CourseInput,
    ReleaseDecision,
    RunContent,
    SnapshotRecord,
    V0Run,
)
from app.v0.storage import FactStore
from app.v0.execution import Command, CommandView, ExecutionReadModel, ExecutionStore
from app.v0.delivery import DeliveryEvidence, DeliveryStore
from app.v0.sensitive import safe_error


router = APIRouter(prefix="/api/v0/runs", tags=["v0-runs"])
DB_PATH = Path(__file__).resolve().parents[4] / ".course-agent" / "v0-facts.sqlite3"


def get_local_config() -> LocalConfigStore:
    return LocalConfigStore(DB_PATH)


@lru_cache(maxsize=1)
def get_runner() -> V0Runner:
    return V0Runner(
        LocalConfiguredProvider(get_local_config()), store=FactStore(DB_PATH)
    )


RunnerDep = Annotated[V0Runner, Depends(get_runner)]
IdempotencyKey = Annotated[str, Header(min_length=1, alias="Idempotency-Key")]


class ArtifactList(BaseModel):
    items: list[ArtifactSummary]


class RevisionInput(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    expected_checkpoint_id: str = Field(min_length=1)
    provider_limit: int | None = Field(default=None, ge=80)


class MissionReviewInput(BaseModel):
    action: Literal["approve", "revise"]
    mission_ref: ArtifactRef
    expected_checkpoint_id: str = Field(min_length=1)
    feedback: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_feedback(self) -> "MissionReviewInput":
        if self.action == "revise" and not (self.feedback or "").strip():
            raise ValueError("修订 Mission 必须填写修改意见")
        if self.action == "approve" and self.feedback is not None:
            raise ValueError("确认 Mission 不接受修改意见")
        return self


def _public_run(run: V0Run) -> V0Run:
    visible = run.model_copy(deep=True)
    visible.course_input.topic = "已隐藏"
    visible.course_input.audience = "已隐藏"
    visible.course_input.goal = "已隐藏"
    for stage in visible.stages:
        stage.input_summary = "已隐藏" if stage.input_summary else ""
        stage.output_summary = "已隐藏" if stage.output_summary else ""
        if stage.failure_reason:
            stage.failure_reason = safe_error(RuntimeError(stage.failure_reason))
    if visible.release_decision:
        visible.release_decision.reason = "已隐藏"
    return visible


@router.post("", status_code=202, response_model=V0Run)
def start_run(
    course_input: CourseInput,
    runner: RunnerDep,
    idempotency_key: IdempotencyKey,
) -> V0Run:
    if isinstance(runner.provider, LocalConfiguredProvider):
        try:
            runner.provider.config.require_credentials()
        except ConfigError:
            raise HTTPException(
                status_code=409,
                detail={"code": "llm_config_required", "message": "请配置 DeepSeek"},
            ) from None
    try:
        run, _ = runner.create_once(
            course_input, idempotency_key, enqueue_start=True
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _public_run(run)


@router.get("/{run_id}", response_model=V0Run)
def read_run(run_id: str, runner: RunnerDep) -> V0Run:
    try:
        return _public_run(runner.get(run_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Run 不存在") from error


@router.get("/{run_id}/content", response_model=RunContent)
def read_run_content(run_id: str, runner: RunnerDep) -> RunContent:
    try:
        return runner.store.get_run_content(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Run 不存在") from error


def _accept_command(
    run_id: str, kind: str, payload: dict, runner: V0Runner, key: str
) -> Command:
    try:
        return ExecutionStore(runner.store.path).accept(run_id, kind, payload, key)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Run 不存在") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{run_id}/stop", status_code=202, response_model=CommandView)
def stop_run(run_id: str, runner: RunnerDep, idempotency_key: IdempotencyKey) -> Command:
    return _accept_command(run_id, "STOP", {}, runner, idempotency_key)


@router.post("/{run_id}/resume", status_code=202, response_model=CommandView)
def resume_run(run_id: str, runner: RunnerDep, idempotency_key: IdempotencyKey) -> Command:
    return _accept_command(run_id, "RESUME", {}, runner, idempotency_key)


@router.post("/{run_id}/revise", status_code=202, response_model=CommandView)
def revise_run(
    run_id: str, revision: RevisionInput,
    runner: RunnerDep, idempotency_key: IdempotencyKey,
) -> Command:
    return _accept_command(
        run_id, "REVISE", revision.model_dump(), runner, idempotency_key
    )


@router.post("/{run_id}/mission-review", status_code=202, response_model=CommandView)
def review_mission(
    run_id: str, review: MissionReviewInput,
    runner: RunnerDep, idempotency_key: IdempotencyKey,
) -> Command:
    if review.mission_ref.run_id != run_id:
        raise HTTPException(status_code=409, detail="Mission 引用与 Run 不一致")
    return _accept_command(
        run_id, "MISSION_REVIEW", review.model_dump(exclude_none=True),
        runner, idempotency_key,
    )


@router.get("/{run_id}/execution", response_model=ExecutionReadModel)
def read_execution(run_id: str, runner: RunnerDep) -> ExecutionReadModel:
    try:
        return ExecutionStore(runner.store.path).read_model(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Run 不存在") from error


@router.get("/{run_id}/evidence", response_model=DeliveryEvidence)
def read_evidence(run_id: str, runner: RunnerDep) -> DeliveryEvidence:
    try:
        return DeliveryStore(runner.store.path).read(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Run 不存在") from error


@router.post("/{run_id}/release", response_model=V0Run)
def decide_release(
    run_id: str,
    decision: ReleaseDecision,
    runner: RunnerDep,
    idempotency_key: IdempotencyKey,
) -> V0Run:
    try:
        return _public_run(runner.decide(run_id, decision, idempotency_key))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Run 不存在") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/{run_id}/artifacts", response_model=ArtifactList)
def read_artifacts(run_id: str, runner: RunnerDep) -> ArtifactList:
    try:
        return ArtifactList(items=runner.store.list_artifacts(run_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Run 不存在") from error


@router.get("/{run_id}/snapshot", response_model=SnapshotRecord)
def read_snapshot(run_id: str, runner: RunnerDep) -> SnapshotRecord:
    try:
        snapshot = runner.store.get_snapshot(run_id)
        return snapshot.model_copy(update={"run": _public_run(snapshot.run)})
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Run 不存在") from error


artifact_router = APIRouter(prefix="/api/v0/artifacts", tags=["v0-artifacts"])


@artifact_router.get("/{artifact_id}/versions/{version}", response_model=ArtifactRecord)
def read_artifact(artifact_id: str, version: int, runner: RunnerDep) -> ArtifactRecord:
    try:
        return runner.store.get_artifact(artifact_id, version)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Artifact 不存在") from error
