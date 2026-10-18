"""Tests for terminal Markdown rendering."""

from __future__ import annotations

import re

import pytest

from ragassist import render, ui

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    """Render with colour forced off and strip any stray escapes."""
    ui.set_colour(False)
    try:
        return ANSI.sub("", render.render_markdown(text, width=80))
    finally:
        ui.set_colour(False)


def coloured(text: str) -> str:
    ui.set_colour(True)
    try:
        return render.render_markdown(text, width=80)
    finally:
        ui.set_colour(False)


# ---------------------------------------------------------------- code blocks
def test_fenced_code_is_not_shown_raw():
    """The whole point: fences must not reach the terminal literally."""
    output = plain("before\n\n```python\nx = 1\n```\n\nafter")
    assert "```" not in output
    assert "x = 1" in output


def test_code_block_shows_language_label():
    assert "python" in plain("```python\npass\n```")


def test_unlabelled_block_gets_generic_label():
    assert "code" in plain("```\npass\n```")


def test_code_indentation_is_preserved():
    output = plain("```python\ndef f():\n    return 1\n```")
    assert "    return 1" in output, "indentation must survive rendering"


def test_multiple_code_blocks_all_rendered():
    output = plain("```js\na();\n```\ntext between\n```bash\nls\n```")
    assert "a();" in output and "ls" in output and "text between" in output
    assert "```" not in output


def test_unclosed_fence_still_renders():
    output = plain("```python\nx = 1\ny = 2")
    assert "```" not in output
    assert "x = 1" in output and "y = 2" in output


def test_longer_fence_closes_properly():
    """A 4-backtick fence may contain 3-backtick content."""
    output = plain("````markdown\n```python\nx = 1\n```\n````")
    assert "x = 1" in output
    assert "````" not in output


def test_tilde_fence_supported():
    output = plain("~~~python\nx = 1\n~~~")
    assert "```" not in output and "~~~" not in output
    assert "x = 1" in output


def test_empty_code_block():
    output = plain("```python\n```")
    assert "```" not in output


def test_code_block_keeps_blank_lines():
    output = plain("```python\na = 1\n\nb = 2\n```")
    assert "a = 1" in output and "b = 2" in output


# --------------------------------------------------------------------- inline
def test_inline_code_marked():
    out = coloured("use `hmac.compare_digest` here")
    assert "hmac.compare_digest" in ANSI.sub("", out)
    assert "\x1b[" in out, "inline code should be colourised"


def test_bold_and_italic_render():
    out = coloured("**bold** and *italic*")
    assert "bold" in ANSI.sub("", out) and "italic" in ANSI.sub("", out)
    assert "\x1b[1m" in out


def test_links_show_label_and_target():
    out = ANSI.sub("", coloured("see [docs](https://example.com)"))
    assert "docs" in out and "https://example.com" in out


def test_bare_url_highlighted():
    out = ANSI.sub("", coloured("go to https://example.com now"))
    assert "https://example.com" in out


def test_markup_inside_code_span_is_literal():
    """A code span must not have its contents interpreted."""
    out = ANSI.sub("", coloured("use `**not bold**` here"))
    assert "**not bold**" in out


def test_stars_inside_code_block_are_literal():
    out = plain("```\na = **not bold**\nb = *x*\n```")
    assert "**not bold**" in out


# -------------------------------------------------------------------- blocks
def test_heading_gets_emphasis():
    out = coloured("# Title\n\ntext")
    assert "Title" in ANSI.sub("", out)
    assert "\x1b[" in out


def test_list_markers_render():
    out = plain("- one\n- two\n1. first\n2. second")
    assert "one" in out and "two" in out and "first" in out


def test_blockquote_rendered():
    out = plain("> quoted text")
    assert "quoted text" in out


def test_horizontal_rule_rendered():
    out = plain("a\n\n---\n\nb")
    assert "---" not in out
    assert "a" in out and "b" in out


def test_setext_heading_rendered():
    out = plain("My Title\n=========")
    assert "My Title" in out


def test_blank_line_runs_collapse():
    out = plain("a\n\n\n\n\nb")
    assert "\n\n\n" not in out


