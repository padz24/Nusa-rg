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
