"""A copied application must boot without the optional example course tree."""

import subprocess
import sys
from pathlib import Path

from app.catalog import list_courses


API_ROOT = Path(__file__).resolve().parents[1]


def test_missing_example_catalog_returns_an_empty_list(monkeypatch, tmp_path):
    monkeypatch.setattr("app.catalog.CATALOG_PATH", tmp_path / "missing.json")

    assert list_courses().items == []


def test_api_boots_without_example_course_directory(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; "
            "from pathlib import Path; "
            "import app.catalog as catalog; "
            "root = Path(sys.argv[1]); "
            "catalog.CATALOG_PATH = root / 'missing.json'; "
            "catalog.EXAMPLE_COURSE_ROOT = root / 'missing-course'; "
            "from fastapi.testclient import TestClient; "
            "from app.main import app; "
            "response = TestClient(app).get('/api/courses'); "
            "assert response.status_code == 200; "
            "assert response.json() == {'items': []}",
            str(tmp_path),
        ],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
