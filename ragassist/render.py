"""Terminal Markdown rendering for LLM answers.

LLMs answer in Markdown, and a terminal renders that poorly: fenced code blocks
show up as literal ``` rows, bold is invisible, tables collapse into noise.

Pipeline:

    markdown  --markdown2-->  HTML  --HtmlRenderer-->  ANSI

``markdown2`` does the actual Markdown parsing. That is deliberate: a
hand-written Markdown parser is a large amount of regex work that is subtly
wrong in ways that are tedious to find (intra-word underscores, unclosed
fences, nested blockquotes). ``markdown2`` is a mature, spec-tested
implementation and ships as a pure-Python universal wheel, so it installs
instantly on Termux without compiling -- unlike ``cryptography`` or ``PyYAML``.

What this module owns:

* the four constructs ``markdown2`` does not implement (subscript, superscript,
  ``==highlight==``, emoji shortcodes), applied to the HTML only outside code;
* protection for intra-word underscores, which Markdown treats as emphasis;
* the HTML-to-terminal renderer, including table layout and syntax colouring.

Covered syntax follows the Markdown Guide (basic + extended + cheat sheet);
``tests/test_render_features.py`` is the per-feature matrix.
"""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser
from typing import Iterable, Iterator

from . import ui
from .ui import paint

BOLD = ui.BOLD
DIM = ui.DIM
ITALIC = ui.ITALIC
UNDERLINE = ui.UNDERLINE
REVERSE = ui.REVERSE
STRIKE = ui.STRIKE
RESET = ui.RESET

BLACK = ui.BLACK
CYAN = ui.CYAN
GREEN = ui.GREEN
YELLOW = ui.YELLOW
BLUE = ui.BLUE
GREY = ui.GREY
RED = ui.RED
MAGENTA = ui.MAGENTA

#: Syntax colours chosen for contrast on both light and dark Termux themes.
C_KEYWORD = BLUE
C_STRING = GREEN
C_COMMENT = GREY
C_NUMBER = YELLOW
C_FUNC = CYAN

MAX_WIDTH = 100
MIN_WIDTH = 32
MAX_TABLE_COLS = 8
MAX_LIST_DEPTH = 8

MARKDOWN2_EXTRAS = [
    "fenced-code-blocks",
    "tables",
    "task_list",
    "footnotes",
    "strike",
    "cuddled-lists",
    "header-ids",
    "tag-friendly",
]
# Two extras are deliberately NOT enabled:
#   "code-friendly"    switches to Pygments, wrapping every token in
#                      <span class=...> and discarding the language attribute.
#   "markdown-in-html" re-parses code content as HTML, so an indented block
#                      containing "&lt;html&gt;" returns a real <html> tag and
#                      its text is lost.
# Fenced blocks are extracted before parsing regardless (see _extract_fenced).
# Note: "code-friendly" is deliberately NOT enabled. It switches markdown2 to
# Pygments, which wraps every token in <span class="..."> and discards the
# language attribute. This module does its own colouring and needs the hint.


# =========================================================== Markdown -> HTML

#: Intra-word underscores (snake_case) are not emphasis in CommonMark's intent
#: but are in its implementation, so they are masked before parsing.
_INTRAWORD_UNDERSCORE = re.compile(r"(?<=\w)_(?=\w)")
_UNDERSCORE_TOKEN = "ZqUndzScOReZq"


_FENCE_LINE = re.compile(r"^\s{0,3}(?P<fence>`{3,}|~{3,})\s*(?P<info>[^\s`]*)\s*$")

_CODE_ELEMENT = "rag-code"
#: Marks an explicit <br /> while a paragraph is being flattened, so real
#: hard breaks can be told apart from ordinary source newlines (which HTML
#: treats as soft, i.e. whitespace).
_BREAK_MARK = "\x00BR\x00"
_HEADING_ID_TAIL = re.compile(r"\s*\{#[^}]*\}\s*$")


