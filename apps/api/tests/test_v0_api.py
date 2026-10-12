import pytest
from fastapi.testclient import TestClient

from app.api.run_routes import get_runner
from app.main import app
from app.v0.provider import FakeProvider
from app.v0.runner import V0Runner
from app.v0.schemas import ArtifactRef, BlueprintDraft, BlueprintLesson, LessonDraft
from app.v0.storage import FactStore
from app.v0.worker import Worker


COURSE = {
    "topic": "Python 变量",
    "audience": "零基础学习者",
    "goal": "能解释并修改变量",
    "language": "zh",
}


@pytest.fixture
def client(tmp_path):
    runner = V0Runner(FakeProvider(), store=FactStore(tmp_path / "facts.sqlite3"))
    app.dependency_overrides[get_runner] = lambda: runner
    with TestClient(
        app, base_url="http://127.0.0.1:8002",
        headers={"Origin": "http://127.0.0.1:5176"},
    ) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def start(client, key="start-1", course=None, *, process=True, legacy=True):
    response = client.post(
        "/api/v0/runs", json=course or COURSE, headers={"Idempotency-Key": key}
    )
    if response.status_code == 202 and legacy:
        runner = app.dependency_overrides[get_runner]()
        run = runner.get(response.json()["id"])
        run.constraints_version = 0
        with runner.store.connect() as connection:
            connection.execute(
                "UPDATE runs SET mission_review_required=0, constraints_version=0 "
                "WHERE id=?",
                (response.json()["id"],),
            )
            connection.execute(
                "UPDATE snapshots SET projection_json=? WHERE run_id=?",
                (run.model_dump_json(), run.id),
            )
    if process and response.status_code == 202:
        runner = app.dependency_overrides[get_runner]()
        Worker(runner.store.path, provider=FakeProvider()).run_once()
    return response


def release(client, run_id, action, reason, key="release-1"):
    return client.post(
        f"/api/v0/runs/{run_id}/release",
        json={"action": action, "reason": reason},
        headers={"Idempotency-Key": key},
    )


def test_api_starts_and_reads_run_without_auto_release(client):
    created = start(client, process=False)

    assert created.status_code == 202
    run_id = created.json()["id"]
    assert client.get(f"/api/v0/runs/{run_id}").json()["status"] == "running"
    assert client.get(f"/api/v0/runs/{run_id}/execution").json()["commands"][0]["status"] == "ACCEPTED"
    runner = app.dependency_overrides[get_runner]()
    Worker(runner.store.path, provider=FakeProvider()).run_once()
    current = client.get(f"/api/v0/runs/{run_id}")
    assert current.status_code == 200
    assert current.json()["status"] == "waiting_for_human"
    assert current.json()["stages"][-1]["status"] == "waiting_for_human"
    assert current.json()["release_decision"] is None
    assert "artifact_refs" not in current.json()
    assert "context_pack" not in current.json()


def test_mission_review_api_only_accepts_command_and_reads_pending_version(client):
    run_id = start(client, legacy=False).json()["id"]
    execution = client.get(f"/api/v0/runs/{run_id}/execution").json()
    pending = execution["mission_review"]
    assert pending["status"] == "pending"
    assert pending["mission_ref"]["version"] == 1
    payload = {
        "action": "approve", "mission_ref": pending["mission_ref"],
        "expected_checkpoint_id": pending["checkpoint_id"],
    }
    response = client.post(
        f"/api/v0/runs/{run_id}/mission-review", json=payload,
        headers={"Idempotency-Key": "approve-v1"},
    )
    assert response.status_code == 202
    assert response.json()["kind"] == "MISSION_REVIEW"
    assert client.get(f"/api/v0/runs/{run_id}").json()["blueprint"] is None
    assert client.post(
        f"/api/v0/runs/{run_id}/mission-review", json=payload,
    ).status_code == 422
    replay = client.post(
        f"/api/v0/runs/{run_id}/mission-review", json=payload,
        headers={"Idempotency-Key": "approve-v1"},
    )
    assert replay.json()["id"] == response.json()["id"]
    assert client.post(
        f"/api/v0/runs/{run_id}/mission-review",
        json={**payload, "action": "revise", "feedback": "改目标"},
        headers={"Idempotency-Key": "approve-v1"},
    ).status_code == 409
    assert client.post(
        f"/api/v0/runs/{run_id}/mission-review",
        json={**payload, "action": "revise", "feedback": ""},
        headers={"Idempotency-Key": "bad-revision"},
    ).status_code == 422


