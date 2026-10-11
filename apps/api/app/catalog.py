from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
COURSES_ROOT = REPOSITORY_ROOT / "courses"
EXAMPLE_COURSE_ROOT = COURSES_ROOT / "advanced-learning-of-obsidian"
CATALOG_PATH = COURSES_ROOT / "catalog.json"


class CourseSummary(BaseModel):
    slug: str
    title: str
    description: str
    href: str
    chapters: int
    duration: str
    status: str


class CourseList(BaseModel):
    items: list[CourseSummary]


def list_courses() -> CourseList:
    if not CATALOG_PATH.exists():
        return CourseList(items=[])
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("课程目录无法读取") from error

    entries = catalog.get("courses", [])
    if not isinstance(entries, list):
        raise RuntimeError("课程目录格式不合法")
    return CourseList(items=[CourseSummary.model_validate(entry) for entry in entries])
