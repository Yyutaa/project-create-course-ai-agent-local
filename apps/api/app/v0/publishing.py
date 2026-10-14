"""Materialize a ready Run into a published course directory.

The published course is a plain, self-contained directory under
``courses/published/<slug>/``: ``course.json`` metadata, ``lessons/*.md``
student-facing Markdown, and an ``index.html`` table of contents. Publishing
never mutates the example course and never touches the SQLite facts.
"""

from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re

from app.v0.schemas import RunContent, V0Run

SLUG_RE = re.compile(r"[^a-z0-9]+")


class PublishError(ValueError):
    """A Run cannot be materialized as a published course."""


def slugify(value: str) -> str:
    ascii_slug = SLUG_RE.sub("-", value.strip().lower()).strip("-")
    if ascii_slug:
        return ascii_slug[:60].strip("-") or _fallback(value)
    return _fallback(value)


def _fallback(value: str) -> str:
    return "course-" + sha256(value.encode("utf-8")).hexdigest()[:10]


def describe(run: V0Run) -> str:
    if run.mission is not None:
        return run.mission.learning_goal
    return run.course_input.goal


def _lesson_filename(index: int, title: str) -> str:
    return f"{index:02d}-{slugify(title)}.md"


def _index_html(title: str, description: str, lessons: list[tuple[str, str]]) -> str:
    cards = "\n".join(
        f'        <li><a href="./lessons/{href}"><span>{index:02d}</span>'
        f"<strong>{escape(name)}</strong></a></li>"
        for index, (name, href) in enumerate(lessons, 1)
    )
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<meta name="description" content="{escape(description)}">'
        f"<title>{escape(title)}</title>"
        "<style>body{margin:0;font-family:system-ui,-apple-system,'Noto Sans SC',"
        "sans-serif;color:#17211f;background:#f6f7f6;line-height:1.7}"
        "main{max-width:760px;margin:0 auto;padding:64px 24px}"
        "h1{font-size:32px;line-height:1.3;margin:0 0 12px}"
        ".lead{color:#4a5754;margin:0 0 40px}"
        "ol{list-style:none;margin:0;padding:0;display:grid;gap:12px}"
        "a{display:flex;gap:16px;align-items:baseline;padding:16px 20px;"
        "background:#fff;border:1px solid #e2e6e4;border-radius:12px;"
        "text-decoration:none;color:inherit}"
        "a:hover{border-color:#17211f}"
        "a span{font-variant-numeric:tabular-nums;color:#7a8683}"
        "footer{margin-top:48px;color:#7a8683;font-size:14px}"
        "</style></head>\n"
        f'<body><main><h1>{escape(title)}</h1>'
        f'<p class="lead">{escape(description)}</p>'
        f"<ol>\n{cards}\n</ol>"
        "<footer>由 AI Course Studio 人工发布</footer>"
        "</main></body></html>\n"
    )


def materialize(
    run: V0Run,
    content: RunContent,
    slug: str,
    root: Path,
) -> dict:
    """Write the published course files and return a catalog entry dict."""
    if run.course_id is None:
        raise PublishError("Run 缺少课程归属，无法发布")
    course_dir = root / slug
    lessons_dir = course_dir / "lessons"
    lessons_dir.mkdir(parents=True, exist_ok=True)

    title = content.title
    description = describe(run)
    entries: list[dict] = []
    index_links: list[tuple[str, str]] = []
    for position, chapter in enumerate(content.chapters, 1):
        if chapter.status != "generated" or not chapter.markdown:
            raise PublishError("存在未生成的章节，无法发布完整课程")
        filename = _lesson_filename(position, chapter.title)
        (lessons_dir / filename).write_text(chapter.markdown, encoding="utf-8")
        entries.append(
            {
                "number": position,
                "title": chapter.title,
                "lesson_id": chapter.lesson_id,
                "markdown": f"lessons/{filename}",
            }
        )
        index_links.append((chapter.title, filename))

    course_meta = {
        "schemaVersion": 1,
        "slug": slug,
        "title": title,
        "description": description,
        "status": "published",
        "lessons": entries,
    }
    (course_dir / "course.json").write_text(
        json.dumps(course_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (course_dir / "index.html").write_text(
        _index_html(title, description, index_links), encoding="utf-8"
    )
    return {
        "slug": slug,
        "title": title,
        "description": description,
        "href": f"/published/{slug}/",
        "chapters": len(entries),
        "duration": "人工发布",
        "status": "published",
    }
