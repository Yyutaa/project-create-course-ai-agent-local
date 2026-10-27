"""Allowlisted operational errors; never publish arbitrary exception text."""

import re

from pydantic import ValidationError


SAFE_MESSAGES = frozenset({
    "blueprint_chapter_deviation",
    "lesson_effective_chars_below_minimum",
    "token_limit_reached",
    "source_evidence_insufficient",
    "source_review_required",
    "provider_transient_exhausted_timeout",
    "provider_transient_exhausted_http_429",
    "stop_requested_during_provider_retry",
    "Rubric 越权产生非教学 Finding",
    "Humanizer 越权产生非表达 Finding",
    "Reviewer Finding 缺少可定位的正文证据",
    "Provider 调用预算耗尽，需要人工处理",
    "LLM 配置不完整：请设置 base_url、model 和 api_key",
    "阶段执行失败；请检查服务端日志",
    "返工预算耗尽，需要人工处理",
    "质量证据需要人工复核",
    "批次循环达到 20 次上限，需要人工处理",
    "接管后验证结论与已提交决定不一致，需要人工处理",
    "Candidate 未通过独立验证，需人工处理",
    "只有已准备发布的 Run 才能发布",
    "发布需要持久化事实库",
    "存在未生成的章节，无法发布完整课程",
    "Run 缺少课程归属，无法发布",
    "课程目录无法读取",
    "课程目录格式不合法",
    "课程目录写入失败",
    "Mission 审批已保存；后续阶段失败，请查看执行记录",
    "Mission 待人工确认，请提交 MISSION_REVIEW",
    "数据校验失败；请检查当前阶段输入",
    "历史数据校验失败；未保存字段详情",
})

REVIEWER_SCHEMA_ERROR = re.compile(
    r"reviewer (rubric|humanizer) 输出校验失败："
    r"(status|checks|findings|language_risk|limitations)"
    r"(?:\.[0-9]+|\.[a-z_]+)* \([a-z_]+\)"
)
HIDDEN_PROVIDER_ERROR = "ProviderError：细节已隐藏，请检查受限诊断信息"
HIDDEN_VALUE_ERROR = "ValueError：细节已隐藏，请检查受限诊断信息"
LEGACY_TOKEN_PREFLIGHT_REASON = (
    "Token 预检未通过；该历史记录的具体原因未保存。"
    "可能是消息超预算、模型不受支持或 tokenizer 不可用。"
)
TOKEN_PREFLIGHT_DETAILS = frozenset({
    "DeepSeek tokenizer 摘要不符",
    "DeepSeek tokenizer 不可用",
    "当前模型没有受支持的离线 tokenizer",
    "最终消息超过 Token 预算",
})
TOKEN_PREFLIGHT_BUDGET = re.compile(
    r"最终消息预估 [0-9]+ Token，预留后需 [0-9]+ Token，"
    r"超过 [0-9]+ Token 预算"
)
VALIDATION_ERROR = re.compile(
    r"数据校验失败：[a-z_][a-z0-9_]*"
    r"(?:\.(?:[a-z_][a-z0-9_]*|[0-9]+))* \([a-z_]+\)"
)


def is_reviewer_schema_error(message: str) -> bool:
    return REVIEWER_SCHEMA_ERROR.fullmatch(message) is not None


def is_token_preflight_detail(message: str) -> bool:
    return (
        message in TOKEN_PREFLIGHT_DETAILS
        or TOKEN_PREFLIGHT_BUDGET.fullmatch(message) is not None
    )


def safe_recorded_error(message: str) -> str:
    """Preserve already-sanitized facts without exposing arbitrary stored text."""
    if message == "token_preflight_rejected":
        return LEGACY_TOKEN_PREFLIGHT_REASON
    if message in (HIDDEN_PROVIDER_ERROR, HIDDEN_VALUE_ERROR) or is_reviewer_schema_error(message):
        return message
    return safe_error(RuntimeError(message))


def mission_review_downstream_error(stage: str, reason: str) -> str:
    detail = (
        "历史数据校验失败；未保存字段详情"
        if reason == "ValidationError：细节已隐藏，请检查受限诊断信息"
        else safe_recorded_error(reason)
    )
    return f"Mission 审批已保存；后续 {stage} 阶段失败：{detail}"


def safe_error(error: Exception) -> str:
    message = str(error)
    if isinstance(error, ValidationError):
        issues = error.errors(include_input=False, include_url=False)
        if issues:
            path = ".".join(str(item) for item in issues[0]["loc"])
            summary = f"数据校验失败：{path} ({issues[0]['type']})"
            if VALIDATION_ERROR.fullmatch(summary):
                return summary
        return "数据校验失败；请检查当前阶段输入"
    if VALIDATION_ERROR.fullmatch(message):
        return message
    downstream = re.fullmatch(
        r"Mission 审批已保存；后续 "
        r"(intake|mission|blueprint|batch_plan|generation|quality|release) "
        r"阶段失败：(.+)", message,
    )
    if downstream and safe_recorded_error(downstream.group(2)) == downstream.group(2):
        return message
    if message in SAFE_MESSAGES:
        return message
    if is_token_preflight_detail(message):
        return message
    if is_reviewer_schema_error(message):
        return message
    if re.fullmatch(r"(mission|blueprint|writer|reviewer|repair) 模型接口返回 HTTP [0-9]{3}", message):
        return message
    if re.fullmatch(r"(mission|blueprint|writer|reviewer|repair) 模型接口不可用或超时", message):
        return message
    if re.fullmatch(r"(mission|blueprint|writer|reviewer|repair) 固定失败夹具", message):
        return message
    if re.fullmatch(
        r"(mission|blueprint|writer|reviewer|repair) 输出校验失败："
        r"(audience|learning_goal|scope|stop_conditions|lessons|title|markdown|"
        r"status|checks|findings|language_risk|limitations)"
        r"(?:\.[0-9]+|\.[a-z_]+)* \([a-z_]+\)",
        message,
    ):
        return message
    return f"{type(error).__name__}：细节已隐藏，请检查受限诊断信息"


def safe_waiting_reason(value: str) -> str:
    if value == "token_preflight_rejected":
        return LEGACY_TOKEN_PREFLIGHT_REASON
    if value in SAFE_MESSAGES:
        return value
    if is_token_preflight_detail(value):
        return value
    if re.fullmatch(
        r"(mission|blueprint|writer|reviewer|repair) Context Pack 超过 [0-9]+ 字符预算",
        value,
    ):
        return value
    return "等待人工处理；详细原文已隐藏"
