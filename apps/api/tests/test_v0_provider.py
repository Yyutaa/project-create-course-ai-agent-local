import json
from io import BytesIO

import pytest

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


def test_real_provider_posts_structured_request_and_returns_json_object(monkeypatch):
    monkeypatch.setenv("COURSE_LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("COURSE_LLM_MODEL", "classroom-model")
    monkeypatch.setenv("COURSE_LLM_API_KEY", "private-test-token")
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        output = {
            "audience": "零基础学习者",
            "learning_goal": "理解变量",
            "scope": "变量定义与修改",
            "stop_conditions": ["来源不足时暂停"],
        }
        return BytesIO(
            json.dumps({"choices": [{"message": {"content": json.dumps(output)}}]}).encode()
        )

    monkeypatch.setattr("app.v0.provider.urlopen", fake_urlopen)
    result = RealProvider.from_env().invoke(mission_request())

    assert result.role == "mission"
    assert result.payload["learning_goal"] == "理解变量"
    request, timeout = calls[0]
    body = json.loads(request.data)
    assert request.full_url == "https://example.invalid/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer private-test-token"
    assert body["model"] == "classroom-model"
    assert body["response_format"] == {"type": "json_object"}
    assert "output_schema" in body["messages"][0]["content"]
    assert "Python 变量" in body["messages"][1]["content"]
    assert timeout == 240


def test_real_provider_rejects_non_object_json_without_echoing_content(monkeypatch):
    def fake_urlopen(request, timeout):
        content = json.dumps(["private-do-not-echo"])
        return BytesIO(
            json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        )

    monkeypatch.setattr("app.v0.provider.urlopen", fake_urlopen)
    with pytest.raises(ProviderError, match="mission.*JSON 对象") as caught:
        RealProvider("https://example.invalid", "test-model", "test-key").invoke(
            mission_request()
        )
    assert "private-do-not-echo" not in str(caught.value)
