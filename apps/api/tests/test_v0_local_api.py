from fastapi.testclient import TestClient
import pytest

from app.api.run_routes import get_local_config
from app.api.run_routes import get_runner
from app.main import app
from app.v0.local_config import LocalConfigStore
from app.v0.provider import (
    AgentInput, AgentRequest, AgentResponse, LocalConfiguredProvider, ProviderError,
    RealProvider,
)
from app.v0.runner import V0Runner
from app.v0.storage import FactStore
from app.v0.worker import Worker


class MemoryKeyring:
    def __init__(self):
        self.key = None

    def get_password(self, service, account):
        return self.key

    def set_password(self, service, account, value):
        self.key = value

    def delete_password(self, service, account):
        self.key = None


@pytest.fixture
def client(tmp_path):
    keyring = MemoryKeyring()
    store = LocalConfigStore(tmp_path / "facts.sqlite3", keyring_backend=keyring)
    app.dependency_overrides[get_local_config] = lambda: store
    with TestClient(
        app,
        base_url="http://127.0.0.1:8002",
        headers={"Origin": "http://127.0.0.1:5176"},
    ) as test_client:
        yield test_client, keyring
    app.dependency_overrides.clear()


def test_config_api_round_trip_never_returns_key(client):
    http, keyring = client
    initial = http.get("/api/v0/llm-config")
    assert initial.status_code == 200
    assert initial.json() == {
        "provider": "deepseek", "model": "deepseek-flash",
        "configured": False, "error": None,
    }

    saved = http.put(
        "/api/v0/llm-config",
        json={"model": "deepseek-flash", "api_key": "TEST_SECRET_901"},
    )
    assert saved.status_code == 200
    assert saved.json()["configured"] is True
    assert "TEST_SECRET_901" not in saved.text
    assert "TEST_SECRET_901" not in http.get("/api/v0/llm-config").text

    changed = http.put("/api/v0/llm-config", json={"model": "deepseek-v4-pro"})
    assert changed.status_code == 200
    assert changed.json()["model"] == "deepseek-v4-pro"
    assert keyring.key == "TEST_SECRET_901"

    cleared = http.delete("/api/v0/llm-config")
    assert cleared.status_code == 200
    assert cleared.json()["configured"] is False
    assert keyring.key is None


@pytest.mark.parametrize("origin,host", [
    ("https://attacker.example", "127.0.0.1:8002"),
    ("null", "127.0.0.1:8002"),
    (None, "127.0.0.1:8002"),
    ("http://127.0.0.1:5176", "attacker.example"),
])
def test_config_write_rejects_untrusted_source(client, origin, host):
    http, keyring = client
    headers = {"Host": host}
    if origin is None:
        headers["Origin"] = ""
    else:
        headers["Origin"] = origin
    response = http.put(
        "/api/v0/llm-config", json={"model": "deepseek-flash", "api_key": "KEY"},
        headers=headers,
    )
    assert response.status_code == 403
    assert keyring.key is None


def test_all_v0_writes_share_source_guard(client):
    http, _ = client
    response = http.post(
        "/api/v0/runs",
        json={"topic": "X", "audience": "Y", "goal": "Z", "language": "zh"},
        headers={"Origin": "https://attacker.example", "Idempotency-Key": "probe"},
    )
    assert response.status_code == 403


def test_config_write_requires_json_and_known_model(client):
    http, _ = client
    wrong_type = http.put(
        "/api/v0/llm-config", content="model=deepseek-flash",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert wrong_type.status_code == 415
    invalid = http.put(
        "/api/v0/llm-config", json={"model": "other", "api_key": "KEY"},
    )
    assert invalid.status_code == 422


def test_invalid_key_never_appears_in_validation_response(client):
    http, _ = client
    secret = "PRIVATE_903" * 500
    response = http.put(
        "/api/v0/llm-config",
        json={"model": "deepseek-flash", "api_key": secret},
    )
    assert response.status_code == 422
    assert secret not in response.text
    assert "PRIVATE_903" not in response.text


def test_new_run_requires_local_config_before_creating_facts(client):
    http, keyring = client
    store = app.dependency_overrides[get_local_config]()
    facts = FactStore(store.facts.path)
    runner = V0Runner(LocalConfiguredProvider(store), store=facts)
    app.dependency_overrides[get_runner] = lambda: runner
    course = {"topic": "变量", "audience": "初学者", "goal": "理解变量", "language": "zh"}

    rejected = http.post(
        "/api/v0/runs", json=course, headers={"Idempotency-Key": "start-1"},
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "llm_config_required"
    with facts.connect() as connection:
        for table in ("courses", "runs", "commands"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0

    http.put(
        "/api/v0/llm-config",
        json={"model": "deepseek-flash", "api_key": "TEST_SECRET_902"},
    )
    accepted = http.post(
        "/api/v0/runs", json=course, headers={"Idempotency-Key": "start-1"},
    )
    assert accepted.status_code == 202
    assert keyring.key == "TEST_SECRET_902"


def test_worker_default_provider_reads_current_config_per_call(
    tmp_path, monkeypatch,
):
    store = LocalConfigStore(tmp_path / "facts.sqlite3", keyring_backend=MemoryKeyring())
    monkeypatch.setattr("app.v0.worker.LocalConfigStore", lambda path: store)
    worker = Worker(store.facts.path)
    provider = worker.budgeted_provider.provider
    assert isinstance(provider, LocalConfiguredProvider)
    seen = []

    def fake_invoke(self, request):
        seen.append((self.base_url, self.model, self.api_key))
        return AgentResponse(role=request.role, payload={})

    monkeypatch.setattr(RealProvider, "invoke", fake_invoke)
    request = AgentRequest(
        role="mission", goal="定义任务", instructions=["短规则"],
        inputs=[AgentInput(kind="intake", content={"topic": "变量"})],
        output_schema={},
    )
    store.save("deepseek-flash", "key-one")
    provider.invoke(request)
    store.save("deepseek-v4-pro", "key-two")
    provider.invoke(request)
    assert seen == [
        ("https://api.deepseek.com", "deepseek-flash", "key-one"),
        ("https://api.deepseek.com", "deepseek-v4-pro", "key-two"),
    ]

    monkeypatch.setenv("COURSE_LLM_API_KEY", "hidden-old-key")
    store.clear()
    with pytest.raises(ProviderError, match="请配置 DeepSeek"):
        provider.invoke(request)
    assert len(seen) == 2
