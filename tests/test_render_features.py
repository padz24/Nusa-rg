"""Markdown rendering tests, organised by the Markdown Guide's feature list.

Sources:
  basic    https://www.markdownguide.org/basic-syntax/
  extended https://www.markdownguide.org/extended-syntax/
  cheat    https://www.markdownguide.org/cheat-sheet/
"""

from __future__ import annotations

import re

import pytest

from ragassist import render, ui

ANSI = re.compile(r"\x1b\[[0-9;]*m")


@pytest.fixture(autouse=True)
def no_colour():
    ui.set_colour(False)
    yield
    ui.set_colour(False)


def plain(text: str, width: int = 80) -> str:
    return ANSI.sub("", render.render_markdown(text, width=width))


def colour(text: str, width: int = 80) -> str:
    ui.set_colour(True)
    try:
        return render.render_markdown(text, width=width)
    finally:
        ui.set_colour(False)


# =========================================================== BASIC SYNTAX ===

# ---------------------------------------------------------------- headings
@pytest.mark.parametrize("level", [1, 2, 3, 4, 5, 6])
def test_all_six_heading_levels(level):
    hashes = "#" * level
    out = plain(f"{hashes} Heading level {level}")
    assert f"Heading level {level}" in out


def test_setext_h1():
    out = plain("Heading level 1\n===============")
    assert "Heading level 1" in out
    assert "===" not in out


def test_setext_h2():
    out = plain("Heading level 2\n---------------")
    assert "Heading level 2" in out
    assert "---" not in out.split("\n")[-1]


def test_heading_custom_id_stripped():
    """Extended syntax: heading IDs are display metadata, not text."""
    out = plain("### My Great Heading {#custom-id}")
    assert "My Great Heading" in out
    assert "custom-id" not in out


# -------------------------------------------------------------- paragraphs
def test_paragraph_text_preserved():
    out = plain("I really like using Markdown.")
    assert "I really like using Markdown." in out


def test_line_break_preserved_without_marker():
    """Two trailing spaces are a hard break; a newline already shows it.

    An explicit "↵" glyph would be noise in a terminal, where the line ends
    anyway.
    """
    out = plain("First line.  \nSecond line.")
    assert out.splitlines()[0].strip() == "First line."
    assert out.splitlines()[1].strip() == "Second line."


def test_line_without_trailing_spaces_stays_one_paragraph():
    """A lone newline is a soft break and collapses, as in a browser."""
    out = plain("First line.\nSecond line.")
    assert out == "First line. Second line."


# --------------------------------------------------------------- emphasis
@pytest.mark.parametrize("markdown", ["**bold**", "__bold__"])
def test_bold(markdown):
    out = plain(f"I love {markdown} text.")
    assert "bold" in out and "**" not in out and "__" not in out


@pytest.mark.parametrize("markdown", ["*italic*", "_italic_"])
def test_italic(markdown):
    out = plain(f"Text is {markdown} here.")
    assert "italic" in out
    assert markdown not in out


@pytest.mark.parametrize("markdown", ["***both***", "___both___"])
def test_bold_italic(markdown):
    out = plain(f"This is {markdown} important.")
    assert "both" in out
    assert "*" not in out and "_" not in out


def test_bold_italic_mixed_delimiters():
    for markdown in ("__*x*__", "*_x_*"):
        out = plain(f"a {markdown} b")
        assert "x" in out


def test_intraword_bold_with_asterisks():
    """Guide: use asterisks, not underscores, inside a word."""
    out = plain("Love**is**bold")
    assert "Love" in out and "bold" in out


def test_snake_case_not_mangled():
    """An underscore inside a word is not emphasis."""
    out = plain("Call my_function_name now")
    assert "my_function_name" in out
    assert "_" in out


# ------------------------------------------------------------- blockquotes
def test_blockquote():
    out = plain("> Dorothy followed her.")
    assert "Dorothy followed her." in out


def test_blockquote_multiple_paragraphs():
    out = plain("> First para.\n>\n> Second para.")
    assert "First para." in out and "Second para." in out


def test_blockquote_nested():
    out = plain("> outer\n>> inner")
    assert "outer" in out and "inner" in out


def test_blockquote_with_other_elements():
    out = plain("> #### Results\n>\n> - Revenue up\n> - Profits up")
    assert "Results" in out and "Revenue up" in out and "Profits up" in out


