import json

import httpx
import pytest
from langchain_deepseek import ChatDeepSeek

from app.v0.provider import (
    AgentInput,
    AgentRequest,
    FakeProvider,
    ProviderError,
    RealProvider,
)
from app.v0.schemas import MissionDraft


def mission_request() -> AgentRequest:
    return AgentRequest(
        role="mission",
        goal="形成课程任务定义",
        instructions=["不得编造已核验事实"],
        inputs=[
            AgentInput(
                kind="intake",
                content={
                    "topic": "Python 变量",
                    "audience": "零基础学习者",
                    "goal": "能修改变量",
                    "language": "zh",
                },
            )
        ],
        output_schema=MissionDraft.model_json_schema(),
    )


def test_fake_provider_uses_the_same_structured_request_and_response():
    response = FakeProvider().invoke(mission_request())

    assert response.role == "mission"
    assert MissionDraft.model_validate(response.payload).learning_goal


def test_fake_provider_fails_only_at_selected_role():
    provider = FakeProvider(fail_at="writer")

    assert provider.invoke(mission_request()).payload["audience"]
    writer_request = mission_request().model_copy(update={"role": "writer"})
    with pytest.raises(ProviderError, match="writer"):
        provider.invoke(writer_request)


def test_real_provider_requires_configuration(monkeypatch):
    for key in (
        "COURSE_LLM_BASE_URL",
        "COURSE_LLM_MODEL",
        "COURSE_LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ProviderError, match="配置"):
        RealProvider.from_env().invoke(mission_request())


def test_real_provider_accepts_existing_repository_environment_names(monkeypatch):
    for key in ("COURSE_LLM_BASE_URL", "COURSE_LLM_MODEL", "COURSE_LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "existing-model")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "existing-private-token")

    provider = RealProvider.from_env()

    assert provider.base_url == "https://example.invalid/v1"
    assert provider.model == "existing-model"
    assert provider.api_key == "existing-private-token"


def test_real_provider_uses_langchain_prompt_and_structured_output(monkeypatch):
    monkeypatch.setenv("COURSE_LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("COURSE_LLM_MODEL", "classroom-model")
    monkeypatch.setenv("COURSE_LLM_API_KEY", "private-test-token")
    calls = []
    settings = []

    def respond(request):
        calls.append(request)
        output = {
            "audience": "零基础学习者",
            "learning_goal": "理解变量",
            "scope": "变量定义与修改",
            "stop_conditions": ["来源不足时暂停"],
        }
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test", "object": "chat.completion",
                "created": 1, "model": "classroom-model",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": json.dumps(output)},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 17, "completion_tokens": 9,
                          "total_tokens": 26},
            },
        )

    def chat_model(**kwargs):
        settings.append(kwargs)
        return ChatDeepSeek(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond))
        )

    monkeypatch.setattr("app.v0.provider.ChatDeepSeek", chat_model)
    result = RealProvider.from_env().invoke(mission_request())

    assert result.role == "mission"
    assert result.payload["learning_goal"] == "理解变量"
    assert (result.input_tokens, result.output_tokens) == (17, 9)
    assert len(calls) == 1
    body = json.loads(calls[0].content)
    assert str(calls[0].url) == "https://example.invalid/v1/chat/completions"
    assert calls[0].headers["Authorization"] == "Bearer private-test-token"
    assert body["model"] == "classroom-model"
    assert body["response_format"] == {"type": "json_object"}
    assert "output_schema" in body["messages"][0]["content"]
    assert "Python 变量" in body["messages"][1]["content"]
    assert settings[0]["timeout"] == 240
    assert settings[0]["max_retries"] == 0


def test_real_provider_rejects_non_object_json_without_echoing_content(monkeypatch):
    def respond(request):
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test", "object": "chat.completion",
                "created": 1, "model": "test-model",
                "choices": [{"index": 0, "message": {
                    "role": "assistant", "content": '["private-do-not-echo"]',
                }, "finish_reason": "stop"}],
            },
        )

    monkeypatch.setattr(
        "app.v0.provider.ChatDeepSeek",
        lambda **kwargs: ChatDeepSeek(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond))
        ),
    )
    with pytest.raises(ProviderError, match="mission.*JSON 对象") as caught:
        RealProvider("https://example.invalid", "test-model", "test-key").invoke(
            mission_request()
        )
    assert "private-do-not-echo" not in str(caught.value)


def test_real_provider_does_not_retry_or_echo_network_errors(monkeypatch):
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("private-do-not-echo")

    monkeypatch.setattr(
        "app.v0.provider.ChatDeepSeek",
        lambda **kwargs: ChatDeepSeek(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond))
        ),
    )
    with pytest.raises(ProviderError) as caught:
        RealProvider("https://example.invalid", "test-model", "test-key").invoke(
            mission_request()
        )
    assert len(calls) == 1
    assert "private-do-not-echo" not in str(caught.value)
