"""Static course site renderer: Markdown -> styled HTML.

Ported from the reference course studio's ``scripts/build-static-course.mjs`` so
published courses share the same page shell, class names and theme system. The
renderer is pure: it returns HTML strings and never touches the filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from pathlib import Path
import re

ASSETS_ROOT = Path(__file__).resolve().parents[1] / "course_assets"
MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"
ASSET_FILES = (
    "theme.css",
    "course-shell.css",
    "themes/guardnet.css",
    "themes/evergreen.css",
    "course.js",
    "theme-switcher.js",
    "reading-progress.js",
)
DEFAULT_TIME = "按正文展开"
DEFAULT_MARK = "COURSE"
COURSE_CSS_TEMPLATE = """\
@import url("./theme.css");
@import url("./course-shell.css");
:root {{ --course-mark: "{mark}"; }}

/* Reading progress: highlight read lessons in chapter navigation */
.chapter-nav-list a.is-read {{
  background: color-mix(in srgb, var(--accent) 8%, var(--surface));
  border-left: 3px solid color-mix(in srgb, var(--accent) 40%, transparent);
  padding-left: 5px;
}}
.chapter-nav-list a.is-read .chapter-nav-title {{ color: var(--muted-strong); }}
.chapter-nav-list a.is-read:hover {{
  background: color-mix(in srgb, var(--accent) 14%, var(--surface-raised));
}}
.read-badge {{ color: var(--accent); font-weight: 600; margin-left: 2px; }}
"""


def escape_html(value: object) -> str:
    return escape(str(value), quote=True)


def strip_markdown(value: str) -> str:
    text = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", str(value))
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"[*_`]", "", text).strip()


def _heading_id(title: str, counter: int) -> str:
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", strip_markdown(title).lower())
    slug = slug.strip("-")
    return slug or f"section-{counter}"


def _parse_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_table_separator(line: str) -> bool:
    return bool(
        re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", line.strip())
    )


def inline_markdown(value: str, glossary: dict[str, str] | None = None) -> str:
    glossary = glossary or {}
    tokens: list[str] = []

    def protect(html: str) -> str:
        marker = f"\u0000TOKEN{len(tokens)}\u0000"
        tokens.append(html)
        return marker

    text = str(value)
    text = re.sub(
        r"`([^`\n]+)`", lambda m: protect(f"<code>{escape_html(m.group(1))}</code>"), text
    )
    text = re.sub(
        r"!\[([^\]]*)\]\(([^)]+)\)",
        lambda m: protect(
            f'<img src="{escape_html(m.group(2))}" alt="{escape_html(m.group(1))}" loading="lazy">'
        ),
        text,
    )

    def link(match: re.Match) -> str:
        label, href = match.group(1), match.group(2)
        external = bool(re.match(r"^https?://", href, re.I))
        suffix = ' target="_blank" rel="noreferrer"' if external else ""
        return protect(f'<a href="{escape_html(href)}"{suffix}>{escape_html(label)}</a>')

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, text)

    def term(match: re.Match) -> str:
        name, label = match.group(1), match.group(2) or match.group(1)
        tip = glossary.get(name, "课程术语，详见术语表。")
        return protect(
            f'<span class="term" tabindex="0" data-tip="{escape_html(tip)}">'
            f"{escape_html(label)}</span>"
        )

    text = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", term, text)
    text = escape_html(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    return re.sub(
        r"\u0000TOKEN(\d+)\u0000", lambda m: tokens[int(m.group(1))], text
    )


def _is_block_start(lines: list[str], index: int) -> bool:
    line = lines[index] if index < len(lines) else ""
    if not line.strip() or line.startswith("```"):
        return True
    if re.match(r"^#{2,6}\s", line) or re.match(r"^>\s?", line):
        return True
    if re.match(r"^\s*[-*+]\s+", line) or re.match(r"^\s*\d+\.\s+", line):
        return True
    if re.match(r"^\s*(---+|\*\*\*+)\s*$", line):
        return True
    nxt = lines[index + 1] if index + 1 < len(lines) else ""
    return "|" in line and _is_table_separator(nxt)


def render_blocks(
    markdown: str, glossary: dict[str, str] | None = None
) -> tuple[str, list[dict]]:
    glossary = glossary or {}
    lines = [line.rstrip("\r") for line in markdown.split("\n")]
    parts: list[str] = []
    toc: list[dict] = []
    index = 0
    heading_counter = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        fence = re.match(r"^```([^\s]*)\s*$", line)
        if fence:
            language = fence.group(1) or "text"
            code: list[str] = []
            index += 1
            while index < len(lines) and not re.match(r"^```\s*$", lines[index]):
                code.append(lines[index])
                index += 1
            if index >= len(lines):
                raise ValueError("Markdown 代码围栏未闭合")
            index += 1
            body = escape_html("\n".join(code))
            if language.lower() == "mermaid":
                parts.append(
                    '<figure class="diagram-card"><pre class="mermaid">'
                    f"{body}</pre><figcaption>图中关系须结合相邻正文与来源理解。"
                    "</figcaption></figure>"
                )
            else:
                parts.append(
                    '<figure class="code-card"><div class="code-toolbar">'
                    f"<span>{escape_html(language)}</span>"
                    '<button class="copy-code" type="button">复制</button></div>'
                    f'<pre><code data-language="{escape_html(language)}">{body}'
                    "</code></pre></figure>"
                )
            continue

        heading = re.match(r"^(#{2,6})\s+(.+)$", line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            heading_counter += 1
            anchor = _heading_id(title, heading_counter)
            toc.append({"level": level, "title": strip_markdown(title), "id": anchor})
            parts.append(
                f'<h{level} id="{escape_html(anchor)}">'
                f"{inline_markdown(title, glossary)}</h{level}>"
            )
            index += 1
            continue

        nxt = lines[index + 1] if index + 1 < len(lines) else ""
        if "|" in line and _is_table_separator(nxt):
            headers = _parse_table_row(line)
            rows: list[str] = []
            index += 2
            while (
                index < len(lines) and "|" in lines[index] and lines[index].strip()
            ):
                rows.append(_parse_table_row(lines[index]))
                index += 1
            head = "".join(
                f"<th>{inline_markdown(cell, glossary)}</th>" for cell in headers
            )
            body_rows = "".join(
                "<tr>"
                + "".join(f"<td>{inline_markdown(cell, glossary)}</td>" for cell in row)
                + "</tr>"
                for row in rows
            )
            parts.append(
                f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
                f"<tbody>{body_rows}</tbody></table></div>"
            )
            continue

        if re.match(r"^>\s?", line):
            quote: list[str] = []
            while index < len(lines) and re.match(r"^>\s?", lines[index]):
                quote.append(re.sub(r"^>\s?", "", lines[index]))
                index += 1
            parts.append(
                f"<blockquote><p>{inline_markdown(' '.join(quote), glossary)}</p></blockquote>"
            )
            continue

        if re.match(r"^\s*[-*+]\s+", line):
            items: list[str] = []
            while index < len(lines) and re.match(r"^\s*[-*+]\s+", lines[index]):
                items.append(re.sub(r"^\s*[-*+]\s+", "", lines[index]))
                index += 1
            body = "".join(
                f"<li>{inline_markdown(item, glossary)}</li>" for item in items
            )
            parts.append(f"<ul>{body}</ul>")
            continue

        if re.match(r"^\s*\d+\.\s+", line):
            items = []
            while index < len(lines) and re.match(r"^\s*\d+\.\s+", lines[index]):
                items.append(re.sub(r"^\s*\d+\.\s+", "", lines[index]))
                index += 1
            body = "".join(
                f"<li>{inline_markdown(item, glossary)}</li>" for item in items
            )
            parts.append(f"<ol>{body}</ol>")
            continue

        if re.match(r"^\s*(---+|\*\*\*+)\s*$", line):
            parts.append("<hr>")
            index += 1
            continue

        paragraph: list[str] = []
        while (
            index < len(lines)
            and lines[index].strip()
            and not _is_block_start(lines, index)
        ):
            paragraph.append(lines[index].strip())
            index += 1
        if not paragraph:
            paragraph.append(lines[index])
            index += 1
        parts.append(f"<p>{inline_markdown(' '.join(paragraph), glossary)}</p>")
    return "\n".join(parts), toc


@dataclass
class LessonParse:
    title: str
    time: str
    summary: str
    html: str
    toc: list[dict] = field(default_factory=list)


def _split_intro(lines: list[str], title_index: int) -> tuple[str, str, int]:
    index = title_index + 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    intro: list[str] = []
    cursor = index
    while cursor < len(lines) and re.match(r"^>\s?", lines[cursor]):
        intro.append(re.sub(r"^>\s?", "", lines[cursor]).strip())
        cursor += 1
    canonical = (
        len(intro) == 2
        and intro[0].startswith("预计学习时间：")
        and intro[1].startswith("一句话总结：")
    )
    if canonical:
        return (
            intro[0][len("预计学习时间：") :].strip(),
            intro[1][len("一句话总结：") :].strip(),
            cursor,
        )
    return "", "", index


def _first_summary(lines: list[str]) -> str:
    for line in lines:
        text = line.strip()
        if not text or re.match(r"^#{1,6}\s", text) or re.match(r"^>\s?", text):
            continue
        if re.match(r"^\s*[-*+]\s+", text) or re.match(r"^\s*\d+\.\s+", text):
            continue
        summary = strip_markdown(text)
        if summary:
            return summary[:120]
    return ""


def parse_lesson(markdown: str, glossary: dict[str, str] | None = None) -> LessonParse:
    lines = [line.rstrip("\r") for line in markdown.split("\n")]
    title_index = next(
        (i for i, line in enumerate(lines) if re.match(r"^#\s+", line)), -1
    )
    if title_index < 0:
        raise ValueError("章节缺少一级标题")
    title = re.sub(r"^#\s+", "", lines[title_index]).strip()
    time, summary, body_start = _split_intro(lines, title_index)
    html, toc = render_blocks("\n".join(lines[body_start:]), glossary)
    if not summary:
        summary = _first_summary(lines[body_start:])
    return LessonParse(
        title=title,
        time=time or DEFAULT_TIME,
        summary=summary,
        html=html,
        toc=toc,
    )


def _topbar(
    course: dict,
    prefix: str,
    *,
    show_catalog: bool = True,
    home_href: str | None = "/",
) -> str:
    links: list[str] = []
    if show_catalog:
        links.append(f'<a href="{prefix}/index.html">课程目录</a>')
    if home_href:
        links.append(f'<a class="back-home" href="{home_href}">返回课程列表</a>')
    return (
        f'<header class="topbar"><a class="brand" href="{prefix}/index.html">'
        f"{escape_html(course['title'])}</a>"
        f'<nav>{"".join(links)}</nav></header>'
    )


def _toc_html(items: list[dict]) -> str:
    h2 = 0
    h3 = 0
    links: list[str] = []
    for item in items:
        if item["level"] > 3:
            continue
        if item["level"] == 2:
            h2 += 1
            h3 = 0
            num = str(h2)
        else:
            h3 += 1
            num = f"{h2}.{h3}"
        cls = ' class="sub"' if item["level"] == 3 else ""
        links.append(
            f'<a{cls} href="#{escape_html(item["id"])}">'
            f'<span class="toc-num">{num}</span>{escape_html(item["title"])}</a>'
        )
    return '<aside class="toc"><strong>本章目录</strong>' + "".join(links) + "</aside>"


def _modules(course: dict) -> list[dict]:
    modules = course.get("modules")
    if modules:
        return modules
    titles: list[str] = []
    for lesson in course["lessons"]:
        name = lesson.get("module")
        if name and name not in titles:
            titles.append(name)
    return [{"title": title, "subtitle": ""} for title in titles]


def _lesson_label(lesson: dict) -> str:
    return f"第 {lesson['number']} 章"


def _chapter_nav_html(course: dict, lesson: dict) -> str:
    modules = _modules(course)
    if not modules:
        return ""
    available = [item for item in course["lessons"] if item["status"] == "available"]
    current = next(
        (i for i, item in enumerate(available) if item["number"] == lesson["number"]),
        -1,
    )
    position = f"{current + 1} / {len(available)}" if current >= 0 else ""
    sections: list[str] = []
    for module in modules:
        mod_lessons = [
            item
            for item in course["lessons"]
            if item.get("module") == module["title"] and item["status"] == "available"
        ]
        if not mod_lessons:
            continue
        links = "".join(
            f'<a href="../{escape_html(item["href"])}"'
            + (' class="is-current" aria-current="page"' if item["number"] == lesson["number"] else "")
            + f'><span class="chapter-nav-code">{item["number"]:02d}</span>'
            + f'<span class="chapter-nav-title">{escape_html(item["title"])}</span></a>'
            for item in mod_lessons
        )
        sections.append(
            f'<section class="chapter-nav-module"><h2>'
            f'{escape_html(module["title"])}</h2>{links}</section>'
        )
    heading = '<div class="chapter-nav-heading"><strong>课程章节</strong>'
    if position:
        heading += f"<span>第 {position} 章</span>"
    heading += "</div>"
    return (
        '<aside class="chapter-nav" aria-label="课程章节导航">'
        '<button class="chapter-nav-toggle" type="button" aria-expanded="true" '
        'aria-controls="chapter-nav-content"><span aria-hidden="true">◀</span>'
        '<span class="chapter-nav-toggle-label">收起</span></button>'
        f'<div class="chapter-nav-content" id="chapter-nav-content">{heading}'
        f'<nav class="chapter-nav-list">{"".join(sections)}</nav></div></aside>'
    )


def _lesson_navigation(course: dict, lesson: dict) -> str:
    available = [item for item in course["lessons"] if item["status"] == "available"]
    current = next(
        (i for i, item in enumerate(available) if item["number"] == lesson["number"]),
        -1,
    )
    previous = available[current - 1] if current > 0 else None
    following = available[current + 1] if 0 <= current < len(available) - 1 else None
    left = (
        f'<a href="../{escape_html(previous["href"])}">← {_lesson_label(previous)}'
        f'<br><strong>{escape_html(previous["title"])}</strong></a>'
        if previous
        else "<span></span>"
    )
    right = (
        f'<a href="../{escape_html(following["href"])}">{_lesson_label(following)} →'
        f'<br><strong>{escape_html(following["title"])}</strong></a>'
        if following
        else '<a href="../index.html">返回课程目录 →</a>'
    )
    return f'<nav class="lesson-nav">{left}{right}</nav>'


def render_lesson_page(course: dict, lesson: dict, parsed: LessonParse) -> str:
    publication = "已发布"
    return (
        '<!doctype html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<meta name="description" content="{escape_html(parsed.summary)}">'
        f"<title>{escape_html(parsed.title)} | {escape_html(course['title'])}</title>"
        '<script src="../assets/theme-switcher.js"></script>'
        '<link rel="stylesheet" href="../assets/course.css">'
        f'<script defer src="{MERMAID_URL}"></script>'
        '<script defer src="../assets/course.js"></script>'
        '<script defer src="../assets/reading-progress.js"></script></head>\n'
        f'<body data-course-slug="{escape_html(course["slug"])}"><div class="course-shell">'
        '<div class="lesson-page-grid">'
        f"{_chapter_nav_html(course, lesson)}"
        '<div class="lesson-page-main">'
        f'{_topbar(course, "..")}'
        '<section class="lesson-header">'
        f'<div class="eyebrow">{escape_html(_lesson_label(lesson))} · '
        f'{escape_html(parsed.time)}</div>'
        f"<h1>{escape_html(parsed.title)}</h1>"
        f'<p class="lesson-summary">{escape_html(parsed.summary)}</p>'
        f'<a class="source-link" href="../markdown/'
        f'{escape_html(lesson["markdown"].split("/")[-1])}">查看 Markdown 版本</a>'
        "</section><div class=\"lesson-layout\">"
        f'<main class="lesson-content">{parsed.html}{_lesson_navigation(course, lesson)}'
        "</main>"
        f"{_toc_html(parsed.toc)}</div></div></div>"
        f'<footer class="site-footer">{escape_html(course["title"])} · {publication}'
        "</footer></div></body></html>"
    )


def render_index(course: dict) -> str:
    lessons = course["lessons"]
    available = [item for item in lessons if item["status"] == "available"]
    modules = _modules(course)
    grouped: list[str] = []
    for module in modules:
        mod_lessons = [
            item for item in lessons if item.get("module") == module["title"]
        ]
        if not mod_lessons:
            continue
        cards = "".join(
            f'<a class="chapter-card available" href="./{escape_html(item["href"])}">'
            f'<small>{escape_html(_lesson_label(item))} · {escape_html(item["time"])}</small>'
            f'<h3>{escape_html(item["title"])}</h3>'
            f'<p>{escape_html(item["summary"])}</p>'
            '<span class="state">开始阅读 →</span></a>'
            for item in mod_lessons
        )
        grouped.append(
            '<div class="module-section"><div class="module-heading">'
            f'<h2>{escape_html(module["title"])}</h2>'
            f'<p>{escape_html(module.get("subtitle", ""))}</p></div>'
            f'<section class="chapter-grid">{cards}</section></div>'
        )
    progress = f"{len(available) / len(lessons) * 100:.0f}%" if lessons else "0%"
    pills = [
        f'{len(lessons)} 章',
        str(course.get("duration") or "人工发布"),
    ]
    if course.get("audience"):
        pills.append(str(course["audience"]))
    pills.append("Markdown + 静态 HTML")
    pill_html = "".join(f'<span class="pill">{escape_html(p)}</span>' for p in pills)
    return (
        '<!doctype html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<meta name="description" content="{escape_html(course.get("description", ""))}">'
        f"<title>{escape_html(course['title'])} | AI Course Studio</title>"
        '<script src="./assets/theme-switcher.js"></script>'
        '<link rel="stylesheet" href="./assets/course.css"></head>\n'
        '<body><div class="site-shell">'
        f'{_topbar(course, ".", show_catalog=False)}'
        '<section class="course-hero">'
        f'<div class="eyebrow">{escape_html(course.get("kicker", "AI 课程"))}</div>'
        f"<h1>{escape_html(course['title'])}</h1>"
        f'<p class="lead">{escape_html(course.get("description", ""))}</p>'
        f'<div class="meta-row">{pill_html}</div></section>'
        '<section class="progress-panel"><div>'
        f'<strong>{len(available)} / {len(lessons)}</strong><span>已发布章节</span></div>'
        f'<div><div class="progress-track" style="--progress:{progress}"><span></span></div>'
        f'<p>{escape_html(course.get("progressNote", ""))}</p></div></section>'
        f'<div class="section-heading"><div><h2>课程目录</h2>'
        f'<p>{escape_html(course.get("catalogIntro", ""))}</p></div></div>'
        f'{"".join(grouped)}'
        f'<footer class="site-footer">{escape_html(course["title"])} · 已发布</footer>'
        "</div></body></html>"
    )


def course_css(mark: str) -> str:
    return COURSE_CSS_TEMPLATE.format(mark=escape_html(mark or DEFAULT_MARK))