def _extract_fenced(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Replace fenced code blocks with placeholders and render them here.

    markdown2 routes fences through Pygments when it is installed, which wraps
    every token in ``<span class=...>`` and drops the language attribute. Doing
    the fences here keeps the language label, supports ``~~~`` and unterminated
    fences (common when a stream is cut off), and lets the local highlighter be
    the single source of colour.

    Returns the rewritten text and the rendered blocks, in document order.
    """
    lines = text.split("\n")
    out: list[str] = []
    blocks: list[tuple[str, str]] = []
    index = 0
    total = len(lines)

    while index < total:
        opener = _FENCE_LINE.match(lines[index])
        if not opener:
            out.append(lines[index])
            index += 1
            continue

        marker = opener.group("fence")
        language = opener.group("info") or ""
        body: list[str] = []
        index += 1
        closed = False
        while index < total:
            candidate = _FENCE_LINE.match(lines[index])
            if candidate and candidate.group("fence")[0] == marker[0] \
                    and len(candidate.group("fence")) >= len(marker) \
                    and not candidate.group("info"):
                closed = True
                index += 1
                break
            body.append(lines[index])
            index += 1

        if not closed:
            # A truncated stream leaves the fence open; the block still runs to
            # the end of the answer.
            pass
        while body and not body[-1].strip():
            body.pop()

        raw = "".join(line + "\n" for line in body)
        blocks.append((render_code_block(body, language), raw))
        out.append(f"<div id=\"{_CODE_ELEMENT}-{len(blocks) - 1}\"></div>")

    return "\n".join(out), blocks


_TRIPLE_UNDERSCORE = re.compile(r"(?<![\w\\])___(?P<body>[^\n]+?)___(?![\w])")


def _markdown_to_html(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Convert Markdown to HTML, returning it with any rendered code blocks."""
    text, blocks = _extract_fenced(text)
    # markdown2 reads ___x___ as plain bold; the guide defines bold + italic.
    text = _TRIPLE_UNDERSCORE.sub(lambda m: f"***{m.group('body')}***", text)
    try:
        import markdown2
    except ImportError:  # pragma: no cover - exercised only without the extra
        return _fallback_markdown(text), blocks

    masked = _INTRAWORD_UNDERSCORE.sub(_UNDERSCORE_TOKEN, text)
    try:
        rendered = markdown2.markdown(masked, extras=MARKDOWN2_EXTRAS)
    except Exception:  # noqa: BLE001 - a parser crash must not break a reply
        return _fallback_markdown(masked), blocks

    rendered = rendered.replace(_UNDERSCORE_TOKEN, "_")
    return _augment_html(rendered), blocks


def _fallback_markdown(text: str) -> str:
    """Escape the input so a missing markdown2 degrades to readable plain text."""
    escaped = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return "<p>" + escaped.replace("\n\n", "</p><p>").replace("\n", "<br />") + "</p>"


# --- constructs markdown2 omits, applied outside <code>/<pre> only ----------

_CODE_REGION = re.compile(r"(<pre\b.*?</pre>|<code\b.*?</code>)", re.DOTALL | re.IGNORECASE)

_MARK = re.compile(r"(?<![=\w])==(?=\S)(?P<body>[^=]+?\S)==(?!=)")
_SUB = re.compile(r"(?<!~)~(?P<body>[^\s~][^~]*?)~(?!~)")
_SUP = re.compile(r"\^(?P<body>[^\s^][^^]*?)\^")
_EMOJI = re.compile(r"(?<![\w&]):(?P<name>[a-z0-9_+-]{1,40}):(?![\w;])", re.IGNORECASE)

EMOJI: dict[str, str] = {
    "smile": "\U0001f604", "smiley": "\U0001f603", "grin": "\U0001f601",
    "joy": "\U0001f602", "rofl": "\U0001f923", "wink": "\U0001f609",
    "blush": "\U0001f60a", "heart": "❤", "thumbsup": "\U0001f44d",
    "+1": "\U0001f44d", "thumbsdown": "\U0001f44e", "-1": "\U0001f44e",
    "ok_hand": "\U0001f44c", "clap": "\U0001f44f", "wave": "\U0001f44b",
    "pray": "\U0001f64f", "muscle": "\U0001f4aa", "eyes": "\U0001f440",
    "cry": "\U0001f622", "sob": "\U0001f62d", "angry": "\U0001f620",
    "thinking": "\U0001f914", "neutral_face": "\U0001f610",
    "confused": "\U0001f615", "sunglasses": "\U0001f60e",
    "fire": "\U0001f525", "star": "⭐", "sparkles": "✨",
    "zap": "⚡", "boom": "\U0001f4a5", "tada": "\U0001f389",
    "rocket": "\U0001f680", "bug": "\U0001f41b", "wrench": "\U0001f527",
    "hammer": "\U0001f528", "gear": "⚙", "lock": "\U0001f512",
    "unlock": "\U0001f513", "key": "\U0001f511", "bulb": "\U0001f4a1",
    "books": "\U0001f4da", "memo": "\U0001f4dd", "pencil": "✏",
    "paperclip": "\U0001f4ce", "link": "\U0001f517", "mag": "\U0001f50d",
    "warning": "⚠", "question": "❓", "exclamation": "❗",
    "white_check_mark": "✅", "x": "❌", "heavy_check_mark": "✔",
    "heavy_multiplication_x": "✖", "bangbang": "‼",
    "arrow_right": "➡", "arrow_left": "⬅", "arrow_up": "⬆",
    "arrow_down": "⬇", "recycle": "♻", "infinity": "∞",
    "hourglass": "⌛", "watch": "⌚", "alarm_clock": "⏰",
    "package": "\U0001f4e6", "computer": "\U0001f4bb", "iphone": "\U0001f4f1",
    "bar_chart": "\U0001f4ca", "chart_with_upwards_trend": "\U0001f4c8",
    "white_circle": "⚪", "black_circle": "⚫", "green_circle": "\U0001f7e2",
    "red_circle": "\U0001f534", "yellow_circle": "\U0001f7e1",
}

_SUB_CHARS = str.maketrans("0123456789+-=()aehkmnopstuvx",
                           "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕₖₘₙₒₚₛₜᵤᵥₓ")
_SUP_CHARS = str.maketrans("0123456789+-=()abcdefghijklmnoprstuvwxyz",
                           "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ")


def _augment_html(document: str) -> str:
    """Add sub/sup/highlight/emoji outside code regions.

    Splitting on code regions first means these rules can never rewrite the
    inside of a code block, which is the whole point of running them here
    rather than on the Markdown.
    """
    parts = _CODE_REGION.split(document)
    for index in range(0, len(parts), 2):   # even indices are not code
        parts[index] = _augment_fragment(parts[index])
    return "".join(parts)


_LEFTOVER_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~^=$])")


