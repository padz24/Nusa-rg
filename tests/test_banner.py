"""Tests for the NUSA-RG banner emblem (letter N, star above, orbit below)."""

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


def test_banner_shows_a_star_above_the_letter_n(capsys):
    ui.banner()
    lines = capsys.readouterr().out.rstrip("\n").splitlines()

    assert "✦" in lines[0], "a small star sits above the emblem"
    assert "█" in "\n".join(lines[1:-1]), "the letter N is drawn below the star"
    assert "╰" in lines[-1] and "╯" in lines[-1], "an orbit arc closes the emblem"


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


def test_banner_falls_back_to_ascii_outside_utf8(monkeypatch):
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
    ui.banner()
    out = "".join(fake.written)

    assert "*" in out
    assert "✦" not in out and "█" not in out
    assert "\\-------/" in out, "orbit survives in the ASCII emblem"


def _fake_console(monkeypatch):
    """Capture Rich output without touching a terminal."""
    import io

    from rich.console import Console

    buffer = io.StringIO()
    monkeypatch.setattr(
        ui, "console",
        lambda *, stderr=False: Console(file=buffer, force_terminal=True, width=40))
    return buffer


def test_banner_animates_once_when_interactive(monkeypatch, capsys):
    buffer = _fake_console(monkeypatch)
    monkeypatch.setattr(ui, "is_interactive", lambda: True)
    monkeypatch.delenv("NUSA_RG_NO_ANIM", raising=False)

    ui.banner()

    frames = buffer.getvalue()
    assert "\033[?25l" in frames, "the intro hides the cursor while it draws"
    assert "✦" in frames or "✧" in frames, "the star twinkles during the reveal"
    assert "✦" in capsys.readouterr().out, "the settled banner is printed after"


def test_banner_skips_the_intro_when_animation_is_disabled(monkeypatch, capsys):
    buffer = _fake_console(monkeypatch)
    monkeypatch.setattr(ui, "is_interactive", lambda: True)
    monkeypatch.setenv("NUSA_RG_NO_ANIM", "1")

    ui.banner()

    assert buffer.getvalue() == "", "no frames when the intro is disabled"
    assert "✦" in capsys.readouterr().out


def test_ascii_emblem_never_animates(monkeypatch):
    buffer = _fake_console(monkeypatch)

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
    monkeypatch.setattr(ui, "is_interactive", lambda: True)

    ui.banner()

    out = "".join(fake.written)
    assert "✦" not in out
    assert buffer.getvalue() == "", "the ASCII emblem cannot twinkle"