def test_delivery_evidence_api_has_trace_and_redacted_summary(client):
    run_id = start(client).json()["id"]
    response = client.get(f"/api/v0/runs/{run_id}/evidence")
    assert response.status_code == 200
    evidence = response.json()
    assert evidence["trace_id"] == run_id
    assert evidence["commands"][0]["kind"] == "START"
    assert evidence["nodes"]
    assert evidence["artifacts"]
    assert "Python 变量" not in response.text


def test_run_and_snapshot_reads_hide_historical_failure_secret(client):
    run_id = start(client, process=False).json()["id"]
    facts = app.dependency_overrides[get_runner]().store
    failed = facts.get_run(run_id)
    failed.status = "failed"
    failed.stages[1].status = "failed"
    failed.stages[1].failure_reason = "api_key=TOPSECRET_731"
    facts.record(failed, "stage.failed", "mission")
    for path in (f"/api/v0/runs/{run_id}", f"/api/v0/runs/{run_id}/snapshot"):
        response = client.get(path)
        assert response.status_code == 200
        assert "TOPSECRET_731" not in response.text


def test_run_responses_hide_intake_raw_fields(client):
    payload = {**COURSE, "topic": "PRIVATE_TOPIC_731"}
    created = start(client, course=payload, process=False)
    run_id = created.json()["id"]
    assert "PRIVATE_TOPIC_731" not in created.text
    assert "PRIVATE_TOPIC_731" not in client.get(f"/api/v0/runs/{run_id}").text
    assert "PRIVATE_TOPIC_731" not in client.get(f"/api/v0/runs/{run_id}/snapshot").text


def test_create_response_preserves_constraints_but_hides_intake(client):
    payload = {
        **COURSE,
        "topic": "PRIVATE_TOPIC_731",
        "expected_chapters": 8,
        "min_effective_chars": 9000,
        "token_limit": 12345,
    }
    response = start(client, course=payload, process=False, legacy=False)

    assert response.status_code == 202
    assert "PRIVATE_TOPIC_731" not in response.text
    assert response.json()["course_input"] == {
        "topic": "已隐藏",
        "audience": "已隐藏",
        "goal": "已隐藏",
        "language": "zh",
        "expected_chapters": 8,
        "min_effective_chars": 9000,
        "token_limit": 12345,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [("expected_chapters", 0), ("min_effective_chars", 0), ("token_limit", 0)],
)
def test_invalid_constraint_response_omits_raw_input(client, field, value):
    response = start(
        client,
        course={**COURSE, field: value},
        process=False,
        legacy=False,
    )

    assert response.status_code == 422
    assert '"input"' not in response.text


def test_public_run_exposes_only_stable_constraint_stop_reason(client):
    response = start(client, process=False, legacy=False)
    run_id = response.json()["id"]
    facts = app.dependency_overrides[get_runner]().store
    run = facts.get_run(run_id)
    run.status = "stopped"
    run.stages[2].status = "stopped"
    run.stages[2].failure_reason = "token_limit_reached"
    facts.record(run, "budget.token_exhausted", "blueprint")

    public = client.get(f"/api/v0/runs/{run_id}")
    assert public.json()["stages"][2]["failure_reason"] == "token_limit_reached"


