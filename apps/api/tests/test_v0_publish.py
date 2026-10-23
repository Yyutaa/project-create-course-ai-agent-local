import json

import pytest
from fastapi.testclient import TestClient

from app.api.run_routes import get_runner
from app.main import app
from app.v0.provider import FakeProvider
from app.v0.runner import V0Runner
from app.v0.schemas import CourseInput, ReleaseDecision
from app.v0.storage import FactStore
from app.v0.worker import Worker


COURSE = CourseInput(
    topic="Python 变量",
    audience="零基础学习者",
    goal="能解释并修改变量",
    language="zh",
)


def make_runner(tmp_path):
    return V0Runner(
        FakeProvider(),
        store=FactStore(tmp_path / "facts.sqlite3"),
        published_root=tmp_path / "published",
        catalog_path=tmp_path / "catalog.json",
    )


def prepare(runner):
    """Drive a legacy run to ``ready_for_release`` using the Fake Provider."""
    run, _ = runner.store.create_run(COURSE, "start-1", enqueue_start=True)
    legacy = runner.get(run.id)
    legacy.constraints_version = 0
    legacy.source_evidence_version = 0
    with runner.store.connect() as connection:
        connection.execute(
            "UPDATE runs SET mission_review_required=0, constraints_version=0, "
            "source_evidence_version=0 "
            "WHERE id=?",
            (run.id,),
        )
        connection.execute(
            "UPDATE snapshots SET projection_json=? WHERE run_id=?",
            (legacy.model_dump_json(), run.id),
        )
    Worker(runner.store.path, provider=FakeProvider()).run_once()
    assert runner.get(run.id).status == "waiting_for_human"
    runner.decide(
        run.id, ReleaseDecision(action="prepare", reason="人工审阅完成"), "release-1"
    )
    assert runner.get(run.id).status == "ready_for_release"
    return run.id


def test_publish_materializes_course_and_catalog(tmp_path):
    runner = make_runner(tmp_path)
    run_id = prepare(runner)

    published = runner.publish(run_id, "pub-1")

    assert published.status == "published"
    assert published.publication is not None
    slug = published.publication.slug
    assert published.publication.href == f"/published/{slug}/"
    course_dir = tmp_path / "published" / slug
    assert (course_dir / "index.html").is_file()
    assert (course_dir / "course.json").is_file()
    assert list((course_dir / "lessons").glob("*.md"))
    catalog = json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))
    assert any(item["slug"] == slug for item in catalog["courses"])


def test_publish_renders_styled_site_and_assets(tmp_path):
    runner = make_runner(tmp_path)
    run_id = prepare(runner)

    published = runner.publish(run_id, "pub-1")
    course_dir = tmp_path / "published" / published.publication.slug

    index = (course_dir / "index.html").read_text(encoding="utf-8")
    assert "course-hero" in index
    assert "chapter-card" in index
    assert 'href="./assets/course.css"' in index

    lesson_html = sorted((course_dir / "lessons").glob("*.html"))
    assert len(lesson_html) == 1
    lesson = lesson_html[0].read_text(encoding="utf-8")
    assert "chapter-nav" in lesson
    assert 'class="lesson-content"' in lesson
    assert "lesson-nav" in lesson

    assets = course_dir / "assets"
    for name in (
        "course.css",
        "theme.css",
        "course-shell.css",
        "course.js",
        "theme-switcher.js",
        "reading-progress.js",
        "themes/guardnet.css",
        "themes/evergreen.css",
    ):
        assert (assets / name).is_file(), name

    course = json.loads((course_dir / "course.json").read_text(encoding="utf-8"))
    assert course["lessons"][0]["href"].endswith(".html")
    assert course["mark"]


def test_published_run_leaves_the_draft_list(tmp_path):
    runner = make_runner(tmp_path)
    run_id = prepare(runner)
    assert [course.run_id for course in runner.store.list_courses()] == [run_id]

    runner.publish(run_id, "pub-1")

    assert runner.store.list_courses() == []


def test_publish_requires_a_prepared_run(tmp_path):
    runner = make_runner(tmp_path)
    run, _ = runner.store.create_run(COURSE, "start-1", enqueue_start=True)

    with pytest.raises(ValueError):
        runner.publish(run.id, "pub-1")


def test_publish_is_idempotent_and_does_not_duplicate(tmp_path):
    runner = make_runner(tmp_path)
    run_id = prepare(runner)

    first = runner.publish(run_id, "pub-1")
    second = runner.publish(run_id, "pub-1")

    assert first.publication.slug == second.publication.slug
    catalog = json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))
    slugs = [item["slug"] for item in catalog["courses"]]
    assert slugs.count(first.publication.slug) == 1


def test_publish_api_returns_published_run_and_lists_course(tmp_path, monkeypatch):
    monkeypatch.setattr("app.catalog.CATALOG_PATH", tmp_path / "catalog.json")
    runner = make_runner(tmp_path)
    run_id = prepare(runner)
    app.dependency_overrides[get_runner] = lambda: runner
    try:
        with TestClient(
            app, base_url="http://127.0.0.1:8002",
            headers={"Origin": "http://127.0.0.1:5176"},
        ) as client:
            response = client.post(
                f"/api/v0/runs/{run_id}/publish",
                headers={"Idempotency-Key": "pub-1"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "published"
            slug = body["publication"]["slug"]
            listed = client.get("/api/courses").json()["items"]
            assert any(item["slug"] == slug for item in listed)
    finally:
        app.dependency_overrides.clear()


def test_publish_api_rejects_unprepared_run(tmp_path):
    runner = make_runner(tmp_path)
    run, _ = runner.store.create_run(COURSE, "start-1", enqueue_start=True)
    app.dependency_overrides[get_runner] = lambda: runner
    try:
        with TestClient(
            app, base_url="http://127.0.0.1:8002",
            headers={"Origin": "http://127.0.0.1:5176"},
        ) as client:
            response = client.post(
                f"/api/v0/runs/{run.id}/publish",
                headers={"Idempotency-Key": "pub-1"},
            )
            assert response.status_code == 409
    finally:
        app.dependency_overrides.clear()
