"""Tests for the banner status card and the runtime facts behind it."""

from __future__ import annotations

import sys
from dataclasses import replace

import pytest
from click.testing import CliRunner

from nusa_rg import __version__, ui
from nusa_rg.banner import Facts, _ago, _shorten, collect
from nusa_rg.cli import main
from nusa_rg.config import Config

FACTS = Facts(
    version="1.3.0",
    project="~/projects/my-app",
    branch="main · 3 changed",
    index="1,284 chunks · 2m ago",
    model="deepseek-chat",
    rtk="on",
)


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


def _lines(capsys):
    return capsys.readouterr().out.rstrip("\n").splitlines()


# ---------------------------------------------------------------- wide layout
def test_wide_banner_draws_the_pixel_n_beside_the_card(capsys):
    ui.banner(FACTS)
    lines = _lines(capsys)

    assert len(lines) == 7
    assert lines[0].startswith("  ███    ██"), "the blocky N opens the banner"
    assert "╭─ nusa-rg v1.3.0 " in lines[0], "the title sits on the top border"


def test_wide_banner_lists_every_runtime_fact(capsys):
    ui.banner(FACTS)
    out = capsys.readouterr().out

    assert "project  ~/projects/my-app" in out
    assert "branch   main · 3 changed" in out
    assert "index    1,284 chunks · 2m ago" in out
    assert "model    deepseek-chat" in out
    assert "rtk      on" in out


def test_wide_banner_is_54_columns_wide(capsys):
    ui.banner(FACTS)
    lines = _lines(capsys)

    assert max(len(line) for line in lines) == 54
    assert lines[-1].endswith("╰" + "─" * 38 + "╯")


# -------------------------------------------------------------- narrow layout
def test_narrow_terminal_shows_the_card_on_its_own(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "44")
    ui.banner(FACTS)
    out = capsys.readouterr().out
    lines = out.rstrip("\n").splitlines()

    assert "█" not in out, "the pixel N is dropped when it cannot fit"
    assert lines[0].startswith("  ╭─ nusa-rg v1.3.0 ")
    assert "index    1,284 chunks · 2m ago" in out
    assert max(len(line) for line in lines) == 42


def test_long_values_are_truncated_to_the_terminal(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "44")
    deep = "~/projects/company/monorepo/services/web/frontend"
    ui.banner(replace(FACTS, project=deep))

    lines = _lines(capsys)
    assert all(len(line) <= 44 for line in lines)
    assert "…" in "\n".join(lines), "overlong values are middle-truncated"


# --------------------------------------------------------------------- colour
def test_banner_drops_colour_when_disabled(capsys):
    ui.set_colour(False)
    ui.banner(FACTS)
    assert "\033[" not in capsys.readouterr().out


def test_banner_uses_the_palette_when_colour_is_on(capsys):
    ui.set_colour(True)
    ui.banner(FACTS)
    out = capsys.readouterr().out

    # truecolor or the 256-colour fallback: both are 38;[25] foreground codes.
    assert "\033[38;" in out
    assert "\033[0m" in out, "every coloured span resets so the terminal is clean"


# --------------------------------------------------------------- ASCII output
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
    ui.banner(FACTS)
    out = "".join(fake.written)

    assert "###    ##" in out, "the pixel N is drawn with # cells"
    assert "+- nusa-rg v1.3.0" in out
    assert "| project  ~/projects/my-app" in out
    assert "·" not in out and "█" not in out and "╭" not in out


def test_ascii_fallback_keeps_the_card_alone_when_narrow(monkeypatch):
    fake = _ascii_stdout(monkeypatch)
    monkeypatch.setenv("COLUMNS", "44")
    ui.banner(FACTS)
    out = "".join(fake.written)

    assert "| project  ~/projects/my-app" in out
    assert "main * 3 changed" in out, "the middle dot degrades to a star"
    assert "█" not in out and "#" not in out


# --------------------------------------------------------------------- facts
def test_shorten_collapses_the_home_prefix():
    from pathlib import Path

    home = str(Path.home())
    assert _shorten(home) == "~"
    assert _shorten(home + "/projects/app") == "~/projects/app"
    assert _shorten("/opt/data") == "/opt/data"


def test_ago_formats_minutes_hours_and_days():
    assert _ago(5) == "just now"
    assert _ago(120) == "2m ago"
    assert _ago(2 * 3600) == "2h ago"
    assert _ago(3 * 86400) == "3d ago"


def test_collect_reads_config_and_an_empty_index(tmp_path):
    settings = Config()
    settings.set("api_model", "demo-model")
    settings.set("default_project_path", str(tmp_path))

    facts = collect()

    assert facts.version == __version__
    assert facts.project == _shorten(str(tmp_path))
    assert facts.branch == "—", "a directory outside git has no branch"
    assert facts.index == "empty"
    assert facts.model == "demo-model"
    assert facts.rtk in ("on", "off")


def test_collect_reports_the_index_size_and_age(sample_project):
    result = CliRunner().invoke(main, ["index", str(sample_project)])
    assert result.exit_code == 0, result.output

    facts = collect()

    assert facts.project == _shorten(str(sample_project))
    assert facts.index.endswith("just now")
    assert facts.index.split(" · ")[0].endswith("chunks")
