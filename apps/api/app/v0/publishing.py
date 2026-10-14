"""Materialize a ready Run into a published static course site.

The published course is a self-contained directory under
``courses/published/<slug>/`` mirroring the reference course studio's build
output: ``course.json`` metadata, an ``index.html`` detail page, styled lesson
pages under ``lessons/``, raw Markdown exports under ``markdown/``, and a local
``assets/`` theme bundle. Publishing never mutates the example course and never
touches the SQLite facts.
"""

from hashlib import sha256
import json
from pathlib import Path
import re
import shutil

from app.v0 import static_course
from app.v0.schemas import RunContent, V0Run

SLUG_RE = re.compile(r"[^a-z0-9]+")
ASCII_WORD_RE = re.compile(r"[A-Za-z0-9]+")


class PublishError(ValueError):
    """A Run cannot be materialized as a published course."""


def slugify(value: str) -> str:
    ascii_slug = SLUG_RE.sub("-", value.strip().lower()).strip("-")
    if ascii_slug:
        return ascii_slug[:60].strip("-") or _fallback(value)
    return _fallback(value)


def _fallback(value: str) -> str:
    return "course-" + sha256(value.encode("utf-8")).hexdigest()[:10]


def derive_mark(title: str) -> str:
    tokens = ASCII_WORD_RE.findall(title)
    mark = " ".join(tokens).upper()[:20].strip()
    return mark or static_course.DEFAULT_MARK


def describe(run: V0Run) -> str:
    if run.mission is not None:
        return run.mission.learning_goal
    return run.course_input.goal


def _lesson_filename(index: int, title: str) -> str:
    return f"{index:02d}-{slugify(title)}.md"


def _copy_assets(assets_dir: Path, mark: str) -> None:
    assets_dir.mkdir(parents=True, exist_ok=True)
    for relative in static_course.ASSET_FILES:
        source = static_course.ASSETS_ROOT / relative
        destination = assets_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    (assets_dir / "course.css").write_text(
        static_course.course_css(mark), encoding="utf-8"
    )


def materialize(run: V0Run, content: RunContent, slug: str, root: Path) -> dict:
    """Write the published course files and return a catalog entry dict."""
    if run.course_id is None:
        raise PublishError("Run 缺少课程归属，无法发布")
    course_dir = root / slug
    lessons_dir = course_dir / "lessons"
    markdown_dir = course_dir / "markdown"
    lessons_dir.mkdir(parents=True, exist_ok=True)
    markdown_dir.mkdir(parents=True, exist_ok=True)

    title = content.title
    description = describe(run)
    mark = derive_mark(title)

    lessons: list[dict] = []
    for position, chapter in enumerate(content.chapters, 1):
        if chapter.status != "generated" or not chapter.markdown:
            raise PublishError("存在未生成的章节，无法发布完整课程")
        filename = _lesson_filename(position, chapter.title)
        (lessons_dir / filename).write_text(chapter.markdown, encoding="utf-8")
        (markdown_dir / filename).write_text(chapter.markdown, encoding="utf-8")
        parsed = static_course.parse_lesson(chapter.markdown)
        html_name = filename[:-3] + ".html"
        lessons.append(
            {
                "number": position,
                "title": parsed.title,
                "summary": parsed.summary,
                "time": parsed.time,
                "status": "available",
                # TODO(module-grouping): 阶段一只归入单一模块。待蓝图产出模块信息后，
                # 按模块边界自动分组章节，并在 index/章节侧栏渲染多个 module-section。
                "module": "课程章节",
                "href": f"lessons/{html_name}",
                "markdown": f"lessons/{filename}",
                "_parsed": parsed,
            }
        )

    course = {
        "slug": slug,
        "title": title,
        "description": description,
        "status": "published",
        "kicker": "AI 课程",
        "audience": "",
        "duration": "人工发布",
        "mark": mark,
        "progressNote": f"当前开放 {len(lessons)} 章；由人工发布。",
        "catalogIntro": "按章节阅读，可查阅每章的完整正文与来源说明。",
        "lessons": lessons,
    }

    _copy_assets(course_dir / "assets", mark)
    for lesson in lessons:
        html = static_course.render_lesson_page(course, lesson, lesson["_parsed"])
        (course_dir / lesson["href"]).write_text(html, encoding="utf-8")
    (course_dir / "index.html").write_text(
        static_course.render_index(course), encoding="utf-8"
    )

    export = {
        "schemaVersion": 1,
        "slug": slug,
        "title": title,
        "description": description,
        "kicker": course["kicker"],
        "duration": course["duration"],
        "mark": mark,
        "modules": [{"title": "课程章节", "subtitle": ""}],
        "lessons": [
            {key: value for key, value in lesson.items() if key != "_parsed"}
            for lesson in lessons
        ],
    }
    (course_dir / "course.json").write_text(
        json.dumps(export, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "slug": slug,
        "title": title,
        "description": description,
        "href": f"/published/{slug}/",
        "chapters": len(lessons),
        "duration": course["duration"],
        "status": "published",
    }