# ------------------------------------------------------------------ lists
def test_unordered_list_all_delimiters():
    for bullet in ("-", "*", "+"):
        out = plain(f"{bullet} one\n{bullet} two")
        assert "one" in out and "two" in out


def test_ordered_list():
    out = plain("1. First\n2. Second\n3. Third")
    assert "First" in out and "Third" in out


def test_ordered_list_non_sequential_numbers():
    """The guide allows arbitrary numbers; output should renumber."""
    out = plain("1. a\n8. b\n3. c")
    assert "a" in out and "b" in out and "c" in out


def test_nested_unordered_list():
    out = plain("- one\n  - nested a\n  - nested b\n- two")
    assert "nested a" in out
    assert out.index("one") < out.index("nested a")


def test_nested_list_indentation_visible():
    out = plain("- outer\n  - inner")
    outer_line = next(line for line in out.split("\n") if "outer" in line)
    inner_line = next(line for line in out.split("\n") if "inner" in line)
    assert len(inner_line) - len(inner_line.lstrip()) > \
           len(outer_line) - len(outer_line.lstrip()), "nested item must indent"


def test_list_paragraph_continuation():
    out = plain("* first\n* second\n\n    added paragraph\n* third")
    assert "added paragraph" in out
    assert "first" in out and "third" in out


def test_list_with_indented_code_block():
    out = plain("1. Open the file.\n2. Edit:\n\n        <html>\n          <head>\n3. Done.")
    assert "<html>" in out and "<head>" in out and "Done." in out


def test_list_with_blockquote():
    out = plain("* first\n* second\n\n    > a quote\n* third")
    assert "a quote" in out


# ------------------------------------------------------------------- code
def test_inline_code():
    out = plain("At the prompt, type `nano`.")
    assert "nano" in out and "`" not in out


def test_inline_code_escaping_backticks():
    out = plain("``Use `code` in your file.``")
    assert "Use `code` in your file." in out


def test_indented_code_block():
    out = plain("Example:\n\n    <html>\n      <head>\n    </html>")
    assert "<html>" in out and "<head>" in out


def test_indented_code_requires_blank_line():
    out = plain("Example:\n\n    indented = 1")
    assert "indented = 1" in out


# --------------------------------------------------------- horizontal rules
@pytest.mark.parametrize("rule", ["***", "---", "___", "* * *", "- - -"])
def test_horizontal_rules(rule):
    out = plain(f"above\n\n{rule}\n\nbelow")
    assert rule not in out
    assert "above" in out and "below" in out


# ------------------------------------------------------------------ links
def test_inline_link():
    out = plain("My favourite is [Duck Duck Go](https://duckduckgo.com).")
    assert "Duck Duck Go" in out and "https://duckduckgo.com" in out


def test_link_with_title():
    out = plain('[Go](https://x.com "Best search")')
    assert "Go" in out and "https://x.com" in out and "Best search" in out


def test_autolink_url():
    out = plain("<https://www.example.com>")
    assert "https://www.example.com" in out


def test_autolink_email():
    out = plain("<fake@example.com>")
    assert "fake@example.com" in out


def test_bare_url_autolinked():
    out = plain("Visit http://www.example.com today")
    assert "http://www.example.com" in out


def test_bare_url_not_duplicated_with_trailing_punctuation():
    out = plain("See https://example.com.")
    assert out.count("https://example.com") == 1
    assert out.rstrip().endswith(".")


def test_backticked_url_not_autolinked():
    out = plain("`http://www.example.com`")
    assert "http://www.example.com" in out
    assert "\x1b" not in out


def test_reference_style_link():
    out = plain("It was a [hobbit-hole][1].\n\n[1]: https://en.wikipedia.org/wiki/Hobbit")
    assert "hobbit-hole" in out and "en.wikipedia.org" in out
    assert "[1]" not in out


def test_reference_style_link_with_title():
    out = plain('See [docs][d].\n\n[d]: https://x.com "Title here"')
    assert "docs" in out and "https://x.com" in out


def test_unresolved_reference_link_left_alone():
    out = plain("See [missing][nope]")
    assert "missing" in out


# ----------------------------------------------------------------- images
def test_image_shown_as_placeholder():
    out = plain("![Tux the penguin](/assets/tux.png)")
    assert "image" in out.lower()
    assert "Tux" in out
    assert "![" not in out


def test_image_with_title():
    out = plain('![The mountains](/img.jpg "San Juan")')
    assert "The mountains" in out


def test_linked_image():
    out = plain("[![alt](/i.png)](https://example.com)")
    assert "alt" in out


