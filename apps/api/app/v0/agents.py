"""Reviewable role definitions for the model-backed V0 stages."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel
from pydantic import ValidationError

from app.v0.provider import AgentInput, AgentRequest, Provider, ProviderError
from app.v0.schemas import (
    AgentRole,
    ArtifactKind,
    BlueprintDraft,
    LessonDraft,
    MissionDraft,
    QualitySummary,
    ArtifactRef,
)


ToolName = Literal["read_artifact", "write_candidate_artifact"]


@dataclass(frozen=True)
class AgentDefinition:
    role: AgentRole
    goal: str
    input_kinds: tuple[ArtifactKind, ...]
    output_kind: ArtifactKind
    output_model: type[BaseModel]
    skill_slices: tuple[str, ...]
    refusal_conditions: tuple[str, ...]
    allowed_tools: frozenset[ToolName]


READ_WRITE = frozenset({"read_artifact", "write_candidate_artifact"})

AGENT_DEFINITIONS: dict[AgentRole, AgentDefinition] = {
    "mission": AgentDefinition(
        role="mission",
        goal="把不可变 Intake 整理成可验收的课程任务定义。",
        input_kinds=(),
        output_kind="mission",
        output_model=MissionDraft,
        skill_slices=(
            "teach-generator/建立课程任务定义：受众、目标、范围和停止条件",
            "teach-generator/来源政策：不得用模型记忆补充未核验事实",
        ),
        refusal_conditions=(
            "Intake 缺失或互相冲突时拒绝生成",
            "拒绝声称已经完成外部研究",
            "拒绝修改 Run 状态或决定 release",
        ),
        allowed_tools=READ_WRITE,
    ),
    "blueprint": AgentDefinition(
        role="blueprint",
        goal="根据 Mission 规划当前 V0 的单章学习路径和完成证据。",
        input_kinds=("mission",),
        output_kind="blueprint",
        output_model=BlueprintDraft,
        skill_slices=(
            "teach-generator/规划课程蓝图：学习成果、先修关系和完成证据",
            "teach-generator/research 是 blueprint 内部活动，证据不足时披露缺口",
        ),
        refusal_conditions=(
            "Mission 引用缺失时拒绝生成",
            "拒绝把无证据内容写成已核验事实",
            "拒绝新增顶层 research 或决定 release",
        ),
        allowed_tools=READ_WRITE,
    ),
    "writer": AgentDefinition(
        role="writer",
        goal="按 Mission、Blueprint 和 Batch Plan 生成一章中文候选正文。",
        input_kinds=("mission", "blueprint", "batch_plan"),
        output_kind="lesson",
        output_model=LessonDraft,
        skill_slices=(
            "teach-generator/逐章生成：只组装当前章节需要的上下文",
            "teach-generator/学生可见信息披露边界与九步完整性作者自查",
        ),
        refusal_conditions=(
            "任一输入 Artifact 缺失时拒绝生成",
            "拒绝越出 Blueprint 或改变 Mission",
            "拒绝更新 Run 状态或决定 release",
        ),
        allowed_tools=READ_WRITE,
    ),
    "reviewer": AgentDefinition(
        role="reviewer",
        goal="审查候选正文并形成结构化质量证据，不作发布决定。",
        input_kinds=("mission", "blueprint", "lesson"),
        output_kind="quality",
        output_model=QualitySummary,
        skill_slices=(
            "teach-generator/质量判断：结构、教学设计、限制和升级条件",
            "humanizer-zh/中文表达 Gate：只判断语言，不核验事实或代码",
        ),
        refusal_conditions=(
            "候选 Lesson 缺失时拒绝审查",
            "拒绝把语言评分当成事实或课程整体质量核验",
            "拒绝更新 Run 状态或决定 release",
        ),
        allowed_tools=READ_WRITE,
    ),
    "repair": AgentDefinition(
        role="repair",
        goal=(
            "只按 RepairTask 修复单行问题片段：在 LessonDraft.markdown 中仅返回"
            "一行替换文本，不返回整章；title 保持原章节标题。"
        ),
        input_kinds=("blueprint", "lesson", "quality"),
        output_kind="lesson",
        output_model=LessonDraft,
        skill_slices=(
            "teach-generator/按证据位置定向返工，禁止无边界整章重写",
            "humanizer-zh/仅对语言 Finding 修订表达并保持事实和术语",
        ),
        refusal_conditions=(
            "没有明确 Finding 时拒绝修订",
            "拒绝输出多行 Markdown 或整章正文",
            "拒绝扩大范围、覆盖旧版本或改写无证据事实",
            "拒绝更新 Run 状态或决定 release",
        ),
        allowed_tools=READ_WRITE,
    ),
}


class AgentExecutor:
    def __init__(self, provider: Provider, artifact_tools):
        self.provider = provider
        self.artifact_tools = artifact_tools

    def invoke(
        self,
        role: AgentRole,
        run_id: str,
        *,
        intake: BaseModel | None = None,
        source_refs: list[ArtifactRef] | None = None,
        inputs: list[AgentInput] | None = None,
    ) -> BaseModel:
        definition = AGENT_DEFINITIONS[role]
        references = list(source_refs or [])
        if inputs is not None:
            expected = ("intake",) if role == "mission" else definition.input_kinds
            if tuple(item.kind for item in inputs) != expected:
                raise ProviderError(f"{role} 的 Context Pack 输入不完整或顺序错误")
            for item in inputs:
                if item.reference is not None:
                    self.artifact_tools.read_artifact(role, run_id, item.reference)
        elif role == "mission":
            if intake is None or references:
                raise ProviderError("mission 需要且只接受 Intake 输入")
            inputs = [AgentInput(kind="intake", content=intake.model_dump())]
        else:
            if tuple(reference.kind for reference in references) != definition.input_kinds:
                raise ProviderError(f"{role} 的输入 Artifact 不完整或顺序错误")
            inputs = []
            for reference in references:
                record = self.artifact_tools.read_artifact(role, run_id, reference)
                inputs.append(
                    AgentInput(
                        kind=record.kind,
                        content=record.content,
                        reference=reference,
                    )
                )

        request = AgentRequest(
            role=role,
            run_id=run_id,
            goal=definition.goal,
            instructions=[*definition.skill_slices, *definition.refusal_conditions],
            inputs=inputs,
            output_schema=definition.output_model.model_json_schema(),
        )
        response = self.provider.invoke(request)
        if response.role != role:
            raise ProviderError(f"{role} Provider 返回了错误角色 {response.role}")
        try:
            return definition.output_model.model_validate(response.payload)
        except ValidationError as error:
            issue = error.errors()[0]
            path = ".".join(str(part) for part in issue["loc"]) or "根节点"
            raise ProviderError(f"{role} 输出校验失败：{path} ({issue['type']})") from error
