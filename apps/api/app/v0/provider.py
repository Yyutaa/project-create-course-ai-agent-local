from __future__ import annotations

import json
import os
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.v0.local_config import ConfigError, LocalConfigStore
from app.v0.schemas import AgentRole, ArtifactRef


InputKind = Literal["intake", "mission", "blueprint", "batch_plan", "lesson", "quality"]


class ProviderError(RuntimeError):
    """A model request failed without exposing credentials or raw prompts."""


class AgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: InputKind
    content: dict
    reference: ArtifactRef | None = None

    @model_validator(mode="after")
    def validate_reference(self) -> "AgentInput":
        if self.kind == "intake" and self.reference is not None:
            raise ValueError("Intake 输入不能引用 Artifact")
        if self.kind != "intake" and self.reference is None:
            raise ValueError("Artifact 输入必须包含精确引用")
        if self.reference is not None and self.reference.kind != self.kind:
            raise ValueError("Artifact 输入 kind 与引用不一致")
        return self


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AgentRole
    run_id: str | None = None
    goal: str = Field(min_length=1)
    instructions: list[str] = Field(min_length=1)
    inputs: list[AgentInput] = Field(min_length=1)
    output_schema: dict


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AgentRole
    payload: dict
    input_tokens: int | None = None
    output_tokens: int | None = None


class Provider(Protocol):
    def invoke(self, request: AgentRequest) -> AgentResponse: ...


class RealProvider:
    def __init__(self, base_url: str, model: str, api_key: str):
        self.base_url = base_url
        self.model = model
        self.api_key = api_key

    @classmethod
    def from_env(cls) -> RealProvider:
        return cls(
            os.getenv("COURSE_LLM_BASE_URL") or os.getenv("LLM_BASE_URL", ""),
            os.getenv("COURSE_LLM_MODEL") or os.getenv("LLM_MODEL", ""),
            os.getenv("COURSE_LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", ""),
        )

    def invoke(self, request: AgentRequest) -> AgentResponse:
        if not all((self.base_url, self.model, self.api_key)):
            raise ProviderError("LLM 配置不完整：请设置 base_url、model 和 api_key")

        system = {
            "role": request.role,
            "goal": request.goal,
            "instructions": request.instructions,
            "output_schema": request.output_schema,
            "rules": [
                "只返回一个符合 output_schema 的 JSON 对象",
                "不得修改 Run 状态或决定 release",
            ],
        }
        inputs = [item.model_dump(mode="json") for item in request.inputs]
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": json.dumps(system, ensure_ascii=False),
                },
                {
                    "role": "user",
                    "content": json.dumps({"inputs": inputs}, ensure_ascii=False),
                },
            ],
        }
        http_request = Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(http_request, timeout=240) as response:
                body = json.load(response)
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("模型未返回文本")
            result = json.loads(content)
            if not isinstance(result, dict):
                raise ProviderError(f"{request.role} 模型必须返回 JSON 对象")
            usage = body.get("usage") or {}
            return AgentResponse(
                role=request.role, payload=result,
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
            )
        except HTTPError as error:
            raise ProviderError(f"{request.role} 模型接口返回 HTTP {error.code}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise ProviderError(f"{request.role} 模型接口不可用或超时") from error
        except ProviderError:
            raise
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ProviderError(f"{request.role} 模型输出不是有效 JSON 对象") from error


class LocalConfiguredProvider:
    """Resolve the local setting for each model call, never at Worker startup."""

    def __init__(self, config: LocalConfigStore):
        self.config = config

    def invoke(self, request: AgentRequest) -> AgentResponse:
        try:
            model, key = self.config.require_credentials()
        except ConfigError:
            raise ProviderError("请配置 DeepSeek 后再运行") from None
        return RealProvider("https://api.deepseek.com", model, key).invoke(request)


class FakeProvider:
    def __init__(self, fail_at: AgentRole | None = None):
        self.fail_at = fail_at

    def invoke(self, request: AgentRequest) -> AgentResponse:
        if request.role == self.fail_at:
            raise ProviderError(f"{request.role} 固定失败夹具")

        fixtures = {
            "mission": {
                "audience": "零基础学习者",
                "learning_goal": "能解释并修改一个 Python 变量",
                "scope": "变量定义与修改",
                "stop_conditions": ["输入目标不清楚时暂停"],
            },
            "blueprint": {
                "lessons": [
                    {
                        "title": "Python 变量入门",
                        "learning_goal": "能解释并修改一个 Python 变量",
                        "evidence": "修改示例变量并说明输出",
                    }
                ]
            },
            "writer": {
                "title": "Python 变量入门",
                "markdown": (
                    "# Python 变量入门\n\n变量保存一个值。"
                    "例如，`name = '小林'` 后打印 `name` 会看到「小林」。"
                    "练习：把名字改成自己的名字，观察输出。"
                ),
            },
            "reviewer": {
                "status": "ready",
                "checks": ["标题和正文非空", "已记录中文表达风险"],
                "findings": [],
                "language_risk": "示例文案需由人工复读",
                "limitations": ["未核验事实来源", "未执行完整课程量规"],
            },
            "repair": {
                "title": "Python 变量入门",
                "markdown": "# Python 变量入门\n\n按明确 Finding 修订后的候选正文。",
            },
        }
        return AgentResponse(role=request.role, payload=fixtures[request.role])
