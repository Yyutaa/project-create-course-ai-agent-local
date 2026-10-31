"""Per-attempt model metrics, with unknown usage left unknown."""

import re

from pydantic import BaseModel, computed_field, field_validator

from app.v0.sensitive import safe_recorded_error


class InvocationMetrics(BaseModel):
    status: str
    duration_ms: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    provider: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    response_status: int | None = None
    error_code: str | None = None
    failure_class: str | None = None
    error_summary: str | None = None

    @field_validator("provider")
    @classmethod
    def safe_provider(cls, value: str | None) -> str | None:
        return value if value == "deepseek" else None

    @field_validator("model")
    @classmethod
    def safe_model(cls, value: str | None) -> str | None:
        return value if value in ("deepseek-flash", "deepseek-v4-pro") else None

    @field_validator("error_code")
    @classmethod
    def safe_code(cls, value: str | None) -> str | None:
        return value if value and re.fullmatch(
            r"http_[1-5][0-9]{2}|timeout|connection|invalid_json|"
            r"provider_error|unexpected_error", value,
        ) else None

    @field_validator("failure_class")
    @classmethod
    def safe_class(cls, value: str | None) -> str | None:
        return value if value in (
            "transient", "deterministic", "business", "unknown",
        ) else None

    @field_validator("error_summary")
    @classmethod
    def safe_summary(cls, value: str | None) -> str | None:
        return safe_recorded_error(value) if value else None

    @computed_field
    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens
