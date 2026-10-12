import importlib

from app import catalog
from app.api.course_routes import read_courses
from app.api.system_routes import read_health
from app import main


def test_health_check_is_available():
    assert read_health().model_dump() == {
        "status": "ok",
        "service": "ai-course-studio-local",
    }


def test_catalog_is_empty_without_the_optional_example_course(monkeypatch, tmp_path):
    monkeypatch.setattr(catalog, "CATALOG_PATH", tmp_path / "missing.json")

    courses = read_courses()

    assert courses.items == []


def test_application_skips_the_missing_static_example_course(monkeypatch, tmp_path):
    with monkeypatch.context() as isolated:
        isolated.setattr(
            catalog, "EXAMPLE_COURSE_ROOT", tmp_path / "missing-course"
        )
        isolated_app = importlib.reload(main).app
    importlib.reload(main)
    route_names = {getattr(route, "name", None) for route in isolated_app.routes}

    assert "course-example" not in route_names


def test_backend_entrypoint_uses_fixed_port_8002(monkeypatch):
    called = {}

    def fake_run(application, **options):
        called.update(application=application, **options)

    monkeypatch.setattr("uvicorn.run", fake_run)

    main.run()

    assert called == {
        "application": "app.main:app",
        "host": "127.0.0.1",
        "port": 8002,
        "reload": False,
    }