def _augment_fragment(fragment: str) -> str:
    # markdown2 unescapes a subset; finish the job so "\|" does not show up.
    fragment = _LEFTOVER_ESCAPE.sub(r"\1", fragment)
    fragment = _MARK.sub(lambda m: f"<mark>{m.group('body')}</mark>", fragment)
    fragment = _SUB.sub(lambda m: f"<sub>{m.group('body')}</sub>", fragment)
    fragment = _SUP.sub(lambda m: f"<sup>{m.group('body')}</sup>", fragment)
    fragment = _EMOJI.sub(
        lambda m: EMOJI.get(m.group("name").lower(), m.group(0)), fragment)
    return fragment


# =================================================================== parsing

VOID_TAGS = {"br", "img", "hr", "input", "meta", "link", "source"}
BLOCK_TAGS = {
    "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li",
    "blockquote", "pre", "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "hr", "dl", "dt", "dd", "section", "article", "header", "footer",
}

#: Tags dropped entirely rather than shown: their text is not meant to be read.
DROPPED_TAGS = {"script", "style", "head", "meta", "link", "title",
                "noscript", "_drop"}

#: Tags escaped and shown literally, because a terminal cannot render them.
LITERAL_TAGS = {"input"}


class _Node:
    """A parsed HTML element or text run."""

    __slots__ = ("tag", "attrs", "children", "text")

    def __init__(self, tag: str | None, attrs: dict | None = None,
                 text: str | None = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[_Node] = []
        self.text = text

    def get(self, name: str, default: str = "") -> str:
        return self.attrs.get(name, default) or default

    def find_all(self, tag: str) -> list["_Node"]:
        """Depth-first search in document order."""
        found: list[_Node] = []
        stack = list(reversed(self.children))
        while stack:
            node = stack.pop()
            if node.tag == tag:
                found.append(node)
            # Reversed so siblings come out in source order, not reversed.
            stack.extend(reversed(node.children))
        return found

    def find(self, tag: str) -> "_Node | None":
        results = self.find_all(tag)
        return results[0] if results else None


class _TreeBuilder(HTMLParser):
    """Builds a small node tree from HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node(None)
        self._stack = [self.root]
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth:
            if tag in DROPPED_TAGS:
                self._skip_depth += 1
            return
        if tag in DROPPED_TAGS:
            self._skip_depth = 1
            return
        node = _Node(tag, {k: (v or "") for k, v in attrs})
        self._stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        if not self._skip_depth and tag not in DROPPED_TAGS:
            self._stack[-1].children.append(
                _Node(tag, {k: (v or "") for k, v in attrs}))

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            if tag in DROPPED_TAGS:
                self._skip_depth -= 1
            return
        for position in range(len(self._stack) - 1, 0, -1):
            if self._stack[position].tag == tag:
                del self._stack[position:]
                return

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data:
            self._stack[-1].children.append(_Node(None, text=data))


def _parse_html(document: str) -> _Node:
    builder = _TreeBuilder()
    try:
        builder.feed(document)
        builder.close()
    except Exception:  # noqa: BLE001 - malformed HTML must not break a reply
        pass
    return builder.root


# ================================================================ rendering


def _visible_length(text: str) -> int:
    """Length of ``text`` ignoring ANSI escapes, counting wide glyphs as two."""
    plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in plain)


def _terminal_width() -> int:
    try:
        import shutil

        size = shutil.get_terminal_size((MAX_WIDTH, 24)).columns
    except Exception:  # noqa: BLE001
        size = MAX_WIDTH
    return max(MIN_WIDTH, min(size, MAX_WIDTH))


def _truncate(text: str, width: int) -> str:
    """Cut plain text to ``width`` visible columns, adding an ellipsis."""
    if _visible_length(text) <= width:
        return text
    out: list[str] = []
    used = 0
    for char in text:
        size = 2 if unicodedata.east_asian_width(char) in "WF" else 1
        if used + size > width - 1:
            break
        out.append(char)
        used += size
    return "".join(out) + "…"


def _pad(text: str, width: int, align: str) -> str:
    filler = max(0, width - _visible_length(text))
    if align == "right":
        return " " * filler + text
    if align == "center":
        left = filler // 2
        return " " * left + text + " " * (filler - left)
    return text + " " * filler


class HtmlRenderer:
    """Walks a parsed HTML tree and emits ANSI-decorated terminal text."""

    def __init__(self, width: int | None = None,
                 code_blocks: list[str] | None = None):
        self.width = width or _terminal_width()
        #: Fenced blocks, already rendered, keyed by the placeholder id.
        self.code_blocks = [rendered for rendered, _ in (code_blocks or [])]
        #: footnote definition id -> the number markdown2 assigned inline
        self.footnote_numbers: dict[str, str] = {}
        #: Styles applied to text at the current position, as (name, style).
        self._style: list[tuple[str, str]] = []
        self._pre_lang = ""
        self._in_pre = 0

    # ------------------------------------------------------------- styling
    def _wrap(self, text: str) -> str:
        if not text:
            return ""
        for _, style in self._style:
            text = paint(text, style)
        return text

    def _push(self, name: str, style: str) -> None:
        self._style.append((name, style))

    def _pop(self, name: str) -> None:
        for position in range(len(self._style) - 1, -1, -1):
            if self._style[position][0] == name:
                del self._style[position:]
                return

    # -------------------------------------------------------------- inline
    def render_inline(self, node: _Node) -> str:
        """Render a node's inline content, with no block-level layout."""
        if node.tag is None:
            # A text node renders its text; a synthetic wrapper renders
            # whatever it was given as children.
            if node.children:
                return self.render_inline_children(node)
            return self._wrap(node.text or "")
        if node.tag in DROPPED_TAGS:
            return ""
        if node.tag == "br":
            return _BREAK_MARK
        if node.tag == "img":
            alt = node.get("alt") or "image"
            src = node.get("src")
            label = paint(f"[image: {alt}]", MAGENTA, BOLD)
            return label + (paint(f" {src}", GREY) if src else "")
        if node.tag == "a":
            return self._render_link(node)
        if node.tag == "code":
            return paint(self._text_of(node), C_STRING)
        if node.tag == "sup" and "footnote-ref" in node.get("class"):
            anchor = node.find("a")
            number = self._text_of(node) or (anchor.get("href", "")[-1:] if anchor else "")
            if anchor is not None and anchor.get("href", "").startswith("#"):
                self.footnote_numbers[anchor.get("href")[1:]] = number
            # Footnote references read better as [1] than as a bare digit.
            return paint(f"[{number}]", CYAN, BOLD)
        if node.tag in ("sub", "sup"):
            body = "".join(self.render_inline(child)
                           for child in node.children)
            table = _SUB_CHARS if node.tag == "sub" else _SUP_CHARS
            return paint(body.translate(table), BLUE)

        self._apply_inline_style(node.tag)
        body = "".join(self.render_inline(child) for child in node.children)
        self._pop(node.tag)
        return body

    def _apply_inline_style(self, tag: str) -> None:
        if tag in ("strong", "b"):
            self._push(tag, BOLD)
        elif tag in ("em", "i", "cite", "dfn"):
            self._push(tag, ITALIC)
        elif tag in ("s", "del", "strike"):
            self._push(tag, STRIKE)
        elif tag == "mark":
            self._push(tag, REVERSE + BLACK)
        elif tag == "sub":
            self._push(tag, BLUE)
        elif tag == "sup":
            self._push(tag, BLUE)
        elif tag in ("span", "small", "u", "ins", "kbd", "abbr", "q"):
            self._push(tag, "")

    def _render_link(self, node: _Node) -> str:
        href = node.get("href")
        title = node.get("title")
        if not href:
            return self.render_inline_children(node)

        # An image inside the label carries its own placeholder; keep that
        # rather than collapsing to the bare href.
        label = self.render_inline_children(node).strip()
        if not label:
            label = href
        if label == href:
            rendered = paint(href, CYAN, UNDERLINE)
        else:
            rendered = paint(label, CYAN, BOLD) + paint(f" ({href})", GREY)
        if title:
            rendered += paint(f" \"{title}\"", GREY)
        return rendered

    def render_inline_children(self, node: _Node) -> str:
        return "".join(self.render_inline(child) for child in node.children)

    @staticmethod
    def _text_of(node: _Node) -> str:
        parts: list[str] = []
        stack = list(node.children)
        while stack:
            current = stack.pop(0)
            if current.tag is None:
                parts.append(current.text or "")
            else:
                stack = list(current.children) + stack
        return "".join(parts).strip()

    # --------------------------------------------------------------- blocks
    def render_blocks(self, nodes: list[_Node]) -> str:
        out: list[str] = []
        for node in nodes:
            rendered = self.render_block(node)
            if not rendered or not rendered.strip():
                continue
            if out:
                out.append("")
            out.append(rendered.strip("\n"))
        return "\n".join(out)

    def render_block(self, node: _Node) -> str:
        if node.tag is None:
            text = (node.text or "").strip()
            return self._wrap(text) if text else ""

        tag = node.tag
        if tag in DROPPED_TAGS:
            return ""
        if tag == "p":
            body = self.render_inline_children(node)
            # A single newline is a soft break and collapses to a space, the
            # same as a browser; only <br /> starts a new line.
            body = re.sub(r"\s*\n\s*", " ", body)
            return body.replace(_BREAK_MARK, "\n").strip()
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            return self._render_heading(node, int(tag[1]))
        if tag == "hr":
            return paint("─" * self.width, GREY)
        if tag == "div" and node.get("id", "").startswith(f"{_CODE_ELEMENT}-"):
            return self._render_code_placeholder(node)
        if tag == "pre":
            return self._render_pre(node)
        if tag == "blockquote":
            return self._render_quote(node)
        if tag == "ul":
            return self._render_list(node, ordered=False)
        if tag == "ol":
            return self._render_list(node, ordered=True)
        if tag == "table":
            return self._render_table(node)
        if tag in ("dl",):
            return self.render_blocks(node.children)
        if tag in ("dt", "dd"):
            prefix = paint("• ", CYAN) if tag == "dd" else ""
            return prefix + self.render_inline_children(node).strip()
        if tag == "div" and "footnotes" in node.get("class"):
            return self._render_footnotes(node)
        if tag == "hr":
            return paint("─" * self.width, GREY)
        if tag == "input":
            return ""
        # Generic container: render children as blocks.
        return self.render_blocks(node.children)

    def _render_code_placeholder(self, node: _Node) -> str:
        """Return a fenced block that was rendered before parsing."""
        identifier = node.get("id", "")
        if not identifier.startswith(f"{_CODE_ELEMENT}-"):
            return ""
        try:
            return self.code_blocks[int(identifier.rsplit("-", 1)[1])]
        except (ValueError, IndexError):
            return ""

    def _render_heading(self, node: _Node, level: int) -> str:
        # markdown2 moves a custom {#id} into the element's id attribute but
        # leaves the literal text in place.
        text = _HEADING_ID_TAIL.sub("", self.render_inline_children(node)).strip()
        if level == 1:
            return (paint(text, BOLD, CYAN) + "\n"
                    + paint("═" * self.width, GREY))
        if level == 2:
            return paint(text, BOLD, CYAN)
        return paint("#" * min(level, 6) + " ", GREY) + paint(text, BOLD)

    def _render_pre(self, node: _Node) -> str:
        code_node = node.find("code")
        language = self._language_of(node, code_node)
        body = self._text_of(node) if code_node else self._text_of(node)
        lines = body.split("\n")
        while lines and not lines[-1].strip():
            lines.pop()
        header = paint(language, CYAN, BOLD) if language else paint("code", GREY)
        gutter = paint("│ ", GREY)
        return header + "\n" + "\n".join(
            gutter + highlight_code(line, language) for line in lines)

    @staticmethod
    def _language_of(node: _Node, code_node: _Node | None) -> str:
        for candidate in (code_node, node):
            if candidate is None:
                continue
            classes = candidate.get("class").split()
            for name in classes:
                if name.startswith("language-"):
                    return name[len("language-"):]
                if name in ("python", "javascript", "bash", "json", "sql",
                            "typescript", "rust", "go", "java", "cpp", "c"):
                    return name
        return ""

    def _render_quote(self, node: _Node) -> str:
        body = self.render_blocks(node.children)
        prefix = paint("▎ ", GREY)
        return "\n".join(prefix + line if line else prefix.rstrip()
                         for line in body.split("\n"))

    def _render_list(self, node: _Node, ordered: bool, depth: int = 0) -> str:
        if depth > MAX_LIST_DEPTH:
            return ""
        lines: list[str] = []
        indent = "  " * depth
        ordinal = 0

        for item in node.children:
            if item.tag != "li":
                continue
            ordinal += 1
            checkbox = item.find("input")
            blocks = [child for child in item.children if child.tag != "input"]

            if checkbox is not None and "checkbox" in checkbox.get("class"):
                # ``checked`` is a bare attribute, so test presence, not value.
                checked = "checked" in checkbox.attrs
                marker = paint("☑" if checked else "☐",
                               GREEN if checked else YELLOW, BOLD)
            elif ordered:
                marker = paint(f"{ordinal}.", CYAN, BOLD)
            else:
                marker = paint("•", CYAN)

            prefix = f"{indent}{marker} "
            continuation = " " * _visible_length(prefix)

            # A list item may be inline text, or contain nested blocks.
            inline_children = [c for c in blocks if c.tag not in BLOCK_TAGS]
            nested = [c for c in blocks if c.tag in BLOCK_TAGS]

            rendered_parts: list[str] = []
            if inline_children:
                wrapper = _Node(None)
                wrapper.children = inline_children
                rendered_parts.append(self.render_inline(wrapper).strip())
            for child in nested:
                if child.tag in ("ul", "ol"):
                    rendered_parts.append(self._render_list(child,
                                                            child.tag == "ol",
                                                            depth + 1))
                else:
                    rendered_parts.append(self.render_block(child))

            rendered_parts = [part for part in rendered_parts if part]
            if not rendered_parts:
                lines.append(prefix.rstrip())
                continue

            head, *rest = rendered_parts[0].split("\n")
            lines.append(prefix + head)
            lines.extend(continuation + line if line else ""
                         for line in rest[1:])
            for extra in rendered_parts[1:]:
                lines.append("")
                lines.append(extra)

        return "\n".join(line for line in lines if line != "" or True)

    # --------------------------------------------------------------- tables
    def _render_table(self, node: _Node) -> str:
        rows = node.find_all("tr")
        if not rows:
            return ""

        header_rows: list[_Node] = []
        body_rows: list[_Node] = []
        for row in rows:
            if row.find("th") is not None:
                header_rows.append(row)
            else:
                body_rows.append(row)

        def cells_of(row: _Node) -> list[str]:
            return [self.render_inline(cell).strip()
                    for cell in row.children if cell.tag in ("td", "th")]

        header = cells_of(header_rows[0]) if header_rows else []
        body = [cells_of(row) for row in body_rows]

        alignments: list[str] = []
        if header_rows:
            for cell in header_rows[0].children:
                if cell.tag not in ("td", "th"):
                    continue
                style = cell.get("style").replace(" ", "").lower()
                if "text-align:center" in style:
                    alignments.append("center")
                elif "text-align:right" in style:
                    alignments.append("right")
                elif "text-align:left" in style:
                    alignments.append("left")
                else:
                    alignments.append(self._guess_alignment(cell))

        columns = min(max([len(header)] + [len(r) for r in body] or [0]),
                      MAX_TABLE_COLS)
        if not columns:
            return ""
        header = (header + [""] * columns)[:columns]
        body = [(row + [""] * columns)[:columns] for row in body]
        alignments = (alignments + ["left"] * columns)[:columns]

        rendered_cells = [header] + body
        natural = [
            max((_visible_length(row[index]) for row in rendered_cells), default=3)
            for index in range(columns)
        ]

        borders = 2 * columns + 1
        budget = max(self.width - borders - 1, columns * 4)
        widths = list(natural)
        while sum(widths) > budget:
            widest = max(range(columns), key=lambda index: widths[index])
            if widths[widest] <= 6:
                break
            widths[widest] -= 1

        bar = paint("│", GREY)
        horizontal = paint("─", GREY)

        def row_line(cells: list[str], bold: bool) -> str:
            parts = []
            for index in range(columns):
                text = _truncate(cells[index], widths[index])
                text = _pad(text, widths[index], alignments[index])
                if bold:
                    text = paint(text, BOLD)
                parts.append(paint(" ") + text + paint(" "))
            return bar + bar.join(parts) + bar

        def rule_line(left: str, joint: str, right: str) -> str:
            return (paint(left, GREY)
                    + paint(joint, GREY).join(horizontal * (w + 2)
                                              for w in widths)
                    + paint(right, GREY))

        out = [
            rule_line("┌", "┬", "┐"),
            row_line(header, True),
            rule_line("├", "┼", "┤"),
        ]
        for row in body:
            out.append(row_line(row, False))
        out.append(rule_line("└", "┴", "┘"))
        return "\n".join(out)

    @staticmethod
    def _guess_alignment(cell: _Node) -> str:
        """Infer alignment from content when no style attribute is present."""
        style = cell.get("style").replace(" ", "").lower()
        for name, value in (("center", "center"), ("right", "right"),
                            ("left", "left")):
            if f"text-align:{value}" in style:
                return name
        body = cell.text or ""
        return "right" if body and all(ch.isdigit() or ch in ".,% -" for ch in body) \
            else "left"

    # ------------------------------------------------------------ footnotes
    def _render_footnotes(self, node: _Node) -> str:
        items = node.find_all("li")
        if not items:
            return ""
        parts: list[tuple[int, str]] = []
        for index, item in enumerate(items, start=1):
            # markdown2 appends a "jump back" anchor; it is noise in a terminal.
            for anchor in item.find_all("a"):
                if "footnoteBackLink" in anchor.get("class"):
                    anchor.tag = "_drop"
            text = self.render_inline_children(item).strip()
            # Reuse the number the inline reference showed, so the two agree
            # even when definitions appear out of reference order.
            try:
                number = int(self.footnote_numbers.get(item.get("id", ""), index))
            except (TypeError, ValueError):
                number = index
            marker = paint(f"[{number}]", CYAN, BOLD)
            parts.append((number, marker + " " + text.replace("\n", "\n    ")))

        # markdown2 emits definitions in source order; sort into reading order.
        ordered = [part for _, part in sorted(parts, key=lambda pair: pair[0])]
        return paint("─" * self.width, GREY) + "\n" + "\n".join(ordered)


# ============================================================ code colouring

_COMMON_KEYWORDS = {
    "if", "else", "elif", "for", "while", "return", "break", "continue",
    "class", "def", "import", "from", "as", "pass", "yield", "lambda",
    "try", "except", "finally", "raise", "with", "and", "or", "not", "in",
    "is", "None", "True", "False", "self", "async", "await", "global",
    "nonlocal", "assert", "del", "switch", "case", "default", "const",
    "let", "var", "function", "new", "this", "typeof", "instanceof",
    "public", "private", "protected", "static", "void", "int", "float",
    "double", "string", "bool", "char", "struct", "enum", "interface",
    "extends", "implements", "package", "namespace", "using", "template",
    "typename", "auto", "extern", "mutable", "virtual", "override", "final",
}

_COMMON_CONSTANTS = {"TRUE", "FALSE", "NULL", "NIL", "NONE", "UNDEFINED"}

LANGUAGE_ALIASES = {
    "py": "python", "python3": "python", "py3": "python", "pyi": "python",
    "js": "javascript", "mjs": "javascript", "cjs": "javascript",
    "node": "javascript", "jsx": "javascript",
    "ts": "typescript", "tsx": "typescript",
    "sh": "bash", "shell": "bash", "zsh": "bash", "console": "bash",
    "shellsession": "bash", "ps1": "powershell", "psm1": "powershell",
    "yml": "yaml", "rs": "rust", "kt": "kotlin", "kts": "kotlin",
    "rb": "ruby", "golang": "go", "objc": "c", "h": "cpp",
    "c++": "cpp", "cxx": "cpp", "hpp": "cpp", "cc": "cpp",
    "dockerfile": "docker", "makefile": "make", "mk": "make",
    "toml": "toml", "ini": "ini", "cfg": "ini", "conf": "ini",
    "text": "", "plain": "", "none": "", "txt": "",
    "diff": "diff", "patch": "diff", "log": "log",
}

_COMMENT_STYLES = {
    "python": ("#", None), "bash": ("#", None), "yaml": ("#", None),
    "ruby": ("#", None), "r": ("#", None), "toml": ("#", None),
    "make": ("#", None), "ini": ("#", None), "makefile": ("#", None),
    "javascript": ("//", "/*"), "typescript": ("//", "/*"),
    "java": ("//", "/*"), "c": ("//", "/*"), "cpp": ("//", "/*"),
    "go": ("//", "/*"), "rust": ("//", "/*"), "php": ("//", "/*"),
    "swift": ("//", "/*"), "kotlin": ("//", "/*"), "scala": ("//", "/*"),
    "json": (None, None), "sql": ("--", "/*"), "lua": ("--", "--[["),
    "docker": ("#", None),
}

_STRING_STYLES = {
    "python": {'"""', "'''", '"', "'"},
    "bash": {'"', "'"},
    "javascript": {"\"", "'", "`"},
    "typescript": {"\"", "'", "`"},
    "sql": {"'", '"'},
    "lua": {'"', "'"},
}

_KEYWORDS_BY_LANGUAGE = {
    "python": _COMMON_KEYWORDS | {
        "match", "case", "property", "staticmethod", "classmethod", "super",
        "isinstance", "getattr", "setattr", "hasattr", "print", "len", "range",
        "open", "type", "dict", "list", "set", "tuple", "str", "int", "float",
        "bytes", "repr", "format", "abs", "min", "max", "sum", "sorted", "map",
        "filter", "zip", "enumerate", "Any", "Optional", "Union", "Callable",
    },
    "bash": {"if", "then", "else", "elif", "fi", "for", "while", "do", "done",
             "case", "esac", "function", "local", "export", "return", "echo",
             "cd", "set", "unset", "source", "exit", "read", "trap", "shift",
             "declare", "readonly", "eval", "exec", "printf", "sudo", "apt"},
    "sql": {"SELECT", "FROM", "WHERE", "INSERT", "INTO", "VALUES", "UPDATE",
            "SET", "DELETE", "CREATE", "TABLE", "INDEX", "DROP", "ALTER",
            "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "ON", "GROUP", "BY",
            "ORDER", "HAVING", "LIMIT", "OFFSET", "AS", "AND", "OR", "NOT",
            "NULL", "PRIMARY", "KEY", "FOREIGN", "REFERENCES", "UNIQUE",
            "DEFAULT", "PRAGMA", "BEGIN", "COMMIT", "ROLLBACK", "WITH",
            "CASE", "WHEN", "THEN", "ELSE", "END", "DISTINCT", "EXISTS",
            "BETWEEN", "LIKE", "UNION", "ALL", "IN"},
    "go": {"func", "package", "import", "var", "const", "type", "struct",
           "interface", "map", "chan", "go", "defer", "range", "select",
           "nil", "true", "false"},
    "rust": {"fn", "let", "mut", "impl", "trait", "enum", "match", "pub",
             "use", "mod", "crate", "self", "where", "loop", "unsafe", "async",
             "await", "dyn", "ref"},
}

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER_RE = re.compile(
    r"\b\d[\d_]*(?:\.\d+)?(?:[eE][-+]?\d+)?\b|0[xXbBoO][0-9a-fA-F_]+")


def _string_end(code: str, start: int, quote: str) -> int:
    index = start + 1
    while index < len(code):
        if code[index] == "\\":
            index += 2
            continue
        if code[index] == quote:
            return index + 1
        if code[index] == "\n":
            return index
        index += 1
    return len(code)


def highlight_code(code: str, language: str = "") -> str:
    """Colourise a snippet of source code.

    Unknown languages pass through unchanged: highlighting a block wrong is
    worse than not highlighting it.
    """
    if not code or not ui._COLOUR:
        return code

    key = LANGUAGE_ALIASES.get(language.lower().strip(), language.lower().strip())
    if key == "diff":
        return _highlight_diff(code)
    if key == "log":
        return _highlight_log(code)
    if key not in _COMMENT_STYLES:
        return code

    line_comment, block_comment = _COMMENT_STYLES.get(key, (None, None))
    quotes = _STRING_STYLES.get(key, set("\"'`"))
    keywords = _KEYWORDS_BY_LANGUAGE.get(key, _COMMON_KEYWORDS)
    allow_triple = key == "python"

    out: list[str] = []
    index = 0
    length = len(code)

    while index < length:
        char = code[index]

        if block_comment and code.startswith(block_comment, index):
            end = code.find(block_comment, index + len(block_comment))
            end = length if end == -1 else end + len(block_comment)
            out.append(paint(code[index:end], C_COMMENT, ITALIC))
            index = end
            continue

        if line_comment and code.startswith(line_comment, index):
            end = code.find("\n", index)
            end = length if end == -1 else end
            out.append(paint(code[index:end], C_COMMENT, ITALIC))
            index = end
            continue

        if char in quotes:
            if allow_triple and code.startswith(char * 3, index):
                marker = char * 3
                end = code.find(marker, index + 3)
                end = length if end == -1 else end + 3
            else:
                end = _string_end(code, index, char)
            out.append(paint(code[index:end], C_STRING))
            index = end
            continue

        number = _NUMBER_RE.match(code, index)
        if number and (char.isdigit() or (char == "." and index + 1 < length
                                          and code[index + 1].isdigit())):
            out.append(paint(number.group(0), C_NUMBER))
            index = number.end()
            continue

        word = _WORD_RE.match(code, index)
        if word:
            token = word.group(0)
            following = index + len(token)
            if token.upper() in _COMMON_CONSTANTS:
                out.append(paint(token, C_NUMBER, BOLD))
            elif token in keywords or token.upper() in keywords:
                out.append(paint(token, C_KEYWORD, BOLD))
            elif following < length and code[following] == "(":
                out.append(paint(token, C_FUNC))
            else:
                out.append(token)
            index = following
            continue

        out.append(char)
        index += 1

    return "".join(out)


def _highlight_diff(code: str) -> str:
    out: list[str] = []
    for line in code.split("\n"):
        if line.startswith(("+++", "---")):
            out.append(paint(line, CYAN, BOLD))
        elif line.startswith("@@"):
            out.append(paint(line, MAGENTA))
        elif line.startswith("+"):
            out.append(paint(line, GREEN))
        elif line.startswith("-"):
            out.append(paint(line, RED))
        else:
            out.append(line)
        out.append("\n")
    result = "".join(out)
    return result[:-1] if code.endswith("\n") else result


_LEVEL_RE = re.compile(r"\b(DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL|TRACE)\b")
_TIME_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*")


def _highlight_log(code: str) -> str:
    out: list[str] = []
    for line in code.split("\n"):
        line = _TIME_RE.sub(lambda m: paint(m.group(0), GREY), line)
        line = _LEVEL_RE.sub(
            lambda m: paint(m.group(0), {
                "ERROR": RED, "FATAL": RED, "CRITICAL": RED,
                "WARN": YELLOW, "WARNING": YELLOW,
                "DEBUG": GREY, "TRACE": GREY,
            }.get(m.group(1), CYAN), BOLD),
            line)
        out.append(line)
        out.append("\n")
    result = "".join(out)
    return result[:-1] if code.endswith("\n") else result


# ============================================================ public API


def render_code_block(code_lines: list[str], language: str = "",
                      indent: str = "") -> str:
    """Render a code block as a labelled, gutter-indented panel."""
    label = (language or "").strip()
    header = paint(label, CYAN, BOLD) if label else paint("code", GREY)
    gutter = indent + paint("│ ", GREY)
    body = "\n".join(gutter + highlight_code(line, label) for line in code_lines)
    return f"{indent}{header}\n{body}"


def render_markdown(text: str, width: int | None = None) -> str:
    """Convert Markdown to ANSI-decorated terminal text.

    Never raises: LLM output is untrusted, so rendering must not be able to
    break a reply. On any failure the original text is returned unformatted.
    """
    if not text:
        return ""
    try:
        document, blocks = _markdown_to_html(
            text.replace("\r\n", "\n").replace("\r", "\n"))
        tree = _parse_html(document)
        renderer = HtmlRenderer(width=width, code_blocks=blocks)
        return renderer.render_blocks(tree.children).strip("\n")
    except Exception:  # noqa: BLE001 - rendering must never break a reply
        return text


def render_html(document: str, width: int | None = None) -> str:
    """Convert an HTML fragment to terminal text (used for table previews)."""
    if not document:
        return ""
    try:
        renderer = HtmlRenderer(width=width)
        return renderer.render_blocks(_parse_html(document).children).strip("\n")
    except Exception:  # noqa: BLE001
        return document


def stream_markdown(chunks: Iterable[str]) -> Iterator[str]:
    """Yield rendered fragments as Markdown arrives.

    Output is buffered to a blank line rather than flushed per line: a table
    row and its delimiter are only recognisable together, and a fenced block
    spans many lines, so line-at-a-time rendering would show raw pipes and
    stray backticks. Buffering still gives the reader output as soon as each
    paragraph or table is complete.
    """
    buffer: list[str] = []

    for chunk in chunks:
        buffer.extend(chunk.split("\n"))
        while buffer and buffer[-1] == "":
            buffer.pop()
            if buffer:
                yield render_markdown("\n".join(buffer)) + "\n\n"
            else:
                yield "\n"

    if buffer:
        yield render_markdown("\n".join(buffer))


def has_markdown(text: str) -> bool:
    """True when the text contains anything worth rendering."""
    if not text:
        return False
    return bool(
        re.search(r"^\s{0,3}(?:`{3,}|~{3,})", text, re.MULTILINE)
        or re.search(r"\*\*|__|~~|==|\[\^[^\]]+\]|^#{1,6}\s", text, re.MULTILINE)
        or re.search(r"(?<![\w\\])[*_`~^][^\s*_`~^]", text)
        or re.search(r"^\s*[-*+]\s+\S|^\s*\d{1,9}[.)]\s+\S", text, re.MULTILINE)
        or re.search(r"^\s*\|.*\|\s*$", text, re.MULTILINE)
        or re.search(r"!\[|\]\(|<https?://|^\s*>", text, re.MULTILINE)
        or _EMOJI.search(text) is not None
    )


def strip_markdown(text: str) -> str:
    """Return the plain text of a Markdown document.

    Used by ``--plain`` so copying an answer into a ticket does not drag the
    fences and pipes along.
    """
    if not text:
        return ""
    try:
        document, block_pairs = _markdown_to_html(text)
        raw_blocks = [raw for _, raw in block_pairs]
        parts: list[str] = []

        def walk(node: _Node) -> None:
            if node.tag is None:
                parts.append(node.text or "")
                return
            if node.tag in DROPPED_TAGS or node.tag in ("hr", "br"):
                return
            if node.tag == "input":
                if "checkbox" in node.get("class"):
                    parts.append("[x]" if "checked" in node.attrs else "[ ]")
                return
            if node.tag == "div":
                identifier = node.get("id", "")
                if identifier.startswith(f"{_CODE_ELEMENT}-"):
                    try:
                        index = int(identifier.rsplit("-", 1)[1])
                        parts.append(raw_blocks[index].rstrip("\n"))
                    except (ValueError, IndexError):
                        pass
                    return
            if node.tag == "img":
                parts.append(f"[image: {node.get('alt') or 'image'}]")
                return
            if node.tag == "a" and node.get("href"):
                label = "".join(child.text or ""
                                for child in node.children
                                if child.tag is None).strip()
                parts.append(label or node.get("href"))
                return
            if node.tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                parts.append("\n")
                for child in node.children:
                    walk(child)
                parts.append("\n")
                return
            if node.tag in BLOCK_TAGS or node.tag == "div":
                parts.append("\n")
                for child in node.children:
                    walk(child)
                parts.append("\n")
                return
            for child in node.children:
                walk(child)

        for child in _parse_html(document).children:
            walk(child)

        cleaned = "".join(parts)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n\s*\n\s*\n+", "\n\n", cleaned)
        return cleaned.strip()
    except Exception:  # noqa: BLE001
        return text


__all__ = [
    "render_markdown",
    "render_html",
    "stream_markdown",
    "highlight_code",
    "render_code_block",
    "has_markdown",
    "strip_markdown",
    "EMOJI",
    "LANGUAGE_ALIASES",
    "MARKDOWN2_EXTRAS",
]