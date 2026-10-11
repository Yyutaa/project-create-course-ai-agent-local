"""A copied application must boot without the optional example course tree."""

import subprocess
import sys
from pathlib import Path

from app.catalog import list_courses


API_ROOT = Path(__file__).resolve().parents[1]


def test_missing_example_catalog_returns_an_empty_list():
    assert list_courses().items == []


def test_api_boots_without_example_course_directory():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from fastapi.testclient import TestClient; "
            "from app.main import app; "
            "response = TestClient(app).get('/api/courses'); "
            "assert response.status_code == 200; "
            "assert response.json() == {'items': []}",
        ],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
