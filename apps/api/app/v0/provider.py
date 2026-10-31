from __future__ import annotations

import json
import os
from typing import Literal, Protocol

from langchain_core.exceptions import OutputParserException
from langchain_deepseek import ChatDeepSeek
from langsmith import tracing_context
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.v0.local_config import ConfigError, LocalConfigStore
from app.v0.prompt_render import render_agent_messages
from app.v0.token_preflight import MAX_OUTPUT_TOKENS, preflight_request
from app.v0.schemas import AgentRole, ArtifactRef
from app.v0.source_tools import FetchInput, SearchInput


InputKind = Literal["intake", "mission", "blueprint", "batch_plan", "lesson", "quality"]


class ProviderError(RuntimeError):
    """A model request failed without exposing credentials or raw prompts."""

    def __init__(
        self, message: str, *, provider: str | None = None,
        model: str | None = None, response_status: int | None = None,
        error_code: str | None = None, input_tokens: int | None = None,
        output_tokens: int | None = None,
    ):
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.response_status = response_status
        self.error_code = error_code
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class TransientProviderError(ProviderError):
    """Only a confirmed timeout or HTTP 429 may receive one bounded retry."""

    def __init__(
        self, reason: str, *, provider: str | None = None,
        model: str | None = None,
    ):
        if reason not in ("timeout", "http_429"):
            raise ValueError("未知临时故障类型")
        self.reason = reason
        super().__init__(
            "模型调用超时" if reason == "timeout" else "模型接口限流",
            provider=provider, model=model,
            response_status=429 if reason == "http_429" else None,
            error_code=reason,
        )


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
    context_contract_version: int = Field(default=0, ge=0, le=1)


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AgentRole
    payload: dict
    input_tokens: int | None = None
    output_tokens: int | None = None
    provider: str | None = None
    model: str | None = None
    response_status: int | None = None


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    arguments: dict


class ToolTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None
    provider: str | None = None
    model: str | None = None
    response_status: int | None = None


SOURCE_FUNCTIONS = [
    {"type": "function", "function": {
        "name": "course_source_search",
        "description": "Find candidate public pages. Results are not verified evidence.",
        "parameters": SearchInput.model_json_schema(),
    }},
    {"type": "function", "function": {
        "name": "course_source_fetch",
        "description": "Fetch a candidate by its ID after runtime approval.",
        "parameters": FetchInput.model_json_schema(),
    }},
]


