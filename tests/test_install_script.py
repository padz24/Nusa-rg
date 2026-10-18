"""Tests for install.sh's choice of source directory.

The bug these guard against: `nusa-rg update` re-runs install.sh from the
tree it just updated. When install.sh always aimed at ``$HOME/nusa-rg``, it
cloned a *second* copy and installed that one instead, so the update appeared
to succeed while the running code stayed on the old checkout -- and on a machine
with no network it failed outright on the clone.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parent.parent / "install.sh"


def resolved_repo_dir(env: dict[str, str] | None = None,
                      cwd: Path | None = None,
                      argv: Path | None = None) -> str:
    """Run install.sh's resolution and return the directory it would install.

    Uses the script's own NUSA_RG_PRINT_REPO_DIR seam so this exercises the
    shipped file rather than a copy of its logic.
    """
    run_env = dict(os.environ)
    run_env["NUSA_RG_PRINT_REPO_DIR"] = "1"
    run_env.update(env or {})
    command = ["bash", str(argv)] if argv else ["bash", str(INSTALL_SH)]
    completed = subprocess.run(
        command, cwd=str(cwd) if cwd else None, env=run_env,
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def make_checkout(root: Path) -> Path:
    """A directory that looks enough like the real source tree.

    ``install.sh`` is copied in verbatim, because the script resolves its own
    location: running the shipped file would always point at the shipped tree.
    """
    checkout = root / "RAG-termux-cli"
    (checkout / "nusa_rg").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    shutil.copy2(INSTALL_SH, checkout / "install.sh")
    return checkout


def test_an_explicit_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    chosen = tmp_path / "explicit"
    chosen.mkdir()
    assert resolved_repo_dir({"NUSA_RG_REPO_DIR": str(chosen)}) == str(chosen)


def test_running_the_checkout_installs_that_checkout(tmp_path, monkeypatch):
    """`bash /path/to/install.sh` must install the tree it lives in."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    checkout = make_checkout(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    resolved = resolved_repo_dir(cwd=elsewhere, argv=checkout / "install.sh")
    assert resolved == str(checkout)


def test_the_cwd_is_never_treated_as_a_checkout(tmp_path, monkeypatch):
    """A decoy checkout in the working directory must not be installed.

    This is the `curl ... | bash` shape: the script arrives on stdin, so
    ${BASH_SOURCE[0]} is "bash" rather than a path, and the user's current
    directory says nothing about which tree they meant.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    decoy = make_checkout(tmp_path)

    completed = subprocess.run(
        ["bash"], cwd=str(decoy),
        stdin=INSTALL_SH.open("rb"),
        env={"PATH": "/usr/bin:/bin:/data/data/com.termux/files/usr/bin",
             "HOME": str(home), "NUSA_RG_PRINT_REPO_DIR": "1"},
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == str(home / "nusa-rg")


def test_a_partial_directory_falls_back_to_cloning(tmp_path, monkeypatch):
    """A `nusa_rg/` dir without pyproject.toml is not a checkout."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    impostor = tmp_path / "impostor"
    (impostor / "nusa_rg").mkdir(parents=True)
    shutil.copy2(INSTALL_SH, impostor / "install.sh")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    resolved = resolved_repo_dir(cwd=elsewhere, argv=impostor / "install.sh")
    assert resolved == str(tmp_path / "home" / "nusa-rg")


def test_update_runs_the_installer_against_the_updated_tree(tmp_path):
    """update.perform must hand install.sh an explicit NUSA_RG_REPO_DIR."""
    source = Path(__file__).resolve().parent.parent / "nusa_rg" / "update.py"
    text = source.read_text(encoding="utf-8")
    assert 'env = {"NUSA_RG_REPO_DIR": str(source_dir)}' in text, (
        "update must pass the updated tree to install.sh explicitly, so the "
        "installer cannot fall back to cloning a different copy"
    )


def test_update_skips_the_optional_llama_build(tmp_path):
    """An optional multi-minute build must not block an update."""
    source = Path(__file__).resolve().parent.parent / "nusa_rg" / "update.py"
    text = source.read_text(encoding="utf-8")
    assert '"NUSA_RG_SKIP_LLAMA"' in text


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required")
def test_the_shipped_script_is_syntactically_valid():
    completed = subprocess.run(
        ["bash", "-n", str(INSTALL_SH)], capture_output=True, text=True,
        timeout=60, check=False,
    )
    assert completed.returncode == 0, completed.stderr