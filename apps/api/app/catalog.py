from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
COURSES_ROOT = REPOSITORY_ROOT / "courses"
EXAMPLE_COURSE_ROOT = COURSES_ROOT / "advanced-learning-of-obsidian"
PUBLISHED_ROOT = COURSES_ROOT / "published"
CATALOG_PATH = COURSES_ROOT / "catalog.json"


class CatalogError(RuntimeError):
    """课程目录写入失败；不泄露底层异常文本。"""


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


def write_course(entry: CourseSummary, catalog_path: Path | None = None) -> None:
    """Append or replace one published course by slug; never duplicate."""
    path = catalog_path or CATALOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            catalog = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CatalogError("课程目录无法读取") from error
    else:
        catalog = {"schemaVersion": 1, "courses": []}
    entries = catalog.get("courses")
    if not isinstance(entries, list):
        raise CatalogError("课程目录格式不合法")
    payload = entry.model_dump() if isinstance(entry, BaseModel) else entry
    entries = [item for item in entries if item.get("slug") != payload["slug"]]
    entries.append(payload)
    catalog["courses"] = entries
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise CatalogError("课程目录写入失败") from error