# -------------------------------------------------------------- escaping
def test_escaped_asterisk_is_literal():
    out = plain(r"\* Without the backslash this would be a bullet.")
    assert "Without the backslash" in out


@pytest.mark.parametrize("escaped", [
    r"\*", r"\_", r"\`", r"\\", r"\[", r"\]", r"\#", r"\+", r"\-", r"\.",
    r"\!", r"\|", r"\{", r"\}", r"\(", r"\)", r"\<", r"\>", r"\~", r"\^",
    r"\=", r"\$",
])
def test_escaped_characters_render_literally(escaped):
    out = plain(f"text {escaped} more")
    assert "text" in out and "more" in out
    assert escaped not in out


def test_escaped_pipe_in_table():
    out = plain("| a | b |\n|---|---|\n| x \\| y | z |")
    assert "x | y" in out


# ========================================================= EXTENDED SYNTAX ===

# ----------------------------------------------------------------- tables
def test_basic_table():
    out = plain("| Syntax | Description |\n| --- | --- |\n| Header | Title |\n| Paragraph | Text |")
    assert "Syntax" in out and "Description" in out
    assert "Header" in out and "Title" in out
    assert "|" not in out.replace("│", ""), "raw pipes must not survive"


def test_table_without_outer_pipes():
    out = plain("Syntax | Description\n--- | ---\nHeader | Title")
    assert "Syntax" in out and "Title" in out


def test_table_variable_cell_widths():
    out = plain("| a | b |\n| --- | ----------- |\n| x | a much longer value |")
    assert "a much longer value" in out


def test_table_alignment_markers():
    for delimiter in (":---", ":---:", "---:"):
        out = plain(f"| a | b |\n| {delimiter} | {delimiter} |\n| 1 | 2 |")
        assert "1" in out and "2" in out


def test_table_right_alignment_visible():
    out = plain("| Name | Value |\n| :--- | ---: |\n| a | 42 |")
    lines = out.split("\n")
    value_line = next(line for line in lines if "42" in line)
    assert value_line.rstrip().endswith("│"), "right-aligned cell hugs the border"


def test_table_center_alignment():
    out = plain("| a | b |\n| :---: | :---: |\n| x | y |")
    assert "x" in out and "y" in out


def test_table_with_inline_formatting():
    out = plain("| a | b |\n| --- | --- |\n| `code` | **bold** |")
    assert "code" in out and "bold" in out


def test_table_with_html_pipe_entity():
    out = plain("| a | b |\n| --- | --- |\n| x &#124; y | z |")
    assert "x | y" in out


def test_table_truncated_to_terminal_width():
    long_row = "word " * 40
    out = plain(f"| a | b |\n| --- | --- |\n| {long_row} | y |", width=50)
    assert max(len(line) for line in out.split("\n")) <= 52, "must fit the width"


def test_pipe_heavy_line_is_not_a_table_without_delimiter_row():
    out = plain("a | b | c\nno delimiter row here")
    assert "a | b | c" in out


# ----------------------------------------------------------- fenced code
@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_both_fence_styles(fence):
    out = plain(f"{fence}json\n{{\"a\": 1}}\n{fence}")
    assert '"a": 1' in out
    assert fence not in out


def test_fence_with_syntax_highlighting():
    out = colour("```python\ndef f():\n    return 1\n```")
    assert "\x1b[" in out, "the language tag should trigger colouring"
    assert "def" in ANSI.sub("", out)


def test_unclosed_fence_renders():
    out = plain("```python\nx = 1")
    assert "```" not in out and "x = 1" in out


def test_nested_fence_lengths():
    out = plain("````markdown\n```python\nx = 1\n```\n````")
    assert "x = 1" in out and "````" not in out


# -------------------------------------------------------------- footnotes
def test_footnote_reference_and_definition():
    out = plain("Here is a note.[^1]\n\n[^1]: The footnote text.")
    assert "[1]" in out
    assert "The footnote text." in out


def test_footnotes_numbered_in_order():
    out = plain("First.[^a] Second.[^b]\n\n[^a]: Alpha.\n[^b]: Beta.")
    assert "Alpha." in out and "Beta." in out
    assert out.index("Alpha.") < out.index("Beta.")


def test_footnote_identifier_is_a_word():
    out = plain("Ref.[^bignote]\n\n[^bignote]: Long note.")
    assert "Long note." in out
    assert "bignote" not in out


def test_unresolved_footnote_marker():
    out = plain("Ref.[^undefined]")
    assert "undefined" in out


