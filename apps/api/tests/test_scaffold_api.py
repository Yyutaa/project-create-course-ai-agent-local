from app.api.course_routes import read_courses
from app.api.system_routes import read_health
from app import main
from app.main import app


def test_health_check_is_available():
    assert read_health().model_dump() == {
        "status": "ok",
        "service": "course-training-scaffold",
    }


def test_catalog_is_empty_without_the_optional_example_course():
    courses = read_courses()

    assert courses.items == []


def test_application_skips_the_missing_static_example_course():
    route_names = {getattr(route, "name", None) for route in app.routes}

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
