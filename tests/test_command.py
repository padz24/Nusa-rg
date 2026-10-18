"""Tests for the command runner and its RTK integration."""

from __future__ import annotations

import stat
import sys

import pytest

from ragassist import command


# ------------------------------------------------------------------- parsing
def test_split_command_basic():
    assert command.split_command("git status") == ["git", "status"]
    assert command.split_command('grep -n "two words" file') == [
        "grep", "-n", "two words", "file"]


def test_split_command_rejects_shell_operators():
    for text in ("ls | head", "echo hi && pwd", "cat $HOME/.x", "ls > out"):
        with pytest.raises(command.CommandError):
            command.split_command(text)


def test_split_command_rejects_empty_and_unbalanced():
    with pytest.raises(command.CommandError):
        command.split_command("   ")
    with pytest.raises(command.CommandError):
        command.split_command('echo "unclosed')


# ------------------------------------------------------------------ running
def test_run_captures_output_and_exit_code():
    result = command.run([sys.executable, "-c", "print('hello')"], use_rtk=False)
    assert result.ok
    assert result.output.strip() == "hello"
    assert result.used_rtk is False
    assert result.truncated is False


def test_run_merges_stderr_and_keeps_the_exit_code():
    script = "import sys; sys.stderr.write('boom\\n'); sys.exit(3)"
    result = command.run([sys.executable, "-c", script], use_rtk=False)
    assert result.exit_code == 3
    assert not result.ok
    assert "[stderr]" in result.output and "boom" in result.output


def test_run_missing_binary_is_actionable():
    with pytest.raises(command.CommandError) as exc:
        command.run(["definitely-not-here-xyz"], use_rtk=False)
    assert "not found" in str(exc.value)


def test_run_timeout_is_actionable():
    script = "import time; time.sleep(5)"
    with pytest.raises(command.CommandError) as exc:
        command.run([sys.executable, "-c", script], timeout=0.3, use_rtk=False)
    assert "did not finish" in str(exc.value)
    assert "command_timeout" in str(exc.value)


def test_run_truncates_large_output_keeping_both_ends():
    script = "print('A' * 3000); print('B' * 3000)"
    result = command.run([sys.executable, "-c", script], limit=1000, use_rtk=False)
    assert result.truncated is True
    assert "output truncated" in result.output
    assert result.output.startswith("A")
    assert result.output.endswith("B")


# ---------------------------------------------------------------------- rtk
def _fake_rtk(tmp_path):
    script = tmp_path / "rtk"
    script.write_text("#!/bin/sh\necho \"[rtk] $@\"\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_run_routes_through_rtk_when_available(monkeypatch, tmp_path):
    monkeypatch.setattr(command, "rtk_path", lambda: str(_fake_rtk(tmp_path)))
    result = command.run(["echo", "hi"], use_rtk=True)
    assert result.used_rtk is True
    assert result.output.strip() == "[rtk] echo hi"


def test_run_can_bypass_rtk(monkeypatch, tmp_path):
    monkeypatch.setattr(command, "rtk_path", lambda: str(_fake_rtk(tmp_path)))
    result = command.run(["echo", "hi"], use_rtk=False)
    assert result.used_rtk is False
    assert result.output.strip() == "hi"


def test_rtk_version_reports_none_when_missing(monkeypatch):
    monkeypatch.setattr(command, "rtk_path", lambda: None)
    assert command.rtk_version() is None


def test_rtk_version_reads_the_binary(monkeypatch, tmp_path):
    script = tmp_path / "rtk"
    script.write_text("#!/bin/sh\necho 'rtk 1.2.3'\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(command, "rtk_path", lambda: str(script))
    assert command.rtk_version() == "rtk 1.2.3"


# ---------------------------------------------------------------- prompt view
def test_for_prompt_includes_command_status_and_trims():
    result = command.CommandResult(
        argv=["pytest"], display="pytest", exit_code=1,
        output="x" * 9000, duration=0.1,
    )
    block = result.for_prompt(max_chars=400)
    assert block.startswith("$ pytest\n")
    assert "output trimmed for the prompt" in block
    assert block.endswith("[exit 1]")
    assert len(block) < 600


def test_summary_mentions_rtk():
    result = command.CommandResult(
        argv=["git"], display="git", exit_code=0, output="", duration=0.5,
        used_rtk=True,
    )
    assert "rtk" in result.summary()
