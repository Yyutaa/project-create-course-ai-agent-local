from app.v0 import static_course as sc


def test_render_blocks_covers_headings_code_tables_quotes_and_lists():
    markdown = (
        "## 小节\n\n"
        "正文段落，含 **强调** 与 `inline`。\n\n"
        "> 引用一句\n\n"
        "- 甲\n- 乙\n\n"
        "1. 一\n2. 二\n\n"
        "| 列 A | 列 B |\n| --- | --- |\n| 1 | 2 |\n\n"
        "```text\nhello\n```\n\n"
        "```mermaid\ngraph TD; A-->B\n```\n"
    )
    html, toc = sc.render_blocks(markdown)

    assert '<h2 id="小节">小节</h2>' in html
    assert "<strong>强调</strong>" in html
    assert "<code>inline</code>" in html
    assert "<blockquote><p>引用一句</p></blockquote>" in html
    assert "<ul><li>甲</li><li>乙</li></ul>" in html
    assert "<ol><li>一</li><li>二</li></ol>" in html
    assert "table-wrap" in html and "<th>列 A</th>" in html
    assert '<code data-language="text">hello</code>' in html
    assert '<pre class="mermaid">graph TD; A--&gt;B</pre>' in html
    assert toc == [{"level": 2, "title": "小节", "id": "小节"}]


def test_unclosed_code_fence_is_rejected():
    try:
        sc.render_blocks("```text\nno closing fence")
    except ValueError as error:
        assert "围栏" in str(error)
    else:  # pragma: no cover - failure path
        raise AssertionError("未闭合围栏应报错")


def test_canonical_intro_supplies_time_and_summary():
    markdown = (
        "# 第一章\n\n"
        "> 预计学习时间：30 分钟\n"
        "> 一句话总结：理解基础概念。\n\n"
        "## 正文\n\n内容。\n"
    )
    parsed = sc.parse_lesson(markdown)
    assert parsed.title == "第一章"
    assert parsed.time == "30 分钟"
    assert parsed.summary == "理解基础概念。"
    assert "<blockquote>" not in parsed.html


def test_non_canonical_intro_degrades_and_keeps_blockquote():
    markdown = (
        "# 第一章\n\n"
        "> 来源边界说明：本章只建立概念框架。\n\n"
        "## 目标\n\n"
        "学完本章你应能解释 state。\n"
    )
    parsed = sc.parse_lesson(markdown)
    assert parsed.time == sc.DEFAULT_TIME
    assert parsed.summary == "学完本章你应能解释 state。"
    assert "blockquote" in parsed.html


def test_inline_markdown_renders_terms_links_and_images():
    glossary = {"RAG": "检索增强生成。"}
    html = sc.inline_markdown(
        "见 [[RAG]]，参考 [文档](https://example.com) 与 ![图](/x.png)。", glossary
    )
    assert 'class="term"' in html and 'data-tip="检索增强生成。"' in html
    assert 'target="_blank" rel="noreferrer"' in html
    assert '<img src="/x.png" alt="图" loading="lazy">' in html


def test_index_and_lesson_pages_use_reference_shell_classes():
    parsed = sc.parse_lesson("# 第一章\n\n> 预计学习时间：5 分钟\n> 一句话总结：概览。\n\n正文。\n")
    course = {
        "slug": "demo",
        "title": "示例课程",
        "description": "一段描述",
        "kicker": "AI 课程",
        "duration": "人工发布",
        "progressNote": "当前开放 1 章。",
        "catalogIntro": "按章阅读。",
        "lessons": [
            {
                "number": 1,
                "title": parsed.title,
                "summary": parsed.summary,
                "time": parsed.time,
                "status": "available",
                "module": "课程章节",
                "href": "lessons/01-1.html",
                "markdown": "lessons/01-1.md",
            }
        ],
    }
    index = sc.render_index(course)
    assert "course-hero" in index and "progress-panel" in index
    assert "chapter-card" in index and "./lessons/01-1.html" in index
    assert 'class="back-home" href="/"' in index and "返回课程列表" in index

    lesson = sc.render_lesson_page(course, course["lessons"][0], parsed)
    assert 'data-course-slug="demo"' in lesson
    assert "chapter-nav" in lesson and 'class="toc"' in lesson
    assert 'href="../markdown/01-1.md"' in lesson
    assert 'class="back-home" href="/"' in lesson and "返回课程列表" in lesson
    assert 'href="../index.html">课程目录' in lesson