# ------------------------------------------------------ definition lists
def test_definition_list():
    out = plain("Term\n: The definition.")
    assert "Term" in out and "The definition." in out


def test_definition_list_multiple_definitions():
    out = plain("Term\n: First def.\n: Second def.")
    assert "First def." in out and "Second def." in out


# ---------------------------------------------------------- strikethrough
def test_strikethrough():
    out = colour("~~The world is flat.~~ We know better.")
    assert "The world is flat." in ANSI.sub("", out)
    assert "~~" not in ANSI.sub("", out)
    assert "\x1b[" in out


# ------------------------------------------------------------ task lists
def test_task_list_checked_and_unchecked():
    out = plain("- [x] Write the release\n- [ ] Update the site")
    assert "Write the release" in out and "Update the site" in out
    assert "☑" in out and "☐" in out


def test_task_list_uppercase_x():
    out = plain("- [X] done")
    assert "☑" in out


def test_task_list_mixed_with_bullets():
    out = plain("- [ ] task\n- plain item")
    assert "task" in out and "plain item" in out


# ----------------------------------------------------------------- emoji
def test_emoji_shortcode():
    out = plain("That is so funny! :joy:")
    assert "\U0001f602" in out
    assert ":joy:" not in out


@pytest.mark.parametrize("name", [":tada:", ":rocket:", ":warning:", ":white_check_mark:"])
def test_various_emoji(name):
    out = plain(f"done {name} ok")
    assert ":", "  " not in out
    assert name not in out


def test_unknown_emoji_left_alone():
    out = plain("text :notarealemoji: more")
    assert ":notarealemoji:" in out


def test_colons_in_prose_not_emoji():
    out = plain("ratio is a : b and time 10:30 sharp")
    assert "a : b" in out


# -------------------------------------------------------------- highlight
def test_highlight():
    out = colour("I need to highlight these ==very important words==.")
    assert "very important words" in ANSI.sub("", out)
    assert "==" not in ANSI.sub("", out)
    assert "\x1b[7m" in out, "reverse video should be used"


def test_highlight_does_not_swallow_equals():
    out = plain("a == b and ==c== d")
    assert "a == b" in out


# ------------------------------------------------- subscript / superscript
def test_subscript():
    out = plain("H~2~O")
    assert "₂" in out


def test_superscript():
    out = plain("X^2^")
    assert "²" in out


def test_subscript_does_not_break_strikethrough():
    out = plain("~~gone~~ and H~2~O")
    assert "gone" in out and "₂" in out


# ------------------------------------------------------------------- HTML
def test_html_tags_are_neutralised():
    """LLM output is untrusted; tags must not survive as live markup."""
    out = plain("This <em>word</em> and <script>alert(1)</script>")
    assert "<em>" not in out
    assert "<script>" not in out
    assert "word" in out, "prose inside a presentational tag is kept"


def test_script_content_is_dropped():
    """Script/style bodies are code, not prose; showing them adds nothing."""
    out = plain("before <script>alert(1)</script> after")
    assert "alert(1)" not in out
    assert "before" in out and "after" in out


def test_html_comments_are_dropped():
    """A common way to smuggle instructions past a reader."""
    out = plain("visible <!-- hidden instruction --> text")
    assert "visible" in out and "text" in out
    assert "hidden instruction" not in out


def test_br_tag_becomes_newline():
    out = plain("line one<br>line two")
    assert "line one" in out and "line two" in out


def test_html_entities_decoded():
    out = plain("A &amp; B &lt; C &nbsp;D")
    assert "&amp;" not in out and "&lt;" not in out
    assert "A & B" in out


# ================================================================ STREAMING ==
def test_stream_renders_code_block():
    out = "".join(render.stream_markdown(["text\n\n```python\n", "x = 1\n", "```\n"]))
    assert "```" not in out and "x = 1" in out


def test_stream_preserves_all_content():
    text = "# H\n\npara one\n\n- item\n"
    out = "".join(render.stream_markdown([text]))
    assert "H" in out and "para one" in out and "item" in out


def test_stream_handles_table():
    out = "".join(render.stream_markdown(["| a | b |\n| --- | --- |\n| 1 | 2 |\n"]))
    assert "│" in out


# ================================================================= HELPERS ==
def test_has_markdown_detects_features():
    for sample in ("```py\nx\n```", "**b**", "a `b`", "- item", "# H",
                   "| a |\n| --- |\n| 1 |", "- [ ] task", "<https://x.com>",
                   "![img](x.png)", "ref[^1]", "~~s~~", "==h=="):
        assert render.has_markdown(sample), sample


