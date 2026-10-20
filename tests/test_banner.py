"""Tests for the banner, the status chips, and the chat chrome."""

from __future__ import annotations

import re
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
    branch="main",
    index="1,284 chunks · 2m ago",
    model="beam",
    rtk="on",
)

ANSI = re.compile(r"\x1b\[[0-9;]*m")


@pytest.fixture(autouse=True)
def restore_colour():
    """Each test starts plain; banner() must never leak a colour toggle."""
    previous = ui._COLOUR
    ui.set_colour(False)
    yield
    ui.set_colour(previous)


@pytest.fixture(autouse=True)
def wide_terminal(monkeypatch):
    """Pin the terminal width so the wide/narrow choice is deterministic."""
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setenv("LINES", "40")


def _lines(capsys):
    return capsys.readouterr().out.rstrip("\n").splitlines()


def _plain_lines(capsys):
    """Visible text per line, with the ANSI colours removed."""
    out = capsys.readouterr().out
    return [ANSI.sub("", line).rstrip() for line in out.rstrip("\n").splitlines()]


# ---------------------------------------------------------------- plain layout
def test_plain_output_has_no_logo_or_escape_codes(capsys):
    """NO_COLOR/non-TTY: plain identity lines, no emblem, no ANSI."""
    ui.banner(FACTS)
    out = capsys.readouterr().out

    assert "\033[" not in out
    assert "█" not in out
    assert out.rstrip("\n").splitlines() == [
        "  nusa-rg v1.3.0",
        "  ask your codebase",
        "  ~/projects/my-app · main",
        "",
        "  index 1,284 chunks · 2m ago  model beam  rtk on",
    ]


# ----------------------------------------------------------------- logo layout
def test_logo_banner_matches_the_reference_rows(capsys):
    ui.set_colour(True)
    ui.banner(FACTS)
    lines = _plain_lines(capsys)

    assert len(lines) == 7
    assert lines[0] == "  ███    ██"
    assert lines[1] == "  ████   ██  nusa-rg v1.3.0"
    assert lines[2] == "  ██ ██  ██  ask your codebase"
    assert lines[3] == "  ██  ██ ██  ~/projects/my-app · main"
    assert lines[4] == "  ██   ████"
    assert lines[5] == ""
    assert "index 1,284 chunks" in lines[6]
    assert "model beam" in lines[6]
    assert "rtk on" in lines[6]


def test_logo_rows_use_the_reference_colours(capsys, monkeypatch):
    monkeypatch.setenv("COLORTERM", "truecolor")
    ui.set_colour(True)
    ui.banner(FACTS)
    lines = capsys.readouterr().out.splitlines()

    assert "\033[38;2;56;182;255m" in lines[0]   # #38b6ff
    assert "\033[38;2;47;208;192m" in lines[0]   # #2fd0c0 right stroke
    assert "\033[38;2;58;165;240m" in lines[1]   # #3aa5f0 diagonal
    assert "\033[38;2;59;143;224m" in lines[2]   # #3b8fe0
    assert "\033[38;2;47;111;208m" in lines[3]   # #2f6fd0
    assert "\033[38;2;34;80;176m" in lines[4]    # #2250b0
    assert lines[2].count("\033[38;2;59;143;224m") == 2  # left + middle
    assert "\033[38;2;59;143;224m" in lines[4]   # bottom bar


def test_chips_colour_ready_and_empty_states(capsys, monkeypatch):
    monkeypatch.setenv("COLORTERM", "truecolor")
    ui.set_colour(True)

    ui.banner(replace(FACTS, index="empty", rtk="off"))
    out = capsys.readouterr().out
    assert "index empty" in out and "rtk off" in out
    assert "\033[48;2;74;58;18m" in out    # #4a3a12 background
    assert "\033[38;2;245;185;66m" in out  # #f5b942 text
    assert "\033[48;2;34;44;50m" in out    # rtk off background

    ui.banner(FACTS)
    out = capsys.readouterr().out
    assert "\033[48;2;18;61;42m" in out    # index ready background
    assert "\033[38;2;74;222;128m" in out  # index ready text
    assert "\033[48;2;23;58;99m" in out    # model background
    assert "\033[48;2;15;61;58m" in out    # rtk on background


def test_branch_is_hidden_when_the_checkout_has_none(capsys):
    ui.banner(replace(FACTS, branch=""))
    lines = _plain_lines(capsys)

    assert lines[2] == "  ~/projects/my-app"
    assert "my-app ·" not in "\n".join(lines)


