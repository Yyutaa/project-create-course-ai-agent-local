"""Evidence-bearing quality gates; no release decisions live here."""

from dataclasses import dataclass
from hashlib import sha256
import re

from pydantic import ValidationError

from app.v0.provider import AgentInput, AgentRequest, ProviderError

from app.v0.schemas import (
    ArtifactRef,
    Finding,
    FindingLocation,
    GateResult,
    LessonDraft,
    QualitySummary,
    RepairTask,
)

GATE_ORDER = ("deterministic", "rubric", "humanizer")


def effective_character_count(markdown: str) -> int:
    """Count visible lesson characters while preserving fenced code content."""
    prose_lines = []
    code_chars = 0
    fence_marker = None
    for line in markdown.splitlines():
        marker = re.match(r"^[ \t]*(`{3,}|~{3,})", line)
        if marker and (
            fence_marker is None or marker.group(1)[0] == fence_marker
        ):
            fence_marker = None if fence_marker else marker.group(1)[0]
            continue
        if fence_marker:
            code_chars += len(re.sub(r"\s+", "", line))
        else:
            prose_lines.append(line)
    text = "\n".join(prose_lines)
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"!?\[([^]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(
        r"(?m)^[ \t]*(?:#{1,6}[ \t]+|>[ \t]?|[-+*][ \t]+|\d+[.)][ \t]+)",
        "",
        text,
    )
    text = re.sub(r"[*_~`]", "", text)
    return code_chars + len(re.sub(r"\s+", "", text))


@dataclass(frozen=True)
class GateReport:
    results: list[GateResult]
    findings: list[Finding]


def check_markdown(
    markdown: str,
    reference: ArtifactRef,
    lesson_id: str,
    min_effective_chars: int | None = None,
) -> GateReport:
    """Check only syntax facts that are repeatable without a model."""
    lines = markdown.splitlines()
    problems: list[tuple[str, int, str, str]] = []
    if not lines or not lines[0].startswith("# ") or not lines[0][2:].strip():
        problems.append(("markdown.h1", 1, "首行缺少一级标题", "首行应为一级标题"))
    fence_line = 0
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            fence_line = 0 if fence_line else number
    if fence_line:
        problems.append(("markdown.fence", fence_line, "代码围栏未闭合", "闭合代码围栏"))
    findings = []
    results = []
    for rule_id, line_number, evidence, expected in problems:
        excerpt = lines[line_number - 1] if line_number <= len(lines) else ""
        findings.append(
            Finding(
                finding_id=sha256(
                    f"{reference.run_id}:{reference.artifact_id}:{reference.version}:"
                    f"{rule_id}:{line_number}".encode()
                ).hexdigest()[:16],
                run_id=reference.run_id,
                gate="deterministic",
                rule_id=rule_id,
                artifact_ref=reference,
                location=FindingLocation(
                    lesson_id=lesson_id,
                    line_start=line_number,
                    line_end=line_number,
                    excerpt_hash=sha256(excerpt.encode()).hexdigest(),
                ),
                category="structure",
                severity="major",
                evidence=evidence,
                expected=expected,
            )
        )
        results.append(
            GateResult(
                gate="deterministic",
                status="fail",
                rule_id=rule_id,
                evidence=evidence,
                artifact_ref=reference,
            )
        )
    if not problems:
        results.append(
            GateResult(
                gate="deterministic",
                status="pass",
                rule_id="markdown.structure",
                evidence="一级标题与代码围栏结构通过",
                artifact_ref=reference,
            )
        )
    actual_chars = effective_character_count(markdown)
    if min_effective_chars is not None and actual_chars < min_effective_chars:
        rule_id = "lesson.effective_chars.minimum"
        findings.append(
            Finding(
                finding_id=sha256(
                    f"{reference.run_id}:{reference.artifact_id}:{reference.version}:"
                    f"{rule_id}".encode()
                ).hexdigest()[:16],
                run_id=reference.run_id,
                gate="deterministic",
                rule_id=rule_id,
                artifact_ref=reference,
                location=FindingLocation(
                    lesson_id=lesson_id,
                    line_start=1,
                    line_end=max(1, len(lines)),
                    excerpt_hash=sha256(markdown.encode()).hexdigest(),
                ),
                category="structure",
                severity="blocker",
                evidence=f"当前有效字符数为 {actual_chars}",
                expected=f"有效字符数至少为 {min_effective_chars}",
            )
        )
        results.append(
            GateResult(
                gate="deterministic",
                status="fail",
                rule_id=rule_id,
                evidence=f"{actual_chars}/{min_effective_chars}",
                artifact_ref=reference,
            )
        )
    return GateReport(results, findings)


