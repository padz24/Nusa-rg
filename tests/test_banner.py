"""Tests for the NUSA-RG banner (pixel N, wordmark, tagline, status row)."""

from __future__ import annotations

import sys

import pytest

from nusa_rg import ui


@pytest.fixture(autouse=True)
def restore_colour():
    """banner() must never leak a colour toggle into other tests."""
    previous = ui._COLOUR
    yield
    ui.set_colour(previous)


@pytest.fixture(autouse=True)
def wide_terminal(monkeypatch):
    """Pin the terminal width so the wide/narrow choice is deterministic."""
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setenv("LINES", "40")


def test_wide_banner_draws_the_pixel_n_beside_the_wordmark(capsys):
    ui.banner()
    lines = capsys.readouterr().out.rstrip("\n").splitlines()

    assert len(lines) == 10
    assert lines[0].startswith("  ████  ██"), "the blocky N opens the banner"
    assert "│" in lines[0], "a separator bar sits between emblem and wordmark"
    assert "█  █ █  █ ████" in lines[0], "NUSA-RG is drawn in pixel glyphs"


def test_wide_banner_prints_tagline_rule_and_status(capsys):
    ui.banner()
    out = capsys.readouterr().out

    assert "LOCAL PROJECT RAG  •  CODING ASSISTANT" in out
    assert "─" * 42 in out, "a rule separates the tagline from the status row"
    assert "─ [ PROJECT CONTEXT • LOCAL AI • READY ] ─" in out
    assert "✦" not in out, "the old star emblem is gone"


def test_wide_banner_is_57_columns_wide(capsys):
    ui.banner()
    lines = capsys.readouterr().out.rstrip("\n").splitlines()

    assert max(len(line) for line in lines) == 57


def test_narrow_terminal_gets_the_wordmark_block(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "44")
    ui.banner()
    out = capsys.readouterr().out
    lines = out.rstrip("\n").splitlines()

    assert "│" not in out, "the separator only exists in the wide layout"
    assert lines[0].startswith("  █  █"), "the wordmark opens the narrow layout"
    assert "LOCAL PROJECT RAG  •  CODING ASSISTANT" in out
    assert max(len(line) for line in lines) == 44


def test_banner_drops_colour_when_disabled(capsys):
    ui.set_colour(False)
    ui.banner()
    assert "\033[" not in capsys.readouterr().out


def test_banner_uses_the_palette_when_colour_is_on(capsys):
    ui.set_colour(True)
    ui.banner()
    out = capsys.readouterr().out

    # truecolor or the 256-colour fallback: both are 38;[25] foreground codes.
    assert "\033[38;" in out
    assert "\033[0m" in out, "every coloured span resets so the terminal is clean"


def _ascii_stdout(monkeypatch):
    class FakeStdout:
        encoding = "ascii"

        def __init__(self):
            self.written: list[str] = []

        def write(self, text):
            self.written.append(text)

        def flush(self):
            pass

    fake = FakeStdout()
    monkeypatch.setattr(sys, "stdout", fake)
    return fake


def test_banner_falls_back_to_ascii_outside_utf8(monkeypatch):
    fake = _ascii_stdout(monkeypatch)
    ui.banner()
    out = "".join(fake.written)

    assert "####  ##" in out, "the pixel N is drawn with # cells"
    assert "|" in out and "│" not in out
    assert "LOCAL PROJECT RAG  *  CODING ASSISTANT" in out
    assert "- [ PROJECT CONTEXT * LOCAL AI * READY ] -" in out
    assert "✦" not in out and "█" not in out


def test_ascii_fallback_stays_ascii_when_narrow(monkeypatch):
    fake = _ascii_stdout(monkeypatch)
    monkeypatch.setenv("COLUMNS", "44")
    ui.banner()
    out = "".join(fake.written)

    assert "|" not in out, "no separator in the narrow layout"
    assert "*" in out and "█" not in out