# -------------------------------------------------------------- narrow layout
def test_narrow_terminal_keeps_only_the_name_and_chips(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "39")
    ui.set_colour(True)
    ui.banner(FACTS)
    lines = _plain_lines(capsys)

    assert lines[0] == "  nusa-rg v1.3.0"
    assert "█" not in "\n".join(lines)
    rest = "\n".join(lines[1:])
    assert "index 1,284 chunks" in rest
    assert "model beam" in rest
    assert "rtk on" in rest
    assert "ask your codebase" not in rest
    assert "~/projects/my-app" not in rest


def test_long_project_is_middle_truncated_to_the_terminal(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "40")
    ui.set_colour(True)
    deep = "~/projects/company/monorepo/services/web/frontend"
    ui.banner(replace(FACTS, project=deep))
    lines = _plain_lines(capsys)

    assert all(len(line) <= 40 for line in lines)
    assert "…" in "\n".join(lines)


# --------------------------------------------------------------------- colour
def test_banner_falls_back_to_256_colours(capsys, monkeypatch):
    monkeypatch.delenv("COLORTERM", raising=False)
    ui.set_colour(True)
    ui.banner(FACTS)
    out = capsys.readouterr().out

    assert "\033[38;5;" in out
    assert "\033[48;5;" in out
    assert "\033[0m" in out, "every coloured span resets"


# ---------------------------------------------------------------------- ASCII
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
    monkeypatch.setenv("COLORTERM", "truecolor")
    ui.set_colour(True)
    fake = _ascii_stdout(monkeypatch)
    ui.banner(FACTS)
    out = ANSI.sub("", "".join(fake.written))

    assert "###    ##" in out, "the logo is drawn with # cells"
    assert "nusa-rg v1.3.0" in out
    assert "~/projects/my-app * main" in out
    assert "█" not in out and "·" not in out


# ---------------------------------------------------------------- chat chrome
def test_chat_hints_are_plain_without_colour(capsys):
    ui.chat_hints(index_empty=True)
    assert _lines(capsys) == [
        "/exit keluar  /help perintah",
        "index kosong, jalankan:",
        "  nusa-rg index <path>",
    ]


def test_chat_hints_use_teal_bold_and_yellow(capsys, monkeypatch):
    monkeypatch.setenv("COLORTERM", "truecolor")
    ui.set_colour(True)
    ui.chat_hints(index_empty=True)
    out = capsys.readouterr().out
    first = out.splitlines()[0]

    assert "\033[38;2;47;208;192m\033[1m/exit\033[0m" in first
    assert "\033[38;2;47;208;192m\033[1m/help\033[0m" in first
    assert "\033[38;2;108;125;134m keluar\033[0m" in first
    assert "\033[38;2;245;185;66mindex kosong, jalankan:\033[0m" in out
    assert "\033[38;2;47;208;192m  nusa-rg index <path>\033[0m" in out


def test_chat_hints_omit_the_index_nudge_when_ready(capsys):
    ui.chat_hints()
    assert "index kosong" not in capsys.readouterr().out


def test_prompt_glyphs_are_plain_without_colour():
    ui.set_colour(False)
    assert ui.user_prompt() == "❯ "
    assert ui.assistant_prompt() == "◆ "


def test_prompt_glyphs_use_green_and_purple(monkeypatch):
    monkeypatch.setenv("COLORTERM", "truecolor")
    ui.set_colour(True)
    assert ui.user_prompt() == "\033[38;2;74;222;128m\033[1m❯ \033[0m"
    assert ui.assistant_prompt() == "\033[38;2;139;140;246m\033[1m◆ \033[0m"


def test_footer_shows_duration_and_total_tokens(capsys):
    ui.footer(0.0, 168)
    assert capsys.readouterr().out == "  0.00s · 168 tok\n"


def test_footer_is_dim(capsys, monkeypatch):
    monkeypatch.setenv("COLORTERM", "truecolor")
    ui.set_colour(True)
    ui.footer(1.25, 42)
    assert capsys.readouterr().out == (
        "\033[38;2;108;125;134m  1.25s · 42 tok\033[0m\n"
    )


def test_banner_returns_the_facts_it_drew(capsys):
    assert ui.banner(FACTS) is FACTS
    capsys.readouterr()


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
    assert facts.branch == "", "a directory outside git has no branch"
    assert facts.index == "empty"
    assert facts.index_ready is False
    assert facts.model == "demo-model"
    assert facts.rtk in ("on", "off")


def test_collect_reports_the_index_size_and_age(sample_project):
    result = CliRunner().invoke(main, ["index", str(sample_project)])
    assert result.exit_code == 0, result.output

    facts = collect()

    assert facts.project == _shorten(str(sample_project))
    assert facts.branch == ""
    assert facts.index.endswith("just now")
    assert facts.index.split(" · ")[0].endswith("chunks")
    assert facts.index_ready is True
