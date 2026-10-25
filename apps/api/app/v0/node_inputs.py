"""Canonical NodeExecution input descriptors and hashes."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from app.v0.schemas import GraphState, V0Run
from app.v0.skill_rules import RULE_CATALOG_VERSION


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def _hash(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def provider_fingerprint(provider: Any) -> str:
    seen: set[int] = set()
    current = provider
    while hasattr(current, "provider") and id(current) not in seen:
        seen.add(id(current))
        current = current.provider
    model = getattr(current, "model", None)
    if model is None:
        config = getattr(current, "config", None)
        if config is not None and hasattr(config, "status"):
            try:
                model = config.status().model
            except Exception:
                model = None
    name = type(current).__name__
    return f"{name}:{model}" if model else name


def build_node_input_hash(
    *,
    node: str,
    run: V0Run,
    state: GraphState,
    mission_review: dict | None,
    source_summary: list[dict] | None,
    human_input: dict | None,
    provider: Any,
) -> str:
    references = [
        {
            "key": key,
            "kind": ref.kind,
            "artifact_id": ref.artifact_id,
            "version": ref.version,
            "content_hash": ref.content_hash,
        }
        for key, ref in sorted(state.artifact_refs.items())
    ]
    descriptor = {
        "node": node,
        "run_id": state.run_id,
        "versions": {
            "constraints": run.constraints_version,
            "source_evidence": run.source_evidence_version,
            "planning_loop": run.planning_loop_version,
            "context_contract": run.context_contract_version,
        },
        "course_input_hash": _hash(run.course_input.model_dump(mode="json")),
        "artifact_refs": references,
        "batch_cursor": state.batch_cursor,
        "quality_cursor": state.quality_cursor,
        "active_finding_id": state.active_finding_id,
        "approval_status": state.approval_status,
        "mission_review_hash": _hash(mission_review) if mission_review else None,
        "source_summary_hash": (
            _hash(source_summary) if source_summary is not None else None
        ),
        "human_input_hash": _hash(human_input) if human_input else None,
        "rule_catalog_version": RULE_CATALOG_VERSION,
        "provider_fingerprint": provider_fingerprint(provider),
    }
    return _hash(descriptor)
