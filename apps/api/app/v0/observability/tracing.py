"""Build a causal Span tree from existing, immutable execution identities."""

from typing import Literal

from pydantic import BaseModel, Field


SpanKind = Literal["run", "command", "node", "provider", "tool"]
SpanAttribute = str | int | float | bool | None


class TraceSpan(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: str | None
    kind: SpanKind
    name: str
    stage: str | None
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    attributes: dict[str, SpanAttribute] = Field(default_factory=dict)


def build_spans(
    trace_id: str, run_status: str, commands: list, nodes: list,
    provider_calls: list, tool_calls: list,
    *, run_started_at: str | None = None, run_finished_at: str | None = None,
) -> list[TraceSpan]:
    """Project stable span IDs; never copy prompts, content or tool arguments."""
    root = f"run:{trace_id}"
    command_ids = {item.id for item in commands}
    node_stage = {item.id: item.node for item in nodes}
    spans = [TraceSpan(
        trace_id=trace_id, span_id=root, parent_span_id=None,
        kind="run", name="course_run", stage=None, status=run_status,
        started_at=run_started_at, finished_at=run_finished_at,
    )]
    spans.extend(TraceSpan(
        trace_id=trace_id, span_id=f"command:{item.id}",
        parent_span_id=root, kind="command", name=item.kind,
        stage=None, status=item.status,
        started_at=item.created_at,
        finished_at=(
            item.updated_at if item.status in ("APPLIED", "FAILED", "REJECTED")
            else None
        ),
    ) for item in commands)
    spans.extend(TraceSpan(
        trace_id=trace_id, span_id=f"node:{item.id}",
        parent_span_id=(
            f"command:{item.command_id}" if item.command_id in command_ids else root
        ),
        kind="node", name=item.node, stage=item.node, status=item.status,
        started_at=item.created_at,
        finished_at=item.updated_at if item.status != "STARTED" else None,
        attributes={
            "attempt": item.attempt, "lease_epoch": item.lease_epoch,
            "failure_class": item.failure_class,
        },
    ) for item in nodes)
    for kind, items in (("provider", provider_calls), ("tool", tool_calls)):
        for item in items:
            parent = (
                f"node:{item.node_execution_id}"
                if item.node_execution_id in node_stage else
                f"command:{item.command_id}"
                if item.command_id in command_ids else root
            )
            attributes = (
                {
                    "role": item.role, "duration_ms": item.duration_ms,
                    "input_tokens": item.input_tokens,
                    "output_tokens": item.output_tokens,
                    "total_tokens": item.total_tokens,
                    "response_status": item.response_status,
                    "error_code": item.error_code,
                }
                if kind == "provider" else
                {"tool_id": item.tool_id, "error_code": item.error_code}
            )
            spans.append(TraceSpan(
                trace_id=trace_id, span_id=f"{kind}:{item.id}",
                parent_span_id=parent, kind=kind,
                name=item.role if kind == "provider" else item.tool_id,
                stage=node_stage.get(item.node_execution_id),
                status=item.status, attributes=attributes,
                started_at=(
                    item.started_at if kind == "provider" else item.created_at
                ),
                finished_at=(
                    item.finished_at if kind == "provider" else
                    item.updated_at if item.status != "STARTED" else None
                ),
            ))
    return spans
