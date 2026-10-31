"""Provider diagnostics and trace structure from durable Run facts."""

import pytest
from fastapi.testclient import TestClient

from app.v0.budget import BudgetedProvider, BudgetStore
from app.v0.delivery import DeliveryStore
from app.v0.execution import ExecutionStore
from app.v0.provider import (
    AgentInput, AgentRequest, AgentResponse, ProviderError, TransientProviderError,
)
from app.v0.schemas import CourseInput, GraphState
from app.v0.storage import FactStore


def _run_with_node(tmp_path):
    facts = FactStore(tmp_path / "facts.sqlite3")
    facts.migrate()
    run, _ = facts.create_run(
        CourseInput(
            topic="PRIVATE_TOPIC_731", audience="初学者",
            goal="解释变量", language="zh",
        ),
        "start", enqueue_start=True,
    )
    execution = ExecutionStore(facts.path)
    command = execution.claim("worker-a")
    epoch = execution.acquire(run.id, "worker-a")
    node_id = execution.start_node(
        run.id, "mission", GraphState(run_id=run.id), "worker-a", epoch,
        command_id=command.id,
    )
    request = AgentRequest(
        role="mission", run_id=run.id, goal="定义课程任务",
        instructions=["遵守来源边界"],
        inputs=[AgentInput(kind="intake", content={"topic": "PRIVATE_TOPIC_731"})],
        output_schema={"type": "object"},
    )
    return facts, run.id, command.id, node_id, epoch, request


def test_successful_provider_call_exposes_metrics_and_causal_spans(tmp_path):
    facts, run_id, command_id, node_id, epoch, request = _run_with_node(tmp_path)

    class Provider:
        def invoke(self, request):
            return AgentResponse(
                role=request.role, payload={"ok": True},
                provider="deepseek", model="deepseek-flash",
                response_status=200, input_tokens=17, output_tokens=9,
            )

    provider = BudgetedProvider(Provider(), BudgetStore(facts.path))
    provider.bind("worker-a", epoch, command_id)
    provider.node_execution_id = node_id
    provider.invoke(request)

    evidence = DeliveryStore(facts.path).read(run_id)
    call = evidence.provider_calls[0]
    assert (call.provider, call.model, call.total_tokens) == (
        "deepseek", "deepseek-flash", 26,
    )
    assert (call.response_status, call.error_code, call.failure_class) == (200, None, None)
    spans = {span.span_id: span for span in evidence.spans}
    assert spans[f"command:{command_id}"].parent_span_id == f"run:{run_id}"
    assert spans[f"node:{node_id}"].parent_span_id == f"command:{command_id}"
    assert spans[f"provider:{call.id}"].parent_span_id == f"node:{node_id}"
    assert spans[f"provider:{call.id}"].stage == "mission"
    assert spans[f"provider:{call.id}"].attributes["total_tokens"] == 26
    assert spans[f"provider:{call.id}"].started_at is not None
    assert spans[f"provider:{call.id}"].finished_at is not None
    assert spans[f"node:{node_id}"].finished_at is None
    assert "PRIVATE_TOPIC_731" not in evidence.model_dump_json()


def test_failed_provider_call_keeps_known_usage_and_safe_diagnostics(tmp_path):
    facts, run_id, command_id, node_id, epoch, request = _run_with_node(tmp_path)

    class Provider:
        def invoke(self, _request):
            raise ProviderError(
                "private-key-SECRET raw response", provider="deepseek",
                model="deepseek-v4-pro", response_status=503,
                error_code="http_503", input_tokens=11, output_tokens=3,
            )

    provider = BudgetedProvider(Provider(), BudgetStore(facts.path))
    provider.bind("worker-a", epoch, command_id)
    provider.node_execution_id = node_id
    with pytest.raises(ProviderError):
        provider.invoke(request)

    evidence = DeliveryStore(facts.path).read(run_id)
    call = evidence.provider_calls[0]
    assert (call.status, call.response_status, call.error_code) == (
        "FAILED", 503, "http_503",
    )
    assert (call.total_tokens, call.failure_class) == (14, "unknown")
    assert "SECRET" not in evidence.model_dump_json()
    assert "private-key" not in evidence.model_dump_json()