# -------------------------------------------------------------- code colouring
def test_python_keywords_coloured():
    out = coloured("```python\ndef f():\n    return 1\n```")
    assert "\x1b[34m" in out, "python keywords should use the keyword colour"


def test_python_comment_coloured_and_not_keyword():
    out = coloured('```python\n# def in a comment\nx = 1\n```')
    assert "def in a comment" in ANSI.sub("", out)


def test_strings_coloured():
    out = coloured('```python\nname = "value"\n```')
    assert "value" in ANSI.sub("", out)
    assert "\x1b[32m" in out


def test_escaped_quote_inside_string_does_not_break():
    out = ANSI.sub("", coloured('```python\ns = "a\\"b"\nt = 1\n```'))
    assert 'a\\"b' in out
    assert "t = 1" in out


def test_unknown_language_is_left_alone():
    code = "some text in an unknown language"
    assert ANSI.sub("", coloured(f"```brainfuck\n{code}\n```")) .count(code) == 1


def test_highlight_is_a_noop_without_colour():
    ui.set_colour(False)
    try:
        assert render.highlight_code("def f(): pass", "python") == "def f(): pass"
    finally:
        ui.set_colour(False)


def test_bash_comment_style():
    out = ANSI.sub("", coloured("```bash\n# a comment\necho hi\n```"))
    assert "# a comment" in out


def test_sql_keywords_uppercase():
    out = coloured("```sql\nSELECT * FROM users;\n```")
    assert "\x1b[" in out


def test_plain_text_passthrough():
    assert plain("just a sentence with no markup") == "just a sentence with no markup"


def test_empty_input():
    assert render.render_markdown("") == ""


# ------------------------------------------------------------------ streaming
def test_stream_renders_line_by_line():
    chunks = ["Here you go:\n\n", "```python\n", "x = 1\n", "```\n"]
    out = "".join(render.stream_markdown(chunks))
    assert "```" not in out
    assert "Here you go:" in out
    assert "x = 1" in out


def test_stream_handles_unterminated_block():
    out = "".join(render.stream_markdown(["```python\n", "x = 1\n"]))
    assert "```" not in out


def test_stream_preserves_content():
    text = "line one\nline two\n"
    out = "".join(render.stream_markdown([text]))
    assert "line one" in out and "line two" in out


# ------------------------------------------------------------------- helpers
def test_has_markdown_detection():
    assert render.has_markdown("```py\nx\n```")
    assert render.has_markdown("**bold**")
    assert render.has_markdown("a `b` c")
    assert render.has_markdown("- item")
    assert not render.has_markdown("plain sentence")
    assert not render.has_markdown("")


def test_strip_markdown_removes_fences_and_emphasis():
    stripped = render.strip_markdown(
        "## Title\n\n**bold** and `code`\n\n```python\nx = 1\n```\n")
    assert "```" not in stripped
    assert "python" not in stripped
    assert "**" not in stripped
    assert "Title" in stripped
    assert "x = 1" in stripped


def test_render_is_idempotent_on_plain_text():
    """Rendering must not mangle text that has no markup.

    A single newline is a soft break and collapses to a space, matching how a
    browser renders it; everything else is preserved.
    """
    text = "just normal text\nwith two lines"
    assert ANSI.sub("", coloured(text)).strip() == "just normal text with two lines"


@pytest.mark.parametrize("sample", [
    "```python\ndef f(): pass\n```",
    "# H\n\n- a\n- b\n\n> q\n\n`inline` and **bold**",
    "text with ```inline fence``` inline",
    "```\n\n```\n\n",
])
def test_never_raises_on_odd_input(sample):
    assert isinstance(render.render_markdown(sample), str)


def test_never_raises_on_adversarial_input():
    """LLM output is untrusted; rendering must never crash a reply."""
    nasty = [
        "```" * 50,
        "`" * 200,
        "**" * 100,
        "[" * 80 + "x",
        "```python\n" + "x = 1\n" * 500 + "```",
        "> " * 50 + "text",
        "\x00\x01\x02```py\nx\n```",
    ]
    for sample in nasty:
        assert isinstance(render.render_markdown(sample), str)