class Provider(Protocol):
    def invoke(self, request: AgentRequest) -> AgentResponse: ...

    def next_tool_turn(
        self, request: AgentRequest, messages: list[dict]
    ) -> ToolTurn: ...


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

    def preflight(
        self, request: AgentRequest, messages: list[dict] | None = None,
    ) -> None:
        preflight_request(
            request, self.model, messages=messages,
            tools=SOURCE_FUNCTIONS if messages is not None else None,
        )

    def invoke(self, request: AgentRequest) -> AgentResponse:
        if not all((self.base_url, self.model, self.api_key)):
            raise ProviderError("LLM 配置不完整：请设置 base_url、model 和 api_key")

        messages = render_agent_messages(request)
        if request.context_contract_version == 1:
            self.preflight(request)

        try:
            model = ChatDeepSeek(
                model=self.model,
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=240,
                max_retries=0,
                max_tokens=MAX_OUTPUT_TOKENS[request.role],
            )
            structured = model.with_structured_output(
                request.output_schema, method="json_mode", include_raw=True
            )
            with tracing_context(enabled=False):
                response = structured.invoke(messages)
            usage = response["raw"].usage_metadata or {}
            result = response["parsed"]
            if not isinstance(result, dict) and response["parsing_error"] is None:
                raise ProviderError(
                    f"{request.role} 模型必须返回 JSON 对象",
                    provider="deepseek", model=self.model, response_status=200,
                    error_code="invalid_json",
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                )
            if response["parsing_error"] is not None:
                raise ProviderError(
                    f"{request.role} 模型输出不是有效 JSON 对象",
                    provider="deepseek", model=self.model, response_status=200,
                    error_code="invalid_json",
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                )
            return AgentResponse(
                role=request.role, payload=result,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                provider="deepseek", model=self.model, response_status=200,
            )
        except APIStatusError as error:
            if error.status_code == 429:
                raise TransientProviderError(
                    "http_429", provider="deepseek", model=self.model,
                ) from None
            raise ProviderError(
                f"{request.role} 模型接口返回 HTTP {error.status_code}",
                provider="deepseek", model=self.model,
                response_status=error.status_code,
                error_code=f"http_{error.status_code}",
            ) from None
        except APITimeoutError:
            raise TransientProviderError(
                "timeout", provider="deepseek", model=self.model,
            ) from None
        except APIConnectionError:
            raise ProviderError(
                f"{request.role} 模型接口不可用或超时",
                provider="deepseek", model=self.model, error_code="connection",
            ) from None
        except ProviderError:
            raise
        except (OutputParserException, KeyError, TypeError, ValueError):
            raise ProviderError(f"{request.role} 模型输出不是有效 JSON 对象") from None
        except Exception:
            raise ProviderError(f"{request.role} 模型调用失败") from None

    def next_tool_turn(
        self, request: AgentRequest, messages: list[dict]
    ) -> ToolTurn:
        if not all((self.base_url, self.model, self.api_key)):
            raise ProviderError("LLM 配置不完整：请设置 base_url、model 和 api_key")
        if request.context_contract_version == 1:
            self.preflight(request, messages)
        try:
            client = OpenAI(
                base_url=self.base_url, api_key=self.api_key,
                timeout=240, max_retries=0,
            )
            with tracing_context(enabled=False):
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=SOURCE_FUNCTIONS,
                    tool_choice="auto",
                    max_tokens=MAX_OUTPUT_TOKENS[request.role],
                )
            message = response.choices[0].message
            calls = []
            for item in message.tool_calls or []:
                arguments = json.loads(item.function.arguments)
                if not isinstance(arguments, dict):
                    raise ProviderError("模型工具参数不是 JSON 对象")
                calls.append(ToolCall(
                    id=item.id, name=item.function.name, arguments=arguments,
                ))
            return ToolTurn(
                content=message.content,
                tool_calls=calls,
                input_tokens=(response.usage.prompt_tokens if response.usage else None),
                output_tokens=(
                    response.usage.completion_tokens if response.usage else None
                ),
                provider="deepseek", model=self.model, response_status=200,
            )
        except APIStatusError as error:
            if error.status_code == 429:
                raise TransientProviderError(
                    "http_429", provider="deepseek", model=self.model,
                ) from None
            raise ProviderError(
                f"{request.role} 模型接口返回 HTTP {error.status_code}",
                provider="deepseek", model=self.model,
                response_status=error.status_code,
                error_code=f"http_{error.status_code}",
            ) from None
        except APITimeoutError:
            raise TransientProviderError(
                "timeout", provider="deepseek", model=self.model,
            ) from None
        except APIConnectionError:
            raise ProviderError(
                f"{request.role} 模型接口不可用或超时",
                provider="deepseek", model=self.model, error_code="connection",
            ) from None
        except ProviderError:
            raise
        except (KeyError, TypeError, ValueError, IndexError):
            raise ProviderError("模型工具响应格式无效") from None
        except Exception:
            raise ProviderError(f"{request.role} 模型调用失败") from None


class LocalConfiguredProvider:
    """Resolve the local setting for each model call, never at Worker startup."""

    def __init__(self, config: LocalConfigStore):
        self.config = config

    def preflight(
        self, request: AgentRequest, messages: list[dict] | None = None,
    ) -> None:
        try:
            model, _ = self.config.require_credentials()
        except ConfigError:
            raise ProviderError("请配置 DeepSeek 后再运行") from None
        RealProvider("https://api.deepseek.com", model, "preflight-only").preflight(
            request, messages,
        )

    def invoke(self, request: AgentRequest) -> AgentResponse:
        try:
            model, key = self.config.require_credentials()
        except ConfigError:
            raise ProviderError("请配置 DeepSeek 后再运行") from None
        return RealProvider("https://api.deepseek.com", model, key).invoke(request)

    def next_tool_turn(
        self, request: AgentRequest, messages: list[dict]
    ) -> ToolTurn:
        try:
            model, key = self.config.require_credentials()
        except ConfigError:
            raise ProviderError("请配置 DeepSeek 后再运行") from None
        return RealProvider(
            "https://api.deepseek.com", model, key
        ).next_tool_turn(request, messages)


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
                "key_facts": ["变量保存可更新的值"],
                "next_goals": ["继续学习条件分支"],
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

    def next_tool_turn(
        self, request: AgentRequest, messages: list[dict]
    ) -> ToolTurn:
        return ToolTurn(content=json.dumps(self.invoke(request).payload, ensure_ascii=False))
