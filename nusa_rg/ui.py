"""Terminal presentation: colour, spinner, and snippet highlighting.

FR-15 requires a visible progress indicator within 500 ms of Enter. The spinner
starts its first frame on a short timer rather than after a full frame delay,
so it appears immediately even when the LLM answers instantly.
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imported lazily to keep this module light
    from .banner import Facts

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"
UNDERLINE = "\033[4m"
REVERSE = "\033[7m"
STRIKE = "\033[9m"

BLACK = "\033[30m"
GREEN = "\033[32m"
BLUE = "\033[34m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
GREY = "\033[90m"

FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
ASCII_FRAMES = ("|", "/", "-", "\\")

USER_COLOR = GREEN
ASSISTANT_COLOR = BLUE
HIGHLIGHT_COLOR = YELLOW


def _supports_colour() -> bool:
    """Disable ANSI codes when output is piped or TERM is dumb."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("NUSA_RG_FORCE_COLOR"):
        return True
    if not sys.stdout.isatty():
        return False
    return os.environ.get("TERM", "") not in ("", "dumb")


_COLOUR = _supports_colour()


def set_colour(enabled: bool) -> None:
    global _COLOUR
    _COLOUR = enabled


def paint(text: str, *codes: str) -> str:
    """Wrap ``text`` in ANSI codes when the terminal supports them."""
    if not _COLOUR or not codes:
        return text
    return f"{''.join(codes)}{text}{RESET}"


def user_prompt(text: str = "you") -> str:
    return paint(f"{text} > ", USER_COLOR, BOLD)


def assistant_prompt() -> str:
    return paint("assistant > ", ASSISTANT_COLOR, BOLD)


def info(text: str) -> None:
    print(paint(text, GREY))


def success(text: str) -> None:
    print(paint(text, GREEN))


def warn(text: str) -> None:
    # Flush stdout first: when it is block-buffered (a pipe) an unflushed
    # stdout line would otherwise appear *after* this stderr line.
    sys.stdout.flush()
    print(paint(text, YELLOW), file=sys.stderr)
    sys.stderr.flush()


def error(text: str) -> None:
    sys.stdout.flush()
    print(paint(f"error: {text}", RED, BOLD), file=sys.stderr)
    sys.stderr.flush()


def highlight_snippet(snippet, max_lines: int = 12) -> None:
    """Echo retrieved context before the answer (FR-15, AC-38).

    The whole snippet is stored in the index; only the first few lines are
    printed so the terminal stays readable on a phone.
    """
    lines = snippet.content.rstrip("\n").splitlines()
    body = lines[:max_lines]
    if len(lines) > max_lines:
        body.append(paint(f"... (+{len(lines) - max_lines} more lines)", DIM))

    header = paint(f"context {snippet.path}:{snippet.start_line}-{snippet.end_line}",
                   HIGHLIGHT_COLOR, ITALIC)
    print(header)
    for line in body:
        print(paint(f"    {line}", HIGHLIGHT_COLOR))


class Spinner:
    """Minimal animation that starts instantly (AC-38)."""

    def __init__(self, message: str = "Thinking...", interval: float = 0.08):
        self.message = message
        self.interval = interval
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _frames(self) -> tuple[str, ...]:
        encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
        return FRAMES if "utf" in encoding else ASCII_FRAMES

    def _run(self) -> None:
        frames = self._frames()
        position = 0
        while not self._stop.is_set():
            if _COLOUR and sys.stdout.isatty():
                sys.stdout.write(f"\r{paint(frames[position % len(frames)], CYAN)} {self.message}")
                sys.stdout.flush()
            position += 1
            self._stop.wait(self.interval)

    def start(self) -> "Spinner":
        if not (_COLOUR and sys.stdout.isatty()):
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if _COLOUR and sys.stdout.isatty():
            sys.stdout.write("\r" + " " * (len(self.message) + 4) + "\r")
            sys.stdout.flush()


@contextmanager
def thinking(message: str = "Thinking..."):
    """Context manager wrapping a slow call with a spinner."""
    spinner = Spinner(message).start()
    try:
        yield spinner
    finally:
        spinner.stop()


def heading(text: str) -> None:
    print(paint(text, BOLD, CYAN))


# ------------------------------------------------------------------- banner
#: Banner palette, sampled from the pixel-art reference: the blocky N steps
#: through the blues from light at the top to dark at the base, its right
#: stroke stays mint, and the status box frames it in teal with sky-blue
#: labels, light-grey values, and a muted version tag.
_BLUE_TOP = (61, 182, 243)      # #3DB6F3  top block of the N
_BLUE_HIGH = (53, 170, 240)     # #35AAF0
_BLUE_MID = (46, 154, 231)      # #2E9AE7  staircase step
_BLUE_LOW = (43, 142, 227)      # #2B8EE3
_BLUE_STEP = (36, 134, 224)     # #2486E0  staircase step
_BLUE_DEEP = (31, 102, 201)     # #1F66C9
_BLUE_DARK = (26, 79, 173)      # #1A4FAD
_BLUE_BASE = (29, 119, 214)     # #1D77D6  bottom mass of the N
_MINT = (51, 204, 190)          # #33CCBE  right stroke of the N
_LABEL = (74, 184, 245)         # #4AB8F5  box labels and title
_VALUE = (230, 230, 230)        # #E6E6E6  box values
_MUTED = (138, 143, 152)        # #8A8F98  version tag
_BORDER = (45, 180, 173)        # #2DB4AD  box frame and bracket

