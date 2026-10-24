"""Permission-checked Artifact reads and candidate writes."""

from dataclasses import dataclass
from typing import Callable, TypeVar

from pydantic import BaseModel

from app.v0.agents import AgentDefinition
from app.v0.schemas import (
    AgentRole,
    ArtifactKind,
    ArtifactRecord,
    ArtifactRef,
    ProducerRole,
)


class ToolPermissionError(ValueError):
    """The requested Artifact operation is outside the role definition."""


@dataclass(frozen=True)
class ArtifactCandidate:
    kind: ArtifactKind
    producer_role: ProducerRole
    content: BaseModel
    source_refs: list[ArtifactRef]


ResultT = TypeVar("ResultT")


class ArtifactTools:
    def __init__(
        self,
        definitions: dict[AgentRole, AgentDefinition],
        loader: Callable[[str, int], ArtifactRecord],
    ):
        self.definitions = definitions
        self.loader = loader

    def read_artifact(
        self, role: AgentRole, run_id: str, reference: ArtifactRef
    ) -> ArtifactRecord:
        definition = self.definitions[role]
        if "read_artifact" not in definition.allowed_tools:
            raise ToolPermissionError(f"{role} 无权读取 Artifact")
        if reference.kind not in definition.input_kinds and not (
            (role == "mission" and reference.kind == "mission")
            or (role == "blueprint" and reference.kind == "blueprint")
        ):
            raise ToolPermissionError(f"{role} 无权读取 {reference.kind} Artifact")
        if reference.run_id != run_id:
            raise ToolPermissionError("Artifact 与当前 Run 不一致")

        record = self.loader(reference.artifact_id, reference.version)
        if record.run_id != run_id:
            raise ToolPermissionError("Artifact 与当前 Run 不一致")
        if record.kind != reference.kind:
            raise ToolPermissionError("Artifact kind 与引用不一致")
        if record.content_hash != reference.content_hash:
            raise ToolPermissionError("Artifact hash 与引用不一致")
        return record

    def write_candidate_artifact(
        self,
        role: AgentRole,
        run_id: str,
        kind: ArtifactKind,
        payload: BaseModel | dict,
        source_refs: list[ArtifactRef],
        persist: Callable[[ArtifactCandidate], ResultT],
    ) -> ResultT:
        definition = self.definitions[role]
        if "write_candidate_artifact" not in definition.allowed_tools:
            raise ToolPermissionError(f"{role} 无权写入 Artifact")
        if kind != definition.output_kind:
            raise ToolPermissionError(f"{role} 无权写入 {kind} Artifact")
        kinds = tuple(reference.kind for reference in source_refs)
        if kinds != definition.input_kinds and not (
            (role == "mission" and kinds == ("mission",))
            or (role == "blueprint" and kinds == ("mission", "blueprint"))
        ):
            raise ToolPermissionError(f"{role} 的输入 Artifact 不完整或顺序错误")

        for reference in source_refs:
            self.read_artifact(role, run_id, reference)
        content = definition.output_model.model_validate(
            payload.model_dump() if isinstance(payload, BaseModel) else payload
        )
        candidate = ArtifactCandidate(
            kind=kind,
            producer_role=role,
            content=content,
            source_refs=list(source_refs),
        )
        return persist(candidate)