def review_gate(
    runner,
    gate: str,
    reference: ArtifactRef,
    lesson_id: str,
    markdown: str,
    rubric_inputs: list[AgentInput],
) -> GateReport:
    """Run the independent Reviewer in one narrowly scoped gate context."""
    if gate not in ("rubric", "humanizer"):
        raise ValueError("未知模型 Gate")
    if gate == "rubric":
        inputs = rubric_inputs
        instructions = [
            "只判断教学目标、解释和练习是否对应；逐项写出正文证据。",
            "事实来源不足时要求人工复核，不得猜测已核验。",
        ]
    else:
        inputs = [
            AgentInput(
                kind="lesson",
                reference=reference,
                content={"markdown": markdown, "lesson_id": lesson_id},
            )
        ]
        instructions = [
            "按 humanizer-zh 只检查中文表达；只能产生 language Finding。",
            "不得判断事实、教学、构建或 release。",
        ]
    response = runner.provider.invoke(
        AgentRequest(
            role="reviewer",
            run_id=reference.run_id,
            goal=f"{gate} 独立质量 Gate",
            instructions=instructions,
            inputs=inputs,
            output_schema=QualitySummary.model_json_schema(),
        )
    )
    if response.role != "reviewer":
        raise ProviderError("Reviewer Gate 返回错误角色")
    try:
        summary = QualitySummary.model_validate(response.payload)
    except ValidationError as error:
        issue = error.errors()[0]
        path = ".".join(str(part) for part in issue["loc"]) or "根节点"
        raise ProviderError(
            f"reviewer {gate} 输出校验失败：{path} ({issue['type']})"
        ) from error
    findings = []
    lines = markdown.splitlines()
    for item in summary.findings:
        if gate == "humanizer" and item.category != "language":
            raise ProviderError("Humanizer 越权产生非表达 Finding")
        if gate == "rubric" and item.category not in ("teaching", "fact"):
            raise ProviderError("Rubric 越权产生非教学 Finding")
        match = next(
            (
                (number, line)
                for number, line in enumerate(lines, 1)
                if item.evidence in line
            ),
            None,
        )
        if match is None:
            raise ProviderError("Reviewer Finding 缺少可定位的正文证据")
        number, excerpt = match
        findings.append(
            Finding(
                finding_id=sha256(
                    f"{reference.run_id}:{lesson_id}:{gate}:{item.code}:{number}".encode()
                ).hexdigest()[:16],
                run_id=reference.run_id,
                gate=gate,
                rule_id=item.code,
                artifact_ref=reference,
                location=FindingLocation(
                    lesson_id=lesson_id,
                    line_start=number,
                    line_end=number,
                    excerpt_hash=sha256(excerpt.encode()).hexdigest(),
                ),
                category=item.category,
                severity=item.severity,
                evidence=item.evidence,
                expected=item.recommendation,
            )
        )
    status = "pass" if summary.status == "ready" and not findings else "fail"
    return GateReport(
        [
            GateResult(
                gate=gate,
                status=status,
                rule_id=f"{gate}.minimum",
                evidence=(
                    "；".join(summary.checks)[:300] + f"；正文证据：{markdown[:160]}"
                ),
                artifact_ref=reference,
            )
        ],
        findings,
    )


def make_repair_task(finding: Finding, markdown: str) -> RepairTask:
    lines = markdown.splitlines()
    number = finding.location.line_start
    if finding.location.line_end != number or number > len(lines):
        raise ValueError("Finding 片段无法局部修复")
    excerpt = lines[number - 1]
    if sha256(excerpt.encode()).hexdigest() != finding.location.excerpt_hash:
        raise ValueError("Finding 片段与源版本不一致")
    return RepairTask(
        finding_id=finding.finding_id,
        source_ref=finding.artifact_ref,
        line_start=number,
        excerpt=excerpt,
        excerpt_hash=finding.location.excerpt_hash,
        rule_id=finding.rule_id,
        objective=finding.expected,
    )


def apply_repair(task: RepairTask, replacement: str, original: LessonDraft) -> LessonDraft:
    if not replacement.strip() or "\n" in replacement.strip("\n"):
        raise ValueError("Repair 必须返回单行替换片段")
    lines = original.markdown.splitlines()
    number = task.line_start
    if (
        number > len(lines)
        or sha256(lines[number - 1].encode()).hexdigest() != task.excerpt_hash
    ):
        raise ValueError("Repair 源片段已变化")
    lines[number - 1] = replacement.strip("\n")
    return original.model_copy(update={"markdown": "\n".join(lines)})
