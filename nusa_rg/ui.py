"""Terminal presentation: colour, Rich chrome, spinner, and snippet display.

Two layers live here. The lower one (``paint`` and the plain ``info``/``warn``
helpers) is the original ANSI layer and stays dependency-free, so piped output
and the test suite keep their exact plain behaviour. The Rich layer on top is
only used on an interactive terminal: it powers the status spinner, the index
progress bar, the aligned tables, the snippet panels, and the banner intro.

Prompt colours still follow FR-14 (green for the user, blue for the assistant)
and the emblem palette is sampled from BANNER.txt.
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from typing import Sequence

try:  # rich is a declared dependency; without it, output degrades to plain.
    from rich.console import Console, Group
    from rich.padding import Padding
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )
    from rich.style import Style
    from rich.table import Table
    from rich.text import Text
    from rich.theme import Theme

    _RICH = True
except ImportError:  # pragma: no cover - exercised only without the extra
    _RICH = False

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
    global _COLOUR, _console_cache, _console_stream
    _COLOUR = enabled
    # The Rich console caches its colour decision, so drop it; the next call
    # rebuilds from the current state.
    _console_cache = None
    _console_stream = None


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
    if is_interactive():
        console(stderr=True).print(
            Panel(Text(text), title=Text("error:", style="nusa.error"),
                  title_align="left", border_style="red", padding=(0, 1))
        )
        return
    print(paint(f"error: {text}", RED, BOLD), file=sys.stderr)
    sys.stderr.flush()


def heading(text: str) -> None:
    print(paint(text, BOLD, CYAN))


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


# ------------------------------------------------------------------- palette
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

_HEX = {
    "gold": "#F8C35C",
    "cyan": "#4EC5FC",
    "sky": "#2FA9F0",
    "electric": "#1F9AEE",
    "royal": "#094AB0",
    "turquoise": "#37C6C6",
    "mint": "#40D0C0",
    "deep": "#246EAA",
}


# ---------------------------------------------------------------- rich layer
if _RICH:
    THEME = Theme({
        "nusa.gold": f"bold {_HEX['gold']}",
        "nusa.cyan": _HEX["cyan"],
        "nusa.electric": _HEX["electric"],
        "nusa.royal": _HEX["royal"],
        "nusa.turquoise": _HEX["turquoise"],
        "nusa.mint": f"bold {_HEX['mint']}",
        "nusa.ok": f"bold {_HEX['mint']}",
        "nusa.warn": "bold yellow",
        "nusa.error": "bold red",
        "nusa.label": "bold",
    })


_console_cache = None
_console_stream = None


def is_interactive() -> bool:
    """True when colour output and animation are safe to use."""
    if not _RICH or not _COLOUR:
        return False
    try:
        return bool(sys.stdout.isatty())
    except (AttributeError, ValueError):  # pragma: no cover - exotic streams
        return False


def console(*, stderr: bool = False):
    """The shared Rich console.

    Rebuilt when the target stream changes (tests swap ``sys.stdout``) or when
    ``set_colour`` flips the global colour state. ``force_terminal`` mirrors the
    legacy semantics: ``NUSA_RG_FORCE_COLOR`` forces ANSI even into a pipe, a
    colourless run gets a console that strips every escape.
    """
    global _console_cache, _console_stream
    if not _RICH:  # pragma: no cover - guarded by is_interactive() callers
        raise RuntimeError("rich is not installed")
    stream = sys.stderr if stderr else sys.stdout
    if _console_cache is None or _console_stream is not stream:
        forced = bool(os.environ.get("NUSA_RG_FORCE_COLOR"))
        _console_cache = Console(
            file=stream,
            theme=THEME,
            highlight=False,
            no_color=not _COLOUR,
            force_terminal=True if (forced and _COLOUR) else (None if _COLOUR else False),
        )
        _console_stream = stream
    return _console_cache


# ---------------------------------------------------------- content helpers
def _cell(value):
    """Content cells are plain strings, or ``(text, style)`` pairs."""
    if isinstance(value, tuple):
        text, style = value
        return Text(str(text), style=style)
    return Text(str(value))


def key_values(items: Sequence[tuple], *, indent: int = 2,
               label_width: int | None = None,
               truncate: int | None = None) -> None:
    """Print aligned label/value rows.

    On an interactive terminal this is a borderless two-column Rich table;
    everywhere else it keeps the original ``  label  value`` lines.
    """
    rows = [(str(label), value) for label, value in items]
    if truncate is not None:
        rows = [(label, value[: truncate - 3] + "..." if isinstance(value, str)
                 and len(value) > truncate else value) for label, value in rows]
    if not rows:
        return

    if is_interactive():
        table = Table(box=None, show_header=False, pad_edge=False, padding=(0, 2))
        table.add_column(style="nusa.label", no_wrap=True)
        table.add_column()
        for label, value in rows:
            table.add_row(_cell(label), _cell(value))
        console().print(Padding(table, (0, 0, 0, indent)))
        return

    pad = label_width or max(len(label) for label, _ in rows)
    for label, value in rows:
        text = value[0] if isinstance(value, tuple) else value
        print(f"  {paint(label, BOLD):<{pad}} {text}")


def data_table(columns: Sequence[str], rows: Sequence[Sequence], *,
               aligns: Sequence[str] | None = None,
               styles: Sequence[str | None] | None = None,
               no_wrap: Sequence[bool] | None = None,
               overflow: Sequence[str] | None = None,
               header: bool = True, indent: int = 2) -> None:
    """Print a column layout: Rich table interactive, padded text otherwise.

    Plain output never grows a header row; it keeps the legacy shape so pipes
    and scripts still read the same lines.
    """
    if not rows:
        return

    if is_interactive():
        table = Table(box=None, pad_edge=False, padding=(0, 2),
                      header_style="bold cyan")
        for index, column in enumerate(columns):
            table.add_column(
                column,
                justify=(aligns[index] if aligns else "left"),
                style=(styles[index] if styles else None),
                no_wrap=(no_wrap[index] if no_wrap else False),
                overflow=(overflow[index] if overflow else "ellipsis"),
            )
        for row in rows:
            table.add_row(*[_cell(cell) for cell in row])
        console().print(Padding(table, (0, 0, 0, indent)))
        return

    all_rows = ([list(columns)] if header else []) + [list(row) for row in rows]
    widths = [
        max(len(_plain(row[index])) for row in all_rows)
        for index in range(len(columns))
    ]
    for row in rows:
        cells = []
        for index, cell in enumerate(row):
            text = _plain(cell)
            align = aligns[index] if aligns else "left"
            width = widths[index]
            cells.append(text.rjust(width) if align == "right" else text.ljust(width))
        print("  " + "  ".join(cells).rstrip())


def _plain(cell) -> str:
    return str(cell[0]) if isinstance(cell, tuple) else str(cell)


def check_rows(rows: Sequence[tuple[str, str, str, str]]) -> None:
    """Print ``(status, style, label, detail)`` check lines for ``doctor``.

    ``style`` is the Rich style name for the status cell on an interactive
    terminal; plain output maps the status word to the legacy colours instead.
    """
    if is_interactive():
        table = Table(box=None, show_header=False, pad_edge=False, padding=(0, 2))
        table.add_column(no_wrap=True)
        table.add_column(no_wrap=True)
        table.add_column(style="dim")
        for status, style, label, detail in rows:
            table.add_row(Text(f"[{status}]", style=style), _cell(label), _cell(detail))
        console().print(Padding(table, (0, 0, 0, 2)))
        return

    plain_colours = {"PASS": GREEN, "FAIL": RED, "INFO": GREY}
    for status, _style, label, detail in rows:
        mark = paint(status, plain_colours.get(status, GREY))
        print(f"  [{mark}] {label}" + (f" - {detail}" if detail else ""))


def index_summary(stats) -> None:
    """Print the post-index report: a panel interactive, legacy lines otherwise."""
    rows = [
        ("root", stats.root),
        ("scanned", f"{stats.scanned} file(s)"),
        ("indexed", str(stats.files_indexed)),
        ("unchanged", str(stats.files_unchanged)),
        ("removed", str(stats.files_removed)),
        ("chunks", str(stats.chunks)),
        ("duration", f"{stats.duration:.2f}s"),
    ]
    if is_interactive():
        table = Table(box=None, show_header=False, pad_edge=False, padding=(0, 2))
        table.add_column(style="nusa.label", no_wrap=True)
        table.add_column()
        for label, value in rows:
            table.add_row(_cell(label), _cell(value))
        console().print(Panel(Padding(table, (0, 0, 0, 1)),
                              title="Index complete", title_align="left",
                              border_style="nusa.royal", padding=(0, 1)))
        return

    heading("Index complete")
    for label, value in rows:
        print(f"  {label:<9} {value}")


def snippet_panel(title: str, ansi_body: str, *, note: str = "") -> None:
    """A retrieved snippet in a bordered panel, body already ANSI-highlighted."""
    body = Text.from_ansi(ansi_body) if ansi_body else Text("")
    if note:
        body.append("\n" + note, style="dim")
    title_text = Text(title, style="nusa.gold")
    title_text.stylize("italic")
    console().print(Panel(body,
                          title=title_text,
                          title_align="left",
                          border_style="nusa.royal",
                          padding=(0, 1)))


# ---------------------------------------------------------------- progress
class _NullIndexProgress:
    """Non-interactive reporter: indexing stays silent, as it always was."""

    def emit(self, event) -> None:
        return None


class _RichIndexProgress:
    """Maps index events onto a two-phase progress task (scan, then files)."""

    def __init__(self, progress, task) -> None:
        self._progress = progress
        self._task = task

    def emit(self, event) -> None:
        phase = getattr(event, "phase", "")
        if phase == "scan":
            self._progress.update(self._task, description=f"scanning {event.detail}")
        elif phase == "planned":
            self._progress.update(self._task, description="indexing",
                                  total=max(int(event.total), 1))
        elif phase == "file":
            self._progress.update(self._task, advance=1, current=event.detail)


@contextmanager
def index_progress():
    """Yield a reporter for ``ProjectIndex.index(on_event=...)``.

    Only an interactive terminal gets the animated bar; everything else gets a
    no-op reporter, which is what keeps piped output and tests unchanged.
    """
    if not is_interactive():
        yield _NullIndexProgress()
        return

    progress = Progress(
        SpinnerColumn("arc", style="nusa.cyan"),
        TextColumn("[nusa.cyan]{task.description}"),
        TextColumn("[nusa.dim]{task.fields[current]}"),
        BarColumn(complete_style="nusa.cyan", finished_style="nusa.mint"),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console(),
        transient=True,
    )
    with progress:
        task = progress.add_task("scanning", total=None, current="")
        yield _RichIndexProgress(progress, task)


class Spinner:
    """Status animation that starts immediately (FR-15, AC-38).

    Interactive terminals get the Rich star spinner; everywhere else this is a
    silent no-op, exactly like the original implementation.
    """

    def __init__(self, message: str = "Thinking...", interval: float | None = None):
        self.message = message
        self.interval = interval
        self._status = None

    def start(self) -> "Spinner":
        if is_interactive():
            self._status = console().status(
                Text(self.message), spinner="star", spinner_style="nusa.gold"
            )
            self._status.start()
        return self

    def stop(self) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None


@contextmanager
def thinking(message: str = "Thinking..."):
    """Context manager wrapping a slow call with a spinner."""
    spinner = Spinner(message).start()
    try:
        yield spinner
    finally:
        spinner.stop()


# ------------------------------------------------------------------- banner
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


def _emblem_rows() -> tuple:
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    return _EMBLEM if "utf" in encoding else _EMBLEM_ASCII


def _emblem_line(row, star: str | None = None):
    """One emblem row as a Rich ``Text``; ``star`` overrides the star glyph."""
    line = Text()
    for text, colour in row:
        if star is not None and text == "✦":
            text = star
        line.append(text, style=Style(color=f"#{colour[0]:02X}{colour[1]:02X}{colour[2]:02X}")
                    if colour else None)
    return line


def _animated_banner(rows) -> None:
    """Draw the emblem row by row, then twinkle the star once (≈0.5 s)."""
    from rich.live import Live

    def frame(visible: int, star: str | None = None) -> Group:
        return Group(*[_emblem_line(row, star) for row in rows[:visible]])

    live = Live(console=console(), refresh_per_second=30, transient=True)
    live.start()
    try:
        for visible in range(1, len(rows) + 1):
            live.update(frame(visible))
            time.sleep(0.035)
        for glyph in ("✧", "✦", "✧"):
            live.update(frame(len(rows), star=glyph))
            time.sleep(0.06)
    except KeyboardInterrupt:  # pragma: no cover - user skipped the intro
        pass
    finally:
        live.stop()


def banner(animate: bool | None = None) -> None:
    """Print the NUSA-RG emblem: a ribbon N with a small star above it.

    Colours follow BANNER.txt (cyan-blue-turquoise gradient, gold star) and
    are dropped when output is piped, NO_COLOR is set, or --no-colour is
    given; block glyphs fall back to ASCII outside a UTF-8 terminal.

    On an interactive UTF-8 terminal the emblem is drawn with a short intro
    unless ``animate`` is False or ``NUSA_RG_NO_ANIM`` is set.
    """
    rows = _emblem_rows()
    if animate is None:
        animate = (rows is _EMBLEM and is_interactive()
                   and not os.environ.get("NUSA_RG_NO_ANIM"))
    if animate and _RICH:
        _animated_banner(rows)

    for row in rows:
        print("  " + "".join(
            paint(text, _foreground(colour)) if colour else text
            for text, colour in row
        ))


def timestamp() -> str:
    return time.strftime("%H:%M:%S")