def test_api_control_posts_only_accept_and_read_model_is_read_only(client):
    run_id = start(client, process=False).json()["id"]
    accepted = client.post(
        f"/api/v0/runs/{run_id}/stop",
        headers={"Idempotency-Key": "stop-1"},
    )
    replay = client.post(
        f"/api/v0/runs/{run_id}/stop",
        headers={"Idempotency-Key": "stop-1"},
    )
    assert accepted.status_code == replay.status_code == 202
    assert accepted.json()["id"] == replay.json()["id"]
    assert accepted.json()["status"] == "ACCEPTED"
    assert client.get(f"/api/v0/runs/{run_id}").json()["status"] == "running"
    model = client.get(f"/api/v0/runs/{run_id}/execution").json()
    assert model["stop_requested"] is True
    assert [item["kind"] for item in model["commands"]] == ["START", "STOP"]


def test_api_rejects_unknown_run_and_invalid_decision(client):
    assert client.get("/api/v0/runs/missing").status_code == 404
    created = start(client)
    run_id = created.json()["id"]
    invalid = client.post(
        f"/api/v0/runs/{run_id}/release",
        json={"action": "publish", "reason": "禁止直接发布"},
    )
    assert invalid.status_code == 422


def test_api_human_stop_is_final(client):
    run_id = start(client).json()["id"]

    stopped = release(client, run_id, "stop", "人工暂停审核")
    repeated = release(client, run_id, "prepare", "再次提交", key="release-2")

    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"
    assert stopped.json()["stages"][-1]["status"] == "stopped"
    assert repeated.status_code == 409


def test_api_human_prepare_does_not_publish(client):
    run_id = start(client).json()["id"]
    prepared = release(client, run_id, "prepare", "人工审阅完成")

    assert prepared.status_code == 200
    assert prepared.json()["status"] == "ready_for_release"
    assert "published" not in prepared.json()["status"]


def test_start_and_release_require_keys_and_are_idempotent(client):
    assert client.post("/api/v0/runs", json=COURSE).status_code == 422
    first = start(client, "same")
    run_id = first.json()["id"]
    revision = client.get(f"/api/v0/runs/{run_id}/snapshot").json()["revision"]
    again = start(client, "same")
    conflict = start(client, "same", {**COURSE, "topic": "另一个主题"})
    assert first.status_code == again.status_code == 202
    assert first.json()["id"] == again.json()["id"]
    assert conflict.status_code == 409
    assert client.get(f"/api/v0/runs/{run_id}/snapshot").json()["revision"] == revision

    assert (
        client.post(
            f"/api/v0/runs/{run_id}/release",
            json={"action": "stop", "reason": "人工停止"},
        ).status_code
        == 422
    )
    stopped = release(client, run_id, "stop", "人工停止", key="decision")
    stopped_revision = stopped.json()["revision"]
    replay = release(client, run_id, "stop", "人工停止", key="decision")
    assert stopped.json()["status"] == replay.json()["status"] == "stopped"
    assert replay.json()["revision"] == stopped_revision
    assert release(client, run_id, "prepare", "变更", key="decision").status_code == 409


def test_course_list_tracks_new_run_and_its_current_stage(client):
    created = start(client, key="course-progress", process=False, legacy=False).json()
    course_id, run_id = created["course_id"], created["id"]

    course = client.get("/api/v0/courses").json()["items"][0]
    assert course["id"] == course_id
    assert course["title"] == COURSE["topic"]
    assert course["run_id"] == run_id
    assert course["current_stage"] == "intake"
    assert course["stage_status"] == "pending"

    runner = app.dependency_overrides[get_runner]()
    Worker(runner.store.path, provider=FakeProvider()).run_once()
    advanced = client.get("/api/v0/courses").json()["items"][0]
    assert advanced["run_id"] == run_id
    assert advanced["current_stage"] == "mission"
    assert advanced["stage_status"] == "waiting_for_human"


