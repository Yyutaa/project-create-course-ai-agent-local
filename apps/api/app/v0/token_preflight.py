"""Offline, fail-closed estimate of messages sent to DeepSeek V4 models."""

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
from typing import Callable

from app.v0.prompt_render import render_agent_messages


TOKEN_BUDGETS = {
    "mission": 4_000,
    "blueprint": 8_000,
    "writer": 12_000,
    "reviewer": 24_000,
    "repair": 4_000,
}
MAX_OUTPUT_TOKENS = {
    "mission": 8_192,
    "blueprint": 8_192,
    "writer": 32_768,
    "reviewer": 8_192,
    "repair": 8_192,
}
SUPPORTED_MODELS = frozenset({"deepseek-flash", "deepseek-v4-pro"})
TOKENIZER_SHA256 = "89085f12ef79460ac5f66d1119325ddfc694b4ab209d80bbd81d35f081dc9614"


class TokenPreflightError(RuntimeError):
    code = "token_preflight_rejected"


@dataclass(frozen=True)
class PreflightResult:
    messages: list
    preflight_estimate: int
    token_limit: int


@lru_cache(maxsize=1)
def _counter() -> Callable[[str], int]:
    asset = Path(__file__).with_name("assets") / "deepseek_v4_tokenizer.json"
    try:
        raw = asset.read_bytes()
        if sha256(raw).hexdigest() != TOKENIZER_SHA256:
            raise TokenPreflightError("DeepSeek tokenizer 摘要不符")
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(str(asset))
    except TokenPreflightError:
        raise
    except Exception:
        raise TokenPreflightError("DeepSeek tokenizer 不可用") from None
    return lambda value: len(tokenizer.encode(value).ids)


def count_final_messages(
    messages: list,
    *,
    counter: Callable[[str], int],
    tools: list[dict] | None = None,
) -> int:
    items = []
    for message in messages:
        if isinstance(message, dict):
            items.append(message)
        else:
            items.append({"role": message.type, "content": message.content})
    serialized = json.dumps(
        {"messages": items, "tools": tools or []},
        ensure_ascii=False, separators=(",", ":"),
    )
    return counter(serialized) + 8 * len(messages)


def preflight_request(
    request,
    model: str,
    *,
    messages: list | None = None,
    tools: list[dict] | None = None,
    counter: Callable[[str], int] | None = None,
    token_limit: int | None = None,
) -> PreflightResult:
    if model not in SUPPORTED_MODELS:
        raise TokenPreflightError("当前模型没有受支持的离线 tokenizer")
    final_messages = messages if messages is not None else render_agent_messages(request)
    estimated = count_final_messages(
        final_messages, counter=counter or _counter(), tools=tools,
    )
    limit = token_limit or TOKEN_BUDGETS[request.role]
    required = (estimated * 6 + 4) // 5 + 128
    if required > limit:
        raise TokenPreflightError(
            f"最终消息预估 {estimated} Token，预留后需 {required} Token，"
            f"超过 {limit} Token 预算"
        )
    return PreflightResult(final_messages, estimated, limit)
