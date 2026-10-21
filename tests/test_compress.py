"""The built-in command output compressor, the fallback for a broken rtk."""

from __future__ import annotations

import os
import stat
import sys

import pytest

from nusa_rg import command, compress


# ------------------------------------------------------------------- rules
def test_pip_output_becomes_the_installed_packages():
    output = (
        "Collecting cryptography\n"
        "Downloading cryptography-43.0.1-cp39-abi3.whl (4.1 MB)\n"
        "Requirement already satisfied: requests in /usr/lib/python3.12\n"
        "Building wheel for cryptography (setup.py) ... done\n"
        "Created wheel for cryptography: size=3.7MB\n"
        "Successfully installed cryptography-43.0.1\n"
    )

    result = compress.compress(output, ["pip", "install", "cryptography"])

    assert "installed 1 package(s): cryptography-43.0.1" in result
    assert "Downloading" not in result
    assert "Requirement already satisfied" not in result
    assert result.startswith("[output compressed: 6 lines -> 1]")


def test_pytest_output_keeps_the_failures_and_the_summary():
    output = (
        "============================= test session starts ==============================\n"
        "collected 12 items\n"
        "src/test_a.py ..F....F......                                     [ 66%]\n"
        "src/test_b.py ......                                             [100%]\n"
        "=========================== short test summary info ============================\n"
        "FAILED src/test_a.py::test_one - AssertionError: expected 3\n"
        "FAILED src/test_a.py::test_two - AssertionError: expected 4\n"
        "========================= 2 failed, 10 passed in 1.42s ==========================\n"
    )

    result = compress.compress(output, ["pytest", "-q"])

    assert "2 failed, 10 passed in 1.42s" in result
    assert "FAILED src/test_a.py::test_one" in result
    assert "collected 12 items" not in result
    assert "short test summary info" not in result


def test_npm_output_keeps_the_added_line():
    output = (
        "npm warn deprecated left-pad@1.3.0: use String.prototype.padStart\n"
        "added 120 packages, and audited 121 packages in 4s\n"
    )

    result = compress.compress(output, ["npm", "install"])

    assert "added 120 packages" in result
    assert "npm warn deprecated" not in result


def test_cargo_output_counts_the_compiled_crates():
    output = (
        "   Compiling serde v1.0.197\n"
        "   Compiling tokio v1.35.0\n"
        "    Finished dev [unoptimized + debuginfo] target(s) in 42.13s\n"
    )

    result = compress.compress(output, ["cargo", "build"])

    assert "compiled 2 crate(s)" in result
    assert "Finished dev" in result


def test_generic_output_drops_progress_lines_and_repeats():
    output = (
        "Downloading package one\n"
        "Downloading package two\n"
        "same line\n"
        "same line\n"
        "the result is 42\n"
    )

    result = compress.compress(output, ["some-tool"])

    assert "the result is 42" in result
    assert "Downloading" not in result
    assert result.count("same line") == 1


def test_short_output_is_returned_unchanged():
    output = "all good\n"

    assert compress.compress(output, ["ls"]) == output


def test_empty_output_stays_empty():
    assert compress.compress("", ["ls"]) == ""


def test_the_note_says_how_much_was_dropped():
    output = "\n".join(f"noise {number}" for number in range(30))

    result = compress.compress(output, ["noisy"])

    assert result.startswith("[output compressed: 30 lines ->")
    assert "more lines" in result


def test_tool_name_reads_the_module_of_a_python_command():
    assert compress.tool_name(["python", "-m", "pytest", "-q"]) == "pytest"
    assert compress.tool_name(["pip", "install", "x"]) == "pip"
    assert compress.tool_name(["go", "test", "./..."]) == "go test"
    assert compress.tool_name(["cargo", "build"]) == "cargo build"
    assert compress.tool_name([]) == ""


# ------------------------------------------------------------------ runner
def _broken_rtk(tmp_path):
    """A file that is on PATH but cannot be executed."""
    path = tmp_path / "rtk"
    path.write_text("not a program\n", encoding="utf-8")
    path.chmod(path.stat().st_mode & ~stat.S_IXUSR & ~stat.S_IXGRP & ~stat.S_IXOTH)
    return path


def test_a_broken_rtk_does_not_stop_the_command(monkeypatch, tmp_path):
    """An rtk that cannot start must not fail the command it wraps."""
    broken = _broken_rtk(tmp_path)
    monkeypatch.setattr(command, "rtk_path", lambda: str(broken))

    result = command.run([sys.executable, "-c", "print('hello')"])

    assert result.exit_code == 0
    assert result.used_rtk is False
    assert "hello" in result.output


def test_the_built_in_compressor_replaces_the_missing_rtk(monkeypatch):
    monkeypatch.setattr(command, "rtk_path", lambda: None)

    result = command.run(
        [sys.executable, "-c",
         "print('Downloading thing'); print('done')"])

    assert result.used_rtk is False
    assert result.compressed is True
    assert "output compressed" in result.summary()


def test_the_compressor_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(command, "rtk_path", lambda: None)

    result = command.run(
        [sys.executable, "-c",
         "print('Downloading thing'); print('done')"],
        compress=False)

    assert result.compressed is False
    assert "Downloading thing" in result.output
