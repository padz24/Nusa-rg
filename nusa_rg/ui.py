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
#: Banner palette, sampled from the pixel-art reference: the blocky N runs
#: cyan at the top to royal blue at the base, its staircase is electric blue
#: and the right stroke fades turquoise to mint; the wordmark is cyan, the
#: tagline turquoise, and the status row electric blue.
_CYAN = (78, 197, 252)        # #4EC5FC
_SKY = (47, 169, 240)         # cyan-blue gradient step
_ELECTRIC = (31, 154, 238)    # #1F9AEE
_ROYAL = (9, 74, 176)         # #094AB0
_TURQUOISE = (55, 198, 198)   # #37C6C6
_MINT = (64, 208, 192)        # #40D0C0

#: 5-row pixel glyphs for the wordmark; "#" marks a filled cell. ``_wordmark``
#: joins them into rows of exactly 34 columns, trailing blanks included.
_WORDMARK_GLYPHS = {
    "N": ("#  #", "## #", "# ##", "#  #", "#  #"),
    "U": ("#  #", "#  #", "#  #", "#  #", "####"),
    "S": ("####", "#   ", "####", "   #", "####"),
    "A": ("####", "#  #", "####", "#  #", "#  #"),
    "-": ("    ", "    ", "####", "    ", "    "),
    "R": ("####", "#  #", "####", "# # ", "#  #"),
    "G": ("####", "#   ", "# ##", "#  #", "####"),
}


def _wordmark(fill: str) -> tuple[str, ...]:
    rows = [""] * 5
    for position, letter in enumerate("NUSA-RG"):
        if position:
            rows = [row + " " for row in rows]
        rows = [row + part for row, part in zip(rows, _WORDMARK_GLYPHS[letter])]
    return tuple(row.replace("#", fill) for row in rows)


_TAGLINE = "LOCAL PROJECT RAG  •  CODING ASSISTANT"
_RULE = "─" * 42
_STATUS = "─ [ PROJECT CONTEXT • LOCAL AI • READY ] ─"

#: The blocky N of the reference banner (8 columns, 10 rows): thick left and
#: right strokes with a two-cell staircase between them. Each row is a tuple
#: of (text, colour) segments; None leaves text plain.
_N_ART = (
    (("████", _CYAN), ("  ", None), ("██", _CYAN)),
    (("████", _CYAN), ("  ", None), ("██", _CYAN)),
    (("██", _SKY), (" ", None), ("██", _ELECTRIC), (" ", None), ("██", _TURQUOISE)),
    (("██", _SKY), (" ", None), ("██", _ELECTRIC), (" ", None), ("██", _TURQUOISE)),
    (("██", _ELECTRIC), ("  ", None), ("████", _TURQUOISE)),
    (("██", _ELECTRIC), ("  ", None), ("████", _MINT)),
    (("██", _ROYAL), ("  ", None), ("████", _MINT)),
    (("██", _ROYAL), ("  ", None), ("████", _MINT)),
    (("██", _ROYAL), ("  ", None), ("████", _MINT)),
    (("██", _ROYAL), ("  ", None), ("████", _MINT)),
)

_N_ART_ASCII = tuple(
    tuple((text.replace("█", "#"), colour) for text, colour in row)
    for row in _N_ART
)


def _banner_variants():
    """Compose the (wide, narrow) row sets for block and ASCII terminals."""
    def right_block(wordmark, tagline, rule, status):
        return [((row, _CYAN),) for row in wordmark] + [
            (("", None),),
            ((tagline, _TURQUOISE),),
            (("", None),),
            ((rule, _SKY),),
            ((status, _ELECTRIC),),
        ]

    def compose(n_art, wordmark, bar, tagline, rule, status):
        rows = right_block(wordmark, tagline, rule, status)
        wide = [tuple(left) + (("  " + bar + "  ", _TURQUOISE),) + tuple(rest)
                for left, rest in zip(n_art, rows)]
        narrow = [tuple(rest) for rest in rows]
        return tuple(wide), tuple(narrow)

    blocks = compose(_N_ART, _wordmark("█"), "│", _TAGLINE, _RULE, _STATUS)
    ascii_ = compose(
        _N_ART_ASCII, _wordmark("#"), "|",
        _TAGLINE.replace("•", "*"), _RULE.replace("─", "-"),
        _STATUS.replace("─", "-").replace("•", "*"),
    )
    return blocks, ascii_


(_EMBLEM, _EMBLEM_NARROW), (_EMBLEM_ASCII, _EMBLEM_ASCII_NARROW) = (
    _banner_variants())

#: The wide banner is 57 columns; anything narrower gets the wordmark block.
_FULL_BANNER_MIN = 58


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


def banner() -> None:
    """Print the NUSA-RG banner: pixel N, wordmark, tagline, status row.

    The pixel emblem only fits beside the wordmark on terminals at least
    ``_FULL_BANNER_MIN`` columns wide; anything narrower gets the wordmark
    block on its own. Colours are dropped when output is piped, NO_COLOR is
    set, or --no-colour is given, and block glyphs fall back to ASCII
    outside a UTF-8 terminal.
    """
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    utf8 = "utf" in encoding
    if _terminal_columns() >= _FULL_BANNER_MIN:
        rows = _EMBLEM if utf8 else _EMBLEM_ASCII
    else:
        rows = _EMBLEM_NARROW if utf8 else _EMBLEM_ASCII_NARROW
    for row in rows:
        print("  " + "".join(
            paint(text, _foreground(colour)) if colour else text
            for text, colour in row
        ))


def timestamp() -> str:
    return time.strftime("%H:%M:%S")