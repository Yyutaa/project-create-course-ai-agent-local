"""Static source-tool contract. Model requests never confer execution permission."""

from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ToolPermissionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ToolManifest:
    id: str
    callers: frozenset[str]
    idempotent: bool


_SOURCE_CALLERS = frozenset({"workflow.blueprint", "workflow.generation"})
TOOL_MANIFESTS = {
    "course.source.search": ToolManifest(
        "course.source.search", _SOURCE_CALLERS, True,
    ),
    "course.source.fetch": ToolManifest(
        "course.source.fetch", _SOURCE_CALLERS, True,
    ),
}
WIRE_TOOL_IDS = {
    "course_source_search": "course.source.search",
    "course_source_fetch": "course.source.fetch",
}


def resolve_tool(wire_name: str, caller: str) -> ToolManifest:
    tool_id = WIRE_TOOL_IDS.get(wire_name)
    manifest = TOOL_MANIFESTS.get(tool_id or "")
    if manifest is None or caller not in manifest.callers:
        raise ToolPermissionError("工具调用不在当前节点白名单")
    return manifest


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=128)

    @field_validator("query")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("检索词不能为空")
        return value


class FetchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=80)


_PRIVATE_SUFFIXES = (
    ".local", ".localhost", ".internal", ".test", ".invalid",
    ".example", ".onion", ".arpa",
)


def canonical_public_url(value: str) -> str:
    """Normalize a public HTTPS URL before it may become a source candidate."""
    if not value or len(value) > 2048 or "\\" in value:
        raise ValueError("来源 URL 不安全")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("来源 URL 不安全")
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").encode("idna").decode("ascii").lower()
        port = parts.port
    except (ValueError, UnicodeError) as error:
        raise ValueError("来源 URL 不安全") from error
    if parts.scheme.lower() != "https" or not host or parts.username or parts.password:
        raise ValueError("来源 URL 必须是公开 HTTPS 地址")
    if port not in (None, 443) or host.endswith(".") or "." not in host:
        raise ValueError("来源 URL 主机不受允许")
    if host.endswith(_PRIVATE_SUFFIXES) or "%" in host or "_" in host:
        raise ValueError("来源 URL 主机不受允许")
    try:
        ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("来源 URL 不得使用 IP 字面量")
    path = parts.path or "/"
    return urlunsplit(("https", host, path, parts.query, ""))


def is_direct_document_host(url: str) -> bool:
    """Shared hosting URLs are not an official product documentation identity."""
    host = urlsplit(url).hostname
    return host not in {
        "github.com", "raw.githubusercontent.com", "gist.github.com",
        "gist.githubusercontent.com",
    }
