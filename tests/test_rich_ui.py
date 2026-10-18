"""Tests for the Rich presentation layer (FR-17).

The interactive helpers live behind ``ui.is_interactive()``; these tests force
that flag and inject a console so the Rich output can be inspected as text.
"""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from nusa_rg import ui


def _stats(**overrides):
    values = dict(root="/tmp/project", scanned=3, files_indexed=2,
                  files_unchanged=1, files_removed=0, chunks=12, duration=0.42)
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def rich_console(monkeypatch):
    """Force the interactive paths and capture what they draw."""
    from rich.console import Console

    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=True, width=64, theme=ui.THEME)
    monkeypatch.setattr(ui, "is_interactive", lambda: True)
    monkeypatch.setattr(ui, "console", lambda *, stderr=False: console)
    return buffer


# ------------------------------------------------------------- key/value rows
def test_key_values_plain_keeps_the_legacy_shape(capsys):
    ui.key_values([("provider", "openai"), ("api key", "set")], label_width=10)
    out = capsys.readouterr().out

    assert out.startswith("  provider"), "plain output keeps the two-space indent"
    assert "openai" in out
    assert "\033[" not in out


def test_key_values_rich_uses_a_table(rich_console):
    ui.key_values([("provider", "openai"), ("api key", "set")], label_width=10)
    out = rich_console.getvalue()

    assert "provider" in out and "openai" in out
    assert "\033[" in out


def test_key_values_renders_int_values(capsys):
    ui.key_values([("models", 12)])
    assert "12" in capsys.readouterr().out


def test_key_values_truncates_long_strings(capsys):
    ui.key_values([("system_prompt", "x" * 100)], truncate=72)
    out = capsys.readouterr().out

    assert "x" * 69 + "..." in out
    assert "x" * 72 not in out


# ------------------------------------------------------------------ data rows
def test_data_table_plain_prints_no_header(capsys):
    ui.data_table(["name", "count"], [["alpha", "3"]])
    lines = capsys.readouterr().out.splitlines()

    assert lines[0].startswith("  alpha")
    assert "name" not in lines[0]


def test_data_table_rich_shows_the_header(rich_console):
    ui.data_table(["id", "models"], [[("deepseek", "bold"), "12"]],
                  aligns=["left", "right"])
    out = rich_console.getvalue()

    assert "id" in out and "models" in out and "deepseek" in out


# --------------------------------------------------------------- index report
def test_index_summary_plain_matches_the_old_report(capsys):
    ui.index_summary(_stats())
    out = capsys.readouterr().out

    assert "Index complete" in out
    assert "  root      /tmp/project" in out
    assert "  duration  0.42s" in out


def test_index_summary_rich_draws_a_panel(rich_console):
    ui.index_summary(_stats())
    out = rich_console.getvalue()

    assert "Index complete" in out
    assert "╭" in out and "╰" in out


# ------------------------------------------------------------ snippet panels
def test_snippet_panel_keeps_the_highlighted_body(rich_console):
    ui.snippet_panel("context auth.py:1-3", "\x1b[34mdef\x1b[0m f():",
                     note="... (+2 more lines)")
    out = rich_console.getvalue()

    assert "context auth.py:1-3" in out
    assert "def f():" in out
    assert "+2 more lines" in out
    assert "╭" in out


# ----------------------------------------------------------- spinner/progress
def test_spinner_is_silent_without_an_interactive_terminal(capsys, monkeypatch):
    monkeypatch.setattr(ui, "is_interactive", lambda: False)
    spinner = ui.Spinner().start()
    spinner.stop()

    assert capsys.readouterr().out == ""


def test_index_progress_is_silent_without_an_interactive_terminal(capsys, monkeypatch):
    monkeypatch.setattr(ui, "is_interactive", lambda: False)
    with ui.index_progress() as reporter:
        reporter.emit(SimpleNamespace(phase="scan", done=0, total=0, detail="/tmp"))
        reporter.emit(SimpleNamespace(phase="file", done=1, total=2, detail="main.py"))

    assert capsys.readouterr().out == ""


def test_index_progress_drives_the_bar_when_interactive(rich_console):
    with ui.index_progress() as reporter:
        reporter.emit(SimpleNamespace(phase="scan", done=0, total=0,
                                      detail="/tmp/project"))
        reporter.emit(SimpleNamespace(phase="planned", done=0, total=3))
        reporter.emit(SimpleNamespace(phase="file", done=1, total=3,
                                      detail="main.py"))
    out = rich_console.getvalue()

    # The opening frame is drawn by ``with progress``, the closing one by stop;
    # the refresh thread may coalesce anything in between, so only assert the
    # states that are guaranteed to render.
    assert "scanning" in out, "the bar opens in the scan phase"
    assert "indexing main.py" in out, "file events drive the bar"
    assert "1/3" in out


def test_progress_reporter_maps_events_onto_the_bar():
    calls: list[dict] = []

    class StubProgress:
        def update(self, task, **fields):
            calls.append(fields)

    reporter = ui._RichIndexProgress(StubProgress(), "task")
    reporter.emit(SimpleNamespace(phase="scan", done=0, total=0, detail="/tmp/p"))
    reporter.emit(SimpleNamespace(phase="planned", done=0, total=3))
    reporter.emit(SimpleNamespace(phase="file", done=1, total=3, detail="main.py"))
    reporter.emit(SimpleNamespace(phase="done"))

    assert calls == [
        {"description": "scanning /tmp/p"},
        {"description": "indexing", "total": 3},
        {"advance": 1, "current": "main.py"},
    ], "done has nothing left to draw"


# --------------------------------------------------------------------- errors
def test_error_becomes_a_panel_when_interactive(rich_console):
    ui.error("boom")
    out = rich_console.getvalue()

    assert "error:" in out and "boom" in out


def test_error_plain_output_is_unchanged(capsys, monkeypatch):
    monkeypatch.setattr(ui, "is_interactive", lambda: False)
    ui.error("boom")
    captured = capsys.readouterr()

    assert captured.err == "error: boom\n"
    assert captured.out == ""