def test_has_markdown_rejects_plain_text():
    for sample in ("", "plain sentence", "how do I use this?"):
        assert not render.has_markdown(sample), sample


def test_strip_markdown_produces_plain_text():
    source = ("## Title\n\n**bold** and `code` and [link](https://x.com)\n\n"
              "| a | b |\n| --- | --- |\n| 1 | 2 |\n\n```python\nx = 1\n```\n")
    out = render.strip_markdown(source)
    assert "```" not in out
    assert "**" not in out
    assert "|---" not in out
    assert "Title" in out and "x = 1" in out and "1" in out


def test_strip_markdown_removes_footnote_syntax():
    out = render.strip_markdown("Ref.[^1]\n\n[^1]: The note.")
    assert "The note." in out
    assert "[^" not in out


def test_strip_markdown_keeps_task_state():
    """--plain is for copying into a ticket, so [x]/[ ] carries meaning."""
    out = render.strip_markdown("- [x] done\n- [ ] todo")
    assert "done" in out and "todo" in out
    assert "[x]" in out and "[ ]" in out


# ================================================================ ROBUSTNESS =
def test_empty_input():
    assert render.render_markdown("") == ""


def test_plain_text_unchanged():
    text = "just a normal sentence with no markup at all"
    assert plain(text) == text


def test_idempotent_on_plain_text():
    """Prose is whitespace-normalised, as browsers do, but nothing else changes."""
    text = "line one\nline two"
    out = plain(text)
    assert out == "line one line two"
    # Rendering again must not keep changing the result.
    assert plain(out) == out


@pytest.mark.parametrize("sample", [
    "```" * 40, "`" * 200, "**" * 100, "[" * 80 + "x", "~" * 100,
    "|" * 100, "> " * 60 + "text", "#" * 30 + " h",
    "```python\n" + "x = 1\n" * 400 + "```",
    "\x00\x01\x02```py\nx\n```",
    "[]()", "[](", "![", "<>", "&", "\\", "|---|", "---", "```",
    "a\n|b\n|\n-|", "[^]:", "[^]", "=~=", "^", "~",
])
def test_never_raises_on_odd_input(sample):
    assert isinstance(render.render_markdown(sample), str)


def test_never_raises_with_narrow_width():
    for width in (1, 2, 5, 10):
        assert isinstance(render.render_markdown("| a | b |\n| --- | --- |\n| 1 | 2 |",
                                                width=width), str)


def test_deep_nesting_terminates():
    deep = "".join("  " * i + "- level\n" for i in range(30))
    assert isinstance(render.render_markdown(deep), str)


def test_no_ansi_leak_when_colour_disabled():
    assert "\x1b" not in plain("**bold** `code`\n\n| a |\n| --- |\n| 1 |")


def test_ansi_state_balanced():
    """Every painted span must reset, so colour never bleeds into the shell."""
    def end_state(text: str) -> set[str]:
        active: set[str] = set()
        for match in re.finditer(r"\x1b\[([0-9;]*)m", text):
            codes = match.group(1).split(";") if match.group(1) else ["0"]
            if codes == ["0"]:
                active.clear()
            else:
                active.update(c for c in codes if c != "0")
        return active

    for sample in ("**b** and *i* and `c`",
                   "```python\n# c\ns = 'x'\n```",
                   "| a | b |\n| --- | --- |\n| 1 | 2 |",
                   "~~s~~ ==h== H~2~O X^2^ :joy:",
                   "- [x] done\n  - nested",
                   "Ref.[^1]\n\n[^1]: note",
                   "> quote\n>> deeper",
                   "<https://x.com> and https://y.com"):
        assert end_state(colour(sample)) == set(), sample


def test_performance_large_document():
    import time

    document = ("# Heading\n\n"
                "Some prose with **bold**, `code`, and a [link](https://x.com).\n\n"
                "| a | b | c |\n| --- | :---: | ---: |\n| 1 | 2 | 3 |\n\n"
                "- item one\n- item two\n  - nested\n\n"
                "```python\ndef f():\n    return 1\n```\n\n") * 40

    start = time.perf_counter()
    out = render.render_markdown(document, width=100)
    elapsed = time.perf_counter() - start
    assert isinstance(out, str)
    assert elapsed < 2.0, f"rendering took {elapsed:.2f}s"