#: The blocky N of the reference (9 columns, 5 rows). Each row is a tuple of
#: (text, colour) segments; None leaves text plain. The right stroke keeps the
#: last two columns and the staircase shifts one column per row.
_N_ART = (
    (("███", _BLUE_TOP), ("    ", None), ("██", _MINT)),
    (("████", _BLUE_HIGH), ("   ", None), ("██", _MINT)),
    (("██", _BLUE_LOW), (" ", None), ("██", _BLUE_MID), ("  ", None), ("██", _MINT)),
    (("██", _BLUE_DEEP), ("  ", None), ("██", _BLUE_STEP), (" ", None), ("██", _MINT)),
    (("██", _BLUE_DARK), ("   ", None), ("████", _BLUE_BASE)),
)

#: The rounded bracket closing the emblem, one column wider than the N.
_BRACKET = "╰────────╯"

#: Left column width: the N padded, and the bracket.
_LEFT_WIDTH = 10

#: Narrowest box interior; wider values grow the box when the terminal allows.
_MIN_BOX_INNER = 38

#: The wide layout (indent + emblem + gap + box) needs this many columns.
_WIDE_BANNER_MIN = 2 + _LEFT_WIDTH + 2 + _MIN_BOX_INNER + 2

#: Box-drawing and typographic marks fall back to these outside UTF-8 output.
_ASCII = str.maketrans({
    "█": "#", "│": "|", "─": "-", "╭": "+", "╮": "+", "╰": "+", "╯": "+",
    "·": "*", "—": "-", "…": "~",
})


def _terminal_columns() -> int:
    """Terminal width in columns (COLUMNS wins, then the tty, then 80)."""
    try:
        return shutil.get_terminal_size((80, 24)).columns
    except (AttributeError, ValueError):
        return 80


def _truecolour() -> bool:
    """True when the terminal advertises 24-bit colour support."""
    colourterm = os.environ.get("COLORTERM", "").lower()
    term = os.environ.get("TERM", "").lower()
    return colourterm in ("truecolor", "24bit") or "truecolor" in term


def _foreground(rgb: tuple[int, int, int]) -> str:
    """SGR code for ``rgb``: 24-bit where advertised, else the 256-colour cube."""
    r, g, b = rgb
    if _truecolour():
        return f"\033[38;2;{r};{g};{b}m"
    cube = 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)
    return f"\033[38;5;{cube}m"


def _fit(text: str, width: int, *, utf8: bool) -> str:
    """Pad ``text`` to ``width`` columns, middle-truncating when too long."""
    if len(text) <= width:
        return text.ljust(width)
    if width < 3:
        return text[:width]
    keep = width - 1
    head = (keep + 1) // 2
    marker = "…" if utf8 else "~"
    return text[:head] + marker + text[len(text) - (keep - head):]


def _status_card(
    facts: Facts, *, utf8: bool, max_inner: int
) -> list[list[tuple[str, tuple[int, int, int] | None]]]:
    """Rows of the status box: title line, one line per fact, bottom border."""
    pairs = (
        ("project", facts.project),
        ("branch", facts.branch),
        ("index", facts.index),
        ("model", facts.model),
        ("rtk", facts.rtk),
    )
    label_w = max(len(label) for label, _ in pairs)
    needed = 1 + label_w + 2 + max(len(value) for _, value in pairs) + 1
    inner = min(max(_MIN_BOX_INNER, needed), max(12, max_inner))
    value_w = max(1, inner - label_w - 4)

    tag = f"v{facts.version}"
    fill = max(0, inner - 11 - len(tag))
    rows = [[
        ("╭─ ", _BORDER),
        ("nusa-rg", _LABEL),
        (" ", None),
        (tag, _MUTED),
        (" ", None),
        ("─" * fill, _BORDER),
        ("╮", _BORDER),
    ]]
    for label, value in pairs:
        rows.append([
            ("│ ", _BORDER),
            (label.ljust(label_w), _LABEL),
            ("  ", None),
            (_fit(value, value_w, utf8=utf8), _VALUE),
            (" │", _BORDER),
        ])
    rows.append([("╰" + "─" * inner + "╯", _BORDER)])
    return rows


def _banner_rows(facts: Facts, *, utf8: bool, columns: int):
    """Compose the card, beside the pixel emblem when the width allows."""
    wide = columns >= _WIDE_BANNER_MIN
    limit = columns - _LEFT_WIDTH - 6 if wide else columns - 4
    card = _status_card(facts, utf8=utf8, max_inner=limit)
    if wide:
        left = [tuple(row) + ((" ", None),) for row in _N_ART]
        left.append(((" " * _LEFT_WIDTH, None),))
        left.append(((_BRACKET, _BORDER),))
        rows = [tuple(cell) + (("  ", None),) + tuple(line)
                for cell, line in zip(left, card)]
    else:
        rows = [tuple(line) for line in card]
    if utf8:
        return rows
    return [tuple((text.translate(_ASCII), colour) for text, colour in row)
            for row in rows]


def banner(facts: Facts | None = None) -> None:
    """Print the opening banner: the pixel N beside a runtime status card.

    ``facts`` come from :func:`nusa_rg.banner.collect` when omitted. The card
    sits beside the emblem on terminals at least ``_WIDE_BANNER_MIN`` columns
    wide and stands alone when narrower, truncating long values to fit.
    Colours are dropped when output is piped, NO_COLOR is set, or --no-colour
    is given, and glyphs fall back to ASCII outside a UTF-8 terminal.
    """
    if facts is None:
        from .banner import collect

        facts = collect()
    utf8 = "utf" in (getattr(sys.stdout, "encoding", "") or "").lower()
    for row in _banner_rows(facts, utf8=utf8, columns=_terminal_columns()):
        print("  " + "".join(
            paint(text, _foreground(colour)) if colour else text
            for text, colour in row
        ))


def timestamp() -> str:
    return time.strftime("%H:%M:%S")