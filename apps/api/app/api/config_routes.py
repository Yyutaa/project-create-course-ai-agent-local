"""Local-only DeepSeek settings; never return credentials."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.run_routes import get_local_config
from app.v0.local_config import ConfigError, LocalConfigStore


router = APIRouter(prefix="/api/v0/llm-config", tags=["v0-local-config"])
ConfigDep = Annotated[LocalConfigStore, Depends(get_local_config)]
ModelId = Literal["deepseek-flash", "deepseek-v4-pro"]


class ConfigView(BaseModel):
    provider: Literal["deepseek"]
    model: ModelId
    configured: bool
    error: str | None


class ConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: ModelId
    api_key: str | None = Field(default=None, min_length=1, max_length=4096)


def _view(store: LocalConfigStore) -> ConfigView:
    return ConfigView(**vars(store.status()))


def _failure(error: ConfigError) -> HTTPException:
    status = 409 if str(error) in {"config_missing", "key_missing", "config_superseded"} else 503
    return HTTPException(status_code=status, detail={"code": str(error)})


@router.get("")
def read_config(store: ConfigDep) -> ConfigView:
    return _view(store)


@router.put("")
def save_config(payload: ConfigInput, store: ConfigDep) -> ConfigView:
    try:
        store.save(payload.model, payload.api_key)
    except ConfigError as error:
        raise _failure(error) from error
    return _view(store)


@router.delete("")
def clear_config(store: ConfigDep) -> ConfigView:
    try:
        store.clear()
    except ConfigError as error:
        raise _failure(error) from error
    return _view(store)
