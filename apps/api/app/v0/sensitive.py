"""Allowlisted operational errors; never publish arbitrary exception text."""

import re


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
})

REVIEWER_SCHEMA_ERROR = re.compile(
    r"reviewer (rubric|humanizer) 输出校验失败："
    r"(status|checks|findings|language_risk|limitations)"
    r"(?:\.[0-9]+|\.[a-z_]+)* \([a-z_]+\)"
)
HIDDEN_PROVIDER_ERROR = "ProviderError：细节已隐藏，请检查受限诊断信息"


def is_reviewer_schema_error(message: str) -> bool:
    return REVIEWER_SCHEMA_ERROR.fullmatch(message) is not None


def safe_recorded_error(message: str) -> str:
    """Preserve already-sanitized facts without exposing arbitrary stored text."""
    if message == HIDDEN_PROVIDER_ERROR or is_reviewer_schema_error(message):
        return message
    return safe_error(RuntimeError(message))


def safe_error(error: Exception) -> str:
    message = str(error)
    if message in SAFE_MESSAGES:
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
    if value in SAFE_MESSAGES:
        return value
    if re.fullmatch(
        r"(mission|blueprint|writer|reviewer|repair) Context Pack 超过 [0-9]+ 字符预算",
        value,
    ):
        return value
    return "等待人工处理；详细原文已隐藏"
