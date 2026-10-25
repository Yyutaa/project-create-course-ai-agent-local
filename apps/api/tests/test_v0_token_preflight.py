import pytest

from app.v0.prompt_render import render_agent_messages
from app.v0.schemas import MissionDraft
from app.v0.provider import AgentInput, AgentRequest
from app.v0.token_preflight import (
    TokenPreflightError, count_final_messages, preflight_request,
)


def request():
    return AgentRequest(
        role="mission", run_id="run-1", context_contract_version=1,
        goal="形成任务定义", instructions=["只写已核验事实"],
        inputs=[AgentInput(kind="intake", content={"topic": "变量"})],
        output_schema=MissionDraft.model_json_schema(),
    )


def test_preflight_counts_the_exact_messages_rendered_for_provider():
    rendered = render_agent_messages(request())
    result = preflight_request(
        request(), "deepseek-flash", counter=lambda value: len(value),
        token_limit=100_000,
    )
    assert result.messages == rendered
    assert "output_schema" in rendered[0].content
    assert "变量" in rendered[1].content
    assert result.preflight_estimate >= len(rendered[0].content)


def test_preflight_rejects_unsupported_model_and_excess_before_send():
    with pytest.raises(TokenPreflightError, match="tokenizer"):
        preflight_request(request(), "unknown-model")
    with pytest.raises(TokenPreflightError, match="预算"):
        preflight_request(
            request(), "deepseek-flash", counter=lambda value: len(value),
            token_limit=100,
        )


def test_tool_result_and_tool_schema_are_included_in_each_count():
    messages = [{"role": "tool", "tool_call_id": "call-1", "content": "来源正文"}]
    base = count_final_messages(messages, counter=lambda value: len(value))
    with_tools = count_final_messages(
        messages, counter=lambda value: len(value),
        tools=[{"function": {"name": "search", "parameters": {"type": "object"}}}],
    )
    assert with_tools > base
