"""Terminal presentation: colour, spinner, and snippet highlighting.
FR-15 requires a visible progress indicator within 500 ms of Enter. The spinner
starts its first frame on a short timer rather than after a full frame delay,
so it appears immediately even when the LLM answers instantly.
"""
from __future__ import annotations

import math
import os
import re
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


_ANSI = re.compile(r"\033\[[0-9;]*m")


def _readline_active() -> bool:
    """True when ``input()`` will run through readline (an interactive tty)."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    try:
        import readline  # noqa: F401 - importing it is what enables line editing
    except ImportError:
        return False
    return True


def readline_safe(text: str) -> str:
    """Mark ANSI codes as zero-width so readline measures a prompt correctly.

    Without the \\001/\\002 markers readline counts colour codes as visible
    characters, which misplaces the cursor and breaks backspace and wrapping.
    Only prompts passed to ``input()`` need this; the markers are skipped when
    readline is not in play so they never leak into piped output.
    """
    if not _COLOUR or not _readline_active():
        return text
    return _ANSI.sub(lambda match: f"\001{match.group(0)}\002", text)


def user_prompt() -> str:
    return readline_safe(paint(_glyph("❯ "), _foreground(_GREEN), BOLD))


def assistant_prompt() -> str:
    return paint(_glyph("◆ "), _foreground(_PURPLE), BOLD)


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


#: Labels the default spinner cycles through (Indonesian, like the chat hints).
THINKING_PHRASES = (
    "Menyisir kode",
    "Merangkai konteks",
    "Menimbang jawaban",
    "Menyusun kata",
    "Memoles jawaban",
)

#: Wave ramp from the lowest to the highest bar, and its ASCII twin for
#: terminals that cannot encode block glyphs.
WAVE = "▁▂▃▄▅▆▇█"
ASCII_WAVE = "_.-~=+*#"


def _gradient(stops: tuple[tuple[int, int, int], ...],
              steps: int = 5) -> tuple[tuple[int, int, int], ...]:
    """Blend through ``stops`` and back to the first, so the loop is seamless."""
    ring = (*stops, stops[0])
    colours = []
    for start, end in zip(ring, ring[1:]):
        for step in range(steps):
            mix = step / steps
            colours.append(tuple(round(a + (b - a) * mix)
                                 for a, b in zip(start, end)))
    return tuple(colours)


class Spinner:
    """Status line for slow calls (AC-38): a gradient wave, a label with a
    shimmer sweeping across it, and a running timer.

    The first frame is drawn the moment ``start()`` is called. With no
    ``message`` the label cycles through ``THINKING_PHRASES``; an explicit
    message stays put and its shimmer repeats.
    """

    WAVE_WIDTH = 8
    PHRASE_SECONDS = 2.4   # how long each rotating label stays on screen
    SHIMMER_PAUSE = 10     # idle ticks between two shimmer sweeps

    def __init__(self, message: str | None = None, interval: float = 0.08):
        self.message = message
        self.interval = interval
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._started = time.monotonic()
        self._palette = _gradient((_TEAL, _LOGO_BLUES[0], _LOGO_BLUES[3], _PURPLE))
        self._label_width = max(len(text) for text in
                                ((message,) if message else THINKING_PHRASES))

    def _label(self, elapsed: float) -> tuple[str, float]:
        """The label to show, and how many seconds it has been on screen."""
        if self.message:
            return self.message, elapsed
        shown = int(elapsed // self.PHRASE_SECONDS)
        phrase = THINKING_PHRASES[shown % len(THINKING_PHRASES)]
        return phrase, elapsed - shown * self.PHRASE_SECONDS

    def _wave(self, tick: int, *, utf8: bool) -> str:
        """Two blended sine waves drawn as bars, tinted by a drifting gradient."""
        ramp = WAVE if utf8 else ASCII_WAVE
        cells = []
        for column in range(self.WAVE_WIDTH):
            level = (math.sin(tick * 0.50 - column * 0.70)
                     + math.sin(tick * 0.31 + column * 0.50)) / 4 + 0.5
            glyph = ramp[min(len(ramp) - 1, int(level * len(ramp)))]
            tint = self._palette[(column * 2 + tick // 2) % len(self._palette)]
            cells.append(paint(glyph, _foreground(tint)))
        return "".join(cells)

    def _shimmer(self, text: str, age: float) -> str:
        """The label in dim ink with a bright band sweeping across it."""
        cycle = len(text) + self.SHIMMER_PAUSE
        sweep = int(age / self.interval)
        # Rotating labels sweep once, then rest; a fixed label sweeps forever.
        centre = (sweep % cycle if self.message else min(sweep, cycle - 1)) - 2
        letters = []
        for index, char in enumerate(text):
            gap = abs(index - centre)
            if gap == 0:
                letters.append(paint(char, _foreground(_SHINE), BOLD))
            else:
                letters.append(paint(char, _foreground(_TEAL if gap == 1 else _DIM)))
        return "".join(letters)

    def _frame(self, tick: int) -> str:
        """One full status line, trimmed so a redraw can never wrap."""
        elapsed = time.monotonic() - self._started
        text, age = self._label(elapsed)
        timer = f"{elapsed:4.1f}s"
        room = _terminal_columns() - (2 + self.WAVE_WIDTH + 1 + 1 + len(timer)) - 1
        width = max(1, min(self._label_width, room))
        text = text[:width]
        return (
            "  " + self._wave(tick, utf8=_utf8()) + " "
            + self._shimmer(text, age) + " " * (width - len(text))
            + " " + paint(timer, _foreground(_DIM))
        )

    def _run(self) -> None:
        tick = 0
        while not self._stop.is_set():
            sys.stdout.write("\r" + self._frame(tick) + "\033[K")
            sys.stdout.flush()
            tick += 1
            self._stop.wait(self.interval)

    def start(self) -> "Spinner":
        if not (_COLOUR and sys.stdout.isatty()):
            return self
        self._started = time.monotonic()
        sys.stdout.write("\033[?25l")  # hide the cursor while animating
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
            sys.stdout.write("\r\033[K\033[?25h")  # wipe the line, show the cursor
            sys.stdout.flush()


@contextmanager
def thinking(message: str | None = None):
    """Context manager wrapping a slow call with a spinner.

    Without a message the label cycles through ``THINKING_PHRASES``.
    """
    spinner = Spinner(message).start()
    try:
        yield spinner
    finally:
        spinner.stop()


def heading(text: str) -> None:
    print(paint(text, BOLD, CYAN))


# ------------------------------------------------------------------- banner
#: Banner and chat palette, sampled from the reference. Every colour lives
#: here so call sites never spell out RGB triples.
_LOGO_BLUES = (
    (56, 182, 255),   # #38b6ff  column 0, row 1
    (58, 165, 240),   # #3aa5f0
    (59, 143, 224),   # #3b8fe0
    (47, 111, 208),   # #2f6fd0
    (34, 80, 176),    # #2250b0
)
_TEAL = (47, 208, 192)          # #2fd0c0
_DIM = (108, 125, 134)          # #6c7d86
_GREEN = (74, 222, 128)         # #4ade80
_PURPLE = (139, 140, 246)       # #8b8cf6
_YELLOW = (245, 185, 66)        # #f5b942
_MODEL_TEXT = (156, 199, 245)   # #9cc7f5
_SHINE = (226, 240, 255)        # #e2f0ff
_CHIPS = {
    "index_empty": ((74, 58, 18), _YELLOW),      # #4a3a12 / #f5b942
    "index_ready": ((18, 61, 42), _GREEN),       # #123d2a / #4ade80
    "model": ((23, 58, 99), _MODEL_TEXT),        # #173a63 / #9cc7f5
    "rtk_off": ((34, 44, 50), _DIM),             # #222c32 / #6c7d86
    "rtk_on": ((15, 61, 58), _TEAL),             # #0f3d3a / #2fd0c0
}

#: The N emblem, traced from the reference: five rows, nine columns wide. The
#: left stroke and the stair-step diagonal take their row's blue, the right
#: stroke is teal, and the bottom row closes with a wider bar. Rows are
#: (text, colour) runs; a None colour leaves the run blank.
_LOGO_WIDTH = 9
_LOGO = (
    (("███", _LOGO_BLUES[0]), ("    ", None), ("██", _TEAL)),
    (("████", _LOGO_BLUES[1]), ("   ", None), ("██", _TEAL)),
    (("██", _LOGO_BLUES[2]), (" ", None), ("██", _LOGO_BLUES[2]), ("  ", None), ("██", _TEAL)),
    (("██", _LOGO_BLUES[3]), ("  ", None), ("██", _LOGO_BLUES[3]), (" ", None), ("██", _TEAL)),
    (("██", _LOGO_BLUES[4]), ("   ", None), ("████", _LOGO_BLUES[2])),
)

#: Logo and typographic glyphs fall back to ASCII outside UTF-8 output.
_ASCII = str.maketrans({
    "█": "#", "·": "*", "—": "-", "…": "~", "❯": ">", "◆": "*",
})


def _utf8() -> bool:
    """True when stdout can encode the block and prompt glyphs."""
    return "utf" in (getattr(sys.stdout, "encoding", "") or "").lower()


def _glyph(text: str) -> str:
    """Fold glyphs to ASCII when stdout cannot encode them."""
    return text if _utf8() else text.translate(_ASCII)


def _terminal_columns() -> int:
    """Terminal width in columns (COLUMNS wins, then the tty, then 80)."""
    try:
        return shutil.get_terminal_size((80, 24)).columns
    except (AttributeError, ValueError):
        return 80


def _truecolour() -> bool:
    """True when COLORTERM advertises 24-bit colour (truecolor/24bit)."""
    return os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")


def _foreground(rgb: tuple[int, int, int]) -> str:
    """SGR code for ``rgb``: 24-bit where advertised, else the 256-colour cube."""
    r, g, b = rgb
    if _truecolour():
        return f"\033[38;2;{r};{g};{b}m"
    cube = 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)
    return f"\033[38;5;{cube}m"


def _background(rgb: tuple[int, int, int]) -> str:
    """SGR code for an ``rgb`` background (24-bit, or the 256-colour cube)."""
    r, g, b = rgb
    if _truecolour():
        return f"\033[48;2;{r};{g};{b}m"
    cube = 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)
    return f"\033[48;5;{cube}m"


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


_Segment = tuple[
    str,
    tuple[int, int, int] | None,
    tuple[int, int, int] | None,
    bool,
]


def _seg(
    text: str,
    colour: tuple[int, int, int] | None = None,
    background: tuple[int, int, int] | None = None,
    *,
    bold: bool = False,
) -> _Segment:
    """One styled span of a banner row."""
    return text, colour, background, bold


def _project_line(facts: Facts, width: int, *, utf8: bool) -> str:
    """Project path plus the branch when the checkout has one."""
    line = facts.project
    if facts.branch:
        line = f"{line} · {facts.branch}" if line else facts.branch
    return _fit(line, max(1, width), utf8=utf8).rstrip()


#: Longest model / index text a chip may carry before it is middle-truncated.
_MODEL_MAX = 24
_INDEX_MAX = 30


def _chip_rows(facts: Facts, *, utf8: bool, columns: int) -> list[list[_Segment]]:
    """Status chips wrapped to ``columns``; without colour they are plain text."""

    def clip(text: str, width: int) -> str:
        return _fit(text, min(len(text), width), utf8=utf8)

    ready = facts.index_ready
    index_text = clip(facts.index, _INDEX_MAX) if ready else "empty"
    chips = (
        (f"index {index_text}", _CHIPS["index_ready" if ready else "index_empty"]),
        (f"model {clip(facts.model, _MODEL_MAX)}", _CHIPS["model"]),
        (f"rtk {facts.rtk}", _CHIPS["rtk_on" if facts.rtk == "on" else "rtk_off"]),
    )
    budget = max(10, columns - 2)  # banner() indents every row by two columns
    gap = 1 if _COLOUR else 2
    rows: list[list[_Segment]] = [[]]
    used = 0
    for label, (background, foreground) in chips:
        piece = f" {label} " if _COLOUR else label
        if rows[-1] and used + gap + len(piece) > budget:
            rows.append([])  # wrap whole chips, never cut one in the middle
            used = 0
        if rows[-1]:
            rows[-1].append(_seg(" " * gap))
            used += gap
        rows[-1].append(_seg(piece, foreground, background) if _COLOUR else _seg(piece))
        used += len(piece)
    return rows


def _banner_rows(
    facts: Facts, *, utf8: bool, columns: int, logo: bool
) -> list[list[_Segment]]:
    """Compose the banner: the logo beside the identity, then the chips."""
    name = [_seg("nusa-rg", _TEAL, bold=True), _seg(f" v{facts.version}", _DIM)]
    chips = _chip_rows(facts, utf8=utf8, columns=columns)

    if columns < 40:
        # Too narrow for the emblem: just the name and the status chips.
        return [name, *chips]

    if not logo:
        # Piped output or NO_COLOR: plain identity lines, no emblem.
        return [
            name,
            [_seg("ask your codebase", _DIM)],
            [_seg(_project_line(facts, columns - 2, utf8=utf8), _DIM)],
            [],
            *chips,
        ]

    right = [
        [],
        name,
        [_seg("ask your codebase", _DIM)],
        [_seg(_project_line(facts, columns - (_LOGO_WIDTH + 4), utf8=utf8), _DIM)],
        [],
    ]
    rows = [
        [_seg(text, colour) for text, colour in logo_row] + [_seg("  ")] + text_row
        for logo_row, text_row in zip(_LOGO, right)
    ]
    rows.append([])
    rows.extend(chips)
    return rows


def _render_row(row: list[_Segment], *, utf8: bool) -> str:
    """Paint one row, folding glyphs to ASCII when the terminal needs it."""
    parts = []
    for text, colour, background, bold in row:
        if not utf8:
            text = text.translate(_ASCII)
        codes = []
        if colour:
            codes.append(_foreground(colour))
        if background:
            codes.append(_background(background))
        if bold:
            codes.append(BOLD)
        parts.append(paint(text, *codes) if codes else text)
    return "".join(parts)


def banner(facts: Facts | None = None) -> Facts:
    """Print the opening banner and return the facts it displays.

    ``facts`` come from :func:`nusa_rg.banner.collect` when omitted. The logo
    only appears on colour-capable terminals at least 40 columns wide; piped
    output and NO_COLOR get plain identity lines, and narrower terminals keep
    the name line plus the status chips.
    """
    if facts is None:
        from .banner import collect

        facts = collect()
    utf8 = _utf8()
    columns = _terminal_columns()
    logo = _COLOUR and columns >= 40
    for row in _banner_rows(facts, utf8=utf8, columns=columns, logo=logo):
        print(("  " + _render_row(row, utf8=utf8)).rstrip())
    return facts


def chat_hints(*, index_empty: bool = False) -> None:
    """Print the shortcut line (and the index nudge when the index is empty)."""
    print(
        paint("/exit", _foreground(_TEAL), BOLD)
        + paint(" keluar", _foreground(_DIM))
        + "  "
        + paint("/help", _foreground(_TEAL), BOLD)
        + paint(" perintah", _foreground(_DIM))
    )
    if index_empty:
        print(paint("index kosong, jalankan:", _foreground(_YELLOW)))
        print(paint("  nusa-rg index <path>", _foreground(_TEAL)))


def footer(seconds: float, tokens: int) -> None:
    """Print the dim turn summary: elapsed time and total tokens."""
    print(paint(_glyph(f"  {seconds:.2f}s · {tokens} tok"), _foreground(_DIM)))


def timestamp() -> str:
    return time.strftime("%H:%M:%S")
