"""Live presentation of a streamed (SSE) answer: the terminal side of streaming.

A turn streams when ``CoreEngine.ask`` accepts two optional keywords:

    on_retrieval(result)  once, right after retrieval and before the model is
                          called, so the context snippets still come first
    on_token(text)        for every text delta the provider streams

:func:`supports_live` checks for both, so an engine without them keeps its
classic spinner-then-answer behaviour. Engine side, in short::

    retrieval = self._retrieve(message)
    if on_retrieval:
        on_retrieval(retrieval)
    ...
    result = collect(stream_chat(url, payload, headers=headers), on_token)

:class:`LiveTurn` owns the terminal while the tokens arrive: the spinner covers
the wait, gives way to the text on the first token, and when the turn is over the
raw text is replaced in place by its Markdown rendering if it all fits on screen.
"""
from __future__ import annotations

import inspect
import os
import re
import shutil
import sys
import unicodedata
from typing import Any, Callable

from . import ui

HOOKS = ("on_retrieval", "on_token")

_ANSI = re.compile(r"\033\[[0-9;?]*[A-Za-z]")
# Model output is untrusted: escape sequences and other control characters are
# dropped (newline and tab stay) before anything reaches the terminal.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def supports_live(engine: Any) -> bool:
    """True when ``engine.ask`` accepts both live hooks."""
    try:
        params = inspect.signature(engine.ask).parameters
    except (TypeError, ValueError):
        return False
    return all(name in params for name in HOOKS)


def _cells(line: str) -> int | None:
    """Columns ``line`` occupies, or None when a character's width is uncertain."""
    total = 0
    for char in line:
        if unicodedata.east_asian_width(char) in ("W", "F"):
            return None
        if unicodedata.category(char) in ("Mn", "Me", "Cf"):  # zero-width marks
            continue
        total += 1
    return total


def _rows(text: str, columns: int) -> int | None:
    """Terminal rows ``text`` takes when printed from column 0 (None if unsure)."""
    columns = max(1, columns)
    rows = 0
    for line in text.expandtabs(8).split("\n"):
        cells = _cells(line)
        if cells is None:
            return None
        rows += max(1, -(-cells // columns))
    return rows


class LiveTurn:
    """Owns the terminal while one answer streams in."""

    def __init__(self, *, show_retrieval: Callable[[Any], None],
                 emit: Callable[..., None], plain: bool = False,
                 markdown: bool = True, lead: str = "", gap: bool = False) -> None:
        self._show_retrieval = show_retrieval
        self._emit = emit
        self._plain = plain
        self._markdown = markdown
        self._lead = lead
        self._gap = gap
        self._spinner: Any = None
        self._parts: list[str] = []
        self._closed = False
        self.started = False          # the first token has been printed
        self.retrieval_shown = False  # on_retrieval already printed the snippets

    def attach(self, spinner: Any) -> None:
        """Take over the spinner that covers the wait for the first token."""
        self._spinner = spinner

    def hooks(self, engine: Any) -> dict[str, Callable[..., None]]:
        """The keywords to pass to ``engine.ask`` (only the ones it accepts)."""
        params = inspect.signature(engine.ask).parameters
        wanted = {"on_retrieval": self.on_retrieval, "on_token": self.on_token}
        return {name: hook for name, hook in wanted.items() if name in params}

    def on_retrieval(self, result: Any) -> None:
        """Print the context snippets before the model is called."""
        if not getattr(result, "snippets", None):
            return
        self._stop_spinner()
        self._show_retrieval(result)
        self.retrieval_shown = True
        self._spinner = ui.Spinner("Menimbang jawaban").start()

    def on_token(self, text: str) -> None:
        """Print one streamed delta; the first one replaces the spinner."""
        text = _CONTROL.sub("", text)
        if not text:
            return
        if not self.started:
            self._stop_spinner()
            self.started = True
            if self._gap:
                print()
            sys.stdout.write(self._lead)
        self._parts.append(text)
        sys.stdout.write(text)
        sys.stdout.flush()

    def finish(self, answer: str) -> bool:
        """End the live block; False when no token streamed (print the answer yourself)."""
        self._stop_spinner()
        self._closed = True
        if not self.started:
            return False
        streamed = "".join(self._parts)
        if not self._redraw(streamed, answer) and not streamed.endswith("\n"):
            print()
        return True

    def abort(self) -> None:
        """Leave the terminal tidy after an error or Ctrl+C."""
        if self._closed:
            return
        self._closed = True
        self._stop_spinner()
        if self.started and not "".join(self._parts).endswith("\n"):
            print()

    def _stop_spinner(self) -> None:
        if self._spinner is not None:
            self._spinner.stop()
            self._spinner = None

    def _redraw(self, streamed: str, answer: str) -> bool:
        """Swap the raw stream for its Markdown rendering when it all fits on screen."""
        if (self._plain or not self._markdown or not sys.stdout.isatty()
                or os.environ.get("TERM", "") in ("", "dumb")):
            return False
        size = shutil.get_terminal_size((80, 24))
        rows = _rows(_ANSI.sub("", self._lead) + streamed, size.columns)
        if rows is None or rows >= size.lines:
            return False  # scrolled off screen, or widths we cannot count safely
        up = rows - 1
        sys.stdout.write("\r" + (f"\033[{up}A" if up else "") + "\033[J")
        sys.stdout.flush()
        answer = _CONTROL.sub("", answer)  # the final text is as untrusted as the stream
        self._emit(answer, plain=self._plain, markdown=self._markdown, lead=self._lead)
        return True
