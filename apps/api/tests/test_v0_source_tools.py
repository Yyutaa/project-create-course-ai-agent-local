import pytest
from pydantic import ValidationError

from app.v0.source_tools import (
    FetchInput,
    SearchInput,
    ToolPermissionError,
    canonical_public_url,
    resolve_tool,
)


def test_tool_registry_enforces_workflow_caller_and_known_wire_names():
    assert resolve_tool("course_source_search", "workflow.blueprint").id == (
        "course.source.search"
    )
    assert resolve_tool("course_source_fetch", "workflow.generation").id == (
        "course.source.fetch"
    )
    with pytest.raises(ToolPermissionError):
        resolve_tool("course_source_search", "workflow.quality")
    with pytest.raises(ToolPermissionError):
        resolve_tool("course_build", "workflow.generation")


@pytest.mark.parametrize("payload", [
    {"query": " "}, {"query": "x" * 129},
    {"query": "Vue", "url": "https://evil.example"},
])
def test_search_input_rejects_invalid_or_extra_values(payload):
    with pytest.raises(ValidationError):
        SearchInput.model_validate(payload)


def test_fetch_input_accepts_only_candidate_identity():
    assert FetchInput(candidate_id="candidate-1").candidate_id == "candidate-1"
    with pytest.raises(ValidationError):
        FetchInput.model_validate({"url": "https://vuejs.org"})


@pytest.mark.parametrize("url", [
    "http://vuejs.org/guide", "https://user:pass@vuejs.org/guide",
    "https://127.0.0.1/", "https://[::1]/", "https://localhost/",
    "https://docs.internal/", "https://vuejs.org:8443/guide",
    "https://vuejs.org\\@evil.example/", "file:///etc/passwd",
])
def test_public_url_rejects_non_public_or_ambiguous_targets(url):
    with pytest.raises(ValueError):
        canonical_public_url(url)


def test_public_url_normalizes_host_and_fragment():
    assert canonical_public_url("https://VUEJS.ORG/guide#intro") == (
        "https://vuejs.org/guide"
    )
