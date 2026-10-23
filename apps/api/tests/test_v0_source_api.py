from fastapi.testclient import TestClient

from app.api.run_routes import get_runner
from app.main import app
from app.v0.provider import FakeProvider
from app.v0.runner import V0Runner
from app.v0.storage import FactStore


def test_source_api_exposes_safe_state_and_rejects_private_proposed_url(tmp_path):
    runner = V0Runner(FakeProvider(), FactStore(tmp_path / "facts.sqlite3"))
    app.dependency_overrides[get_runner] = lambda: runner
    try:
        with TestClient(
            app, base_url="http://127.0.0.1:8002",
            headers={"Origin": "http://127.0.0.1:5176"},
        ) as client:
            created = client.post(
                "/api/v0/runs",
                json={
                    "topic": "Vue", "audience": "初学者",
                    "goal": "理解 state", "language": "zh",
                },
                headers={"Idempotency-Key": "source-api"},
            )
            run_id = created.json()["id"]
            sources = client.get(f"/api/v0/runs/{run_id}/sources")
            assert sources.status_code == 200
            assert sources.json() == {"candidates": [], "documents": [], "claims": []}
            with runner.store.connect() as connection:
                connection.execute(
                    "INSERT INTO source_candidates "
                    "(id, run_id, url, title, status, metadata_hash, created_at) "
                    "VALUES ('candidate-1', ?, 'https://vuejs.org/guide', "
                    "'Vue Guide', 'candidate', 'hash-1', '2026-01-01')",
                    (run_id,),
                )
                connection.execute(
                    "INSERT INTO source_documents "
                    "(id, run_id, candidate_id, version, url, title, content, "
                    "content_hash, identity_json, status, created_at) "
                    "VALUES ('document-1', ?, 'candidate-1', 1, "
                    "'https://vuejs.org/guide', 'Vue Guide', 'secret page text', "
                    "'page-hash', '{\"official_host\":\"vuejs.org\"}', 'eligible', "
                    "'2026-01-01')", (run_id,),
                )
            visible = client.get(f"/api/v0/runs/{run_id}/sources")
            assert visible.status_code == 200
            assert visible.json()["documents"][0]["content_hash"] == "page-hash"
            assert "secret page text" not in visible.text
            assert "identity_json" not in visible.text
            rejected = client.post(
                f"/api/v0/runs/{run_id}/source-review",
                json={
                    "action": "propose_url", "url": "http://127.0.0.1/admin",
                    "reason": "manual", "expected_checkpoint_id": "checkpoint-1",
                },
                headers={"Idempotency-Key": "bad-source"},
            )
            assert rejected.status_code == 422
    finally:
        app.dependency_overrides.clear()
