"""Terminal presentation: colour, spinner, and snippet highlighting.

FR-15 requires a visible progress indicator within 500 ms of Enter. The spinner
starts its first frame on a short timer rather than after a full frame delay,
so it appears immediately even when the LLM answers instantly.
"""

from __future__ import annotations

import os
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
#: Emblem palette sampled from the logo description in BANNER.txt (hex in
#: parentheses): the left stroke runs cyan to royal blue, the diagonal is
#: electric blue, the right stroke is turquoise to mint, the star is gold,
#: and the orbit arc fades cyan to mint. Navy marks the shadowed baseline.
_GOLD = (248, 195, 92)        # #F8C35C
_CYAN = (78, 197, 252)        # #4EC5FC
_SKY = (47, 169, 240)         # cyan-blue gradient step
_ELECTRIC = (31, 154, 238)    # #1F9AEE
_ROYAL = (9, 74, 176)         # #094AB0
_TURQUOISE = (55, 198, 198)   # #37C6C6
_MINT = (64, 208, 192)        # #40D0C0
_DEEP = (36, 110, 170)        # navy shadow on the right baseline

#: A ribbon N with a small gold star above it and an orbit arc underneath.
#: Each row is a tuple of (text, colour) segments; None leaves text plain.
_EMBLEM = (
    (("     ", None), ("✦", _GOLD)),
    (("███╗", _CYAN), ("   ", None), ("██╗", _TURQUOISE)),
    (("████╗", _SKY), ("  ", None), ("██║", _TURQUOISE)),
    (("██╔", _ELECTRIC), ("██╗", _ELECTRIC), (" ", None), ("██║", _TURQUOISE)),
    (("██║", _ROYAL), ("╚██╗", _ELECTRIC), ("██║", _MINT)),
    (("██║ ", _ROYAL), ("╚", _ELECTRIC), ("████", _ELECTRIC), ("║", _MINT)),
    (("╚═╝", _ROYAL), ("  ", None), ("╚═══╝", _DEEP)),
    (("╰───", _CYAN), ("────", _TURQUOISE), ("──╯", _MINT)),
)

#: The same emblem in ASCII, for terminals that cannot show block glyphs.
_EMBLEM_ASCII = (
    (("    ", None), ("*", _GOLD)),
    (("##", _CYAN), ("   ", None), ("##", _TURQUOISE)),
    (("###", _SKY), ("  ", None), ("##", _TURQUOISE)),
    (("##", _ELECTRIC), (" #", _ELECTRIC), (" ", None), ("##", _TURQUOISE)),
    (("##", _ROYAL), ("  ", None), ("###", _MINT)),
    (("##", _ROYAL), ("   ", None), ("##", _MINT)),
    (("\\", _CYAN), ("-------", _TURQUOISE), ("/", _MINT)),
)


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
    """Print the NUSA-RG emblem: a ribbon N with a small star above it.

    Colours follow BANNER.txt (cyan-blue-turquoise gradient, gold star) and
    are dropped when output is piped, NO_COLOR is set, or --no-colour is
    given; block glyphs fall back to ASCII outside a UTF-8 terminal.
    """
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    rows = _EMBLEM if "utf" in encoding else _EMBLEM_ASCII
    for row in rows:
        print("  " + "".join(
            paint(text, _foreground(colour)) if colour else text
            for text, colour in row
        ))


def timestamp() -> str:
    return time.strftime("%H:%M:%S")