def test_run_content_keeps_blueprint_order_and_hides_unaccepted_candidate(client):
    created = start(client, key="content-run", process=False, legacy=False).json()
    run_id = created["id"]
    runner = app.dependency_overrides[get_runner]()
    store = runner.store
    assert client.get(f"/api/v0/runs/{run_id}/content").json() == {
        "run_id": run_id, "title": COURSE["topic"], "chapters": [],
    }

    run = store.get_run(run_id)
    blueprint = BlueprintDraft(lessons=[
        BlueprintLesson(
            title="第一章", learning_goal="学会第一章", evidence="完成练习", lesson_id="l1"
        ),
        BlueprintLesson(
            title="第二章", learning_goal="学会第二章", evidence="完成练习", lesson_id="l2"
        ),
    ])
    run.blueprint = blueprint
    run = store.record(run, "artifact.created", "blueprint", blueprint)
    first = LessonDraft(title="第一章", markdown="# 原稿", lesson_id="l1")
    run.lesson = first
    run = store.record(run, "artifact.created", "generation", first, producer_role="writer")

    candidate = LessonDraft(title="第一章", markdown="# 修复稿", lesson_id="l1")
    run = store.record(
        run, "candidate.created", "quality", candidate,
        producer_role="repair", artifact_kind="lesson",
    )
    candidate_summary = run.artifacts[-1]
    before = client.get(f"/api/v0/runs/{run_id}/content").json()["chapters"]
    assert [(item["lesson_id"], item["status"], item["markdown"]) for item in before] == [
        ("l1", "generated", "# 原稿"), ("l2", "pending", None),
    ]

    run.lesson = candidate
    store.record(
        run, "candidate.accepted", "quality",
        accepted_ref=ArtifactRef(
            run_id=run_id, artifact_id=candidate_summary.artifact_id,
            version=candidate_summary.version, kind="lesson",
            content_hash=candidate_summary.content_hash,
        ),
    )
    after = client.get(f"/api/v0/runs/{run_id}/content").json()["chapters"]
    assert [(item["lesson_id"], item["markdown"], item["version"]) for item in after] == [
        ("l1", "# 修复稿", 2), ("l2", None, None),
    ]


def test_read_course_artifacts_and_snapshot(client):
    run = start(client).json()
    run_id, course_id = run["id"], run["course_id"]
    assert client.get("/api/v0/courses").json()["items"][0]["id"] == course_id
    assert client.get(f"/api/v0/courses/{course_id}").status_code == 200
    summary = client.get(f"/api/v0/runs/{run_id}/snapshot")
    assert summary.status_code == 200
    assert summary.json()["run"]["status"] == "waiting_for_human"
    artifacts = client.get(f"/api/v0/runs/{run_id}/artifacts")
    items = artifacts.json()["items"]
    assert {item["kind"] for item in items} == {
        "mission",
        "blueprint",
        "batch_plan",
        "lesson",
        "quality",
    }
    by_kind = {item["kind"]: item for item in items}
    assert by_kind["mission"]["producer_role"] == "mission"
    assert by_kind["mission"]["source_refs"] == []
    assert [ref["kind"] for ref in by_kind["blueprint"]["source_refs"]] == ["mission"]
    assert by_kind["batch_plan"]["producer_role"] == "system"
    assert [ref["kind"] for ref in by_kind["lesson"]["source_refs"]] == [
        "mission",
        "blueprint",
        "batch_plan",
    ]
    assert by_kind["quality"]["producer_role"] == "system"
    assert [ref["kind"] for ref in by_kind["quality"]["source_refs"]] == [
        "mission",
        "blueprint",
        "lesson",
    ]
    lesson = by_kind["lesson"]
    detail = client.get(
        f"/api/v0/artifacts/{lesson['artifact_id']}/versions/{lesson['version']}"
    )
    assert detail.json()["content"]["markdown"].startswith("# ")
    assert detail.json()["producer_role"] == "writer"
    assert detail.json()["source_refs"] == lesson["source_refs"]


def test_new_api_runner_reads_same_run_after_restart(client):
    created = start(client, key="restart-read").json()
    previous = app.dependency_overrides[get_runner]()
    app.dependency_overrides[get_runner] = lambda: V0Runner(
        FakeProvider(), store=FactStore(previous.store.path)
    )
    after = client.get(f"/api/v0/runs/{created['id']}")
    assert after.status_code == 200
    assert after.json()["status"] == "waiting_for_human"
    assert after.json()["course_id"] == created["course_id"]