def test_unknown_failure_usage_stays_unknown_and_node_error_is_redacted(tmp_path):
    facts, run_id, command_id, node_id, epoch, request = _run_with_node(tmp_path)

    class Provider:
        def invoke(self, _request):
            raise RuntimeError("private-key-SECRET")

    provider = BudgetedProvider(Provider(), BudgetStore(facts.path))
    provider.bind("worker-a", epoch, command_id)
    provider.node_execution_id = node_id
    with pytest.raises(RuntimeError):
        provider.invoke(request)
    with facts.connect() as connection:
        connection.execute(
            "UPDATE node_executions SET status='FAILED', error=?, "
            "failure_class='unknown' WHERE id=?",
            ("private-key-SECRET", node_id),
        )

    evidence = DeliveryStore(facts.path).read(run_id)
    call = evidence.provider_calls[0]
    assert (call.input_tokens, call.output_tokens, call.total_tokens) == (
        None, None, None,
    )
    assert call.failure_class == "unknown"
    assert evidence.nodes[0].failure_class == "unknown"
    assert "SECRET" not in evidence.model_dump_json()


@pytest.mark.parametrize(
    ("reason", "status", "response_status"),
    [("timeout", "FAILED_TIMEOUT", None), ("http_429", "FAILED_429", 429)],
)
def test_transient_attempt_retains_safe_code_without_guessing_usage(
    tmp_path, reason, status, response_status,
):
    facts, run_id, command_id, node_id, epoch, request = _run_with_node(tmp_path)

    class Provider:
        def invoke(self, _request):
            raise TransientProviderError(
                reason, provider="deepseek", model="deepseek-flash",
            )

    provider = BudgetedProvider(Provider(), BudgetStore(facts.path))
    provider.bind("worker-a", epoch, command_id)
    provider.node_execution_id = node_id
    with pytest.raises(TransientProviderError):
        provider.invoke(request)
    call = DeliveryStore(facts.path).read(run_id).provider_calls[0]
    assert (call.status, call.error_code, call.failure_class) == (
        status, reason, "transient",
    )
    assert call.response_status == response_status
    assert call.total_tokens is None


def test_tool_span_uses_node_parent_without_copying_tool_result(tmp_path):
    facts, run_id, command_id, node_id, epoch, _request = _run_with_node(tmp_path)
    with facts.connect() as connection:
        connection.execute(
            "INSERT INTO tool_invocations (id,run_id,node_execution_id,command_id,"
            "tool_id,args_hash,status,result_json,error_code,lease_epoch,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "tool-1", run_id, node_id, command_id, "course.source.search",
                "args-hash", "SUCCEEDED", '{"secret":"PRIVATE_TOOL_RESULT"}',
                None, epoch, "now", "now",
            ),
        )

    evidence = DeliveryStore(facts.path).read(run_id)
    span = next(item for item in evidence.spans if item.span_id == "tool:tool-1")
    assert (span.parent_span_id, span.stage) == (f"node:{node_id}", "mission")
    assert "PRIVATE_TOOL_RESULT" not in evidence.model_dump_json()


def test_evidence_api_serializes_metrics_and_spans_without_private_input(tmp_path):
    from app.api.run_routes import get_runner
    from app.main import app
    from app.v0.provider import FakeProvider
    from app.v0.runner import V0Runner

    facts, run_id, command_id, node_id, epoch, request = _run_with_node(tmp_path)

    class Provider:
        def invoke(self, request):
            return AgentResponse(
                role=request.role, payload={}, provider="deepseek",
                model="deepseek-flash", response_status=200,
                input_tokens=12, output_tokens=8,
            )

    provider = BudgetedProvider(Provider(), BudgetStore(facts.path))
    provider.bind("worker-a", epoch, command_id)
    provider.node_execution_id = node_id
    provider.invoke(request)
    app.dependency_overrides[get_runner] = lambda: V0Runner(
        FakeProvider(), store=facts,
    )
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/v0/runs/{run_id}/evidence")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["provider_calls"][0]["total_tokens"] == 20
    assert data["spans"][-1]["parent_span_id"] == f"node:{node_id}"
    assert "PRIVATE_TOPIC_731" not in response.text
