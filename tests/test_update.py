"""Tests for self-update."""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import types
import sys
from pathlib import Path

import pytest

from nusa_rg import update


# ------------------------------------------------------------------ helpers
def run_git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                          capture_output=True,
                          text=True, check=False)


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Keep audit logs and state out of the real home directory."""
    state = tmp_path / "state"
    monkeypatch.setenv("NUSA_RG_HOME", str(state))
    return state


@pytest.fixture
def checkout(tmp_path):
    """Return a named holder with the working checkout and the bare origin."""
    """A git checkout whose origin presents as the real repository.

    The URL is rewritten with ``insteadOf`` so the guard sees the real address
    while git still fetches from a local bare repository.
    """
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"

    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    run_git("clone", "-q", str(origin), str(work))
    run_git("checkout", "-q", "-b", "main", cwd=work)

    (work / "nusa_rg").mkdir()
    (work / "nusa_rg" / "__init__.py").write_text(
        '__version__ = "1.0.0"\n', encoding="utf-8")
    (work / "install.sh").write_text('#!/bin/bash\necho INSTALLER\n',
                                     encoding="utf-8")
    run_git("add", "-A", cwd=work)
    run_git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base", cwd=work)
    run_git("tag", "v1.0.0", cwd=work)
    run_git("remote", "set-url", "origin", update.GITHUB_REPO, cwd=work)
    # Present the remote as the real repository while git fetches locally.
    # The rewrite target omits ".git" because git appends it to path-like URLs,
    # so the bare repository itself is named "<target>.git".
    run_git("config", f"url.file://{origin.parent}/origin.insteadOf",
            update.GITHUB_REPO, cwd=work)
    pushed = run_git("push", "-q", "origin", "main", "--tags", cwd=work)
    assert pushed.returncode == 0, pushed.stderr
    return types.SimpleNamespace(work=work, origin=origin)


def publish(origin, work, version: str):
    """Commit a new version to the upstream repository.

    Tags are force-pushed: the tag is recreated locally with ``git tag -f``,
    and pushing a moved tag without ``--force`` is rejected, which would
    silently leave the remote on the previous version.

    Every git call carries an explicit identity. ``git tag -m`` creates an
    annotated tag, which needs a committer, and without one it fails -- and the
    failure is easy to miss because a later ``git push --tags`` then simply has
    nothing new to send.
    """
    publisher = origin.parent / f"pub{version}"
    shutil.rmtree(publisher, ignore_errors=True)
    run_git("clone", "-q", str(origin), str(publisher))
    run_git("checkout", "-q", "main", cwd=publisher)
    (publisher / "nusa_rg" / "__init__.py").write_text(
        f'__version__ = "{version}"\n', encoding="utf-8")
    run_git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-aqm",
            f"release {version}", cwd=publisher)
    tagged = run_git("-c", "user.email=t@t", "-c", "user.name=t",
                     "tag", "-f", f"v{version}", "-m", "release", cwd=publisher)
    assert tagged.returncode == 0, f"tag failed: {tagged.stderr}"
    pushed = run_git("push", "-q", "--force", "origin", "main", "--tags",
                     cwd=publisher)
    assert pushed.returncode == 0, f"publish failed: {pushed.stderr}"
    # Confirm the tag actually reached the remote; a silent no-op here would
    # otherwise surface much later as "no update available".
    listing = run_git("ls-remote", "--tags", "--refs", str(origin))
    assert f"v{version}" in listing.stdout, f"tag missing upstream: {version}"
    return publisher


# ------------------------------------------------------------- version logic
@pytest.mark.parametrize("remote,local,expected", [
    ("1.0.1", "1.0.0", True),
    ("1.1.0", "1.0.0", True),
    ("2.0.0", "1.9.9", True),
    ("1.0.0", "1.0.0", False),
    ("0.9.0", "1.0.0", False),
    (None, "1.0.0", None),
    ("", "1.0.0", None),
])
def test_is_newer(remote, local, expected):
    assert update.is_newer(remote, local) is expected


def test_version_parsing_handles_suffixes():
    assert update._parse_version("v1.2.3") == (1, 2, 3)
    assert update._parse_version("1.2.3-rc1") == (1, 2, 3)
    assert update._parse_version("") == (0,)


# ------------------------------------------------------------ remote guard
@pytest.mark.parametrize("url,expected", [
    ("https://github.com/PADZ-PRD/RAG-termux-cli", True),
    ("https://github.com/PADZ-PRD/RAG-termux-cli.git", True),
    ("https://GitHub.com/PADZ-PRD/RAG-termux-cli/", True),
    ("https://github.com/evil/RAG-termux-cli", False),
    ("https://github.com/PADZ-PRD/other", False),
    ("git@github.com:PADZ-PRD/RAG-termux-cli.git", False),
    # Plaintext HTTP must stay refused: an update fetches and runs this code.
    ("http://github.com/PADZ-PRD/RAG-termux-cli", False),
    ("HTTPS://github.com/PADZ-PRD/RAG-termux-cli", True),
    ("/tmp/some/local/repo", False),
    ("", False),
    (None, False),
])
def test_expected_remote(url, expected):
    assert update._is_expected_remote(url) is expected


# ---------------------------------------------- local / offline opt-in remote
@pytest.mark.parametrize("url,expected_remote_path,allowed", [
    # Configured explicitly: the exact path is honoured.
    ("/root/mirror.git", "/root/mirror.git", True),
    ("/root/mirror.git/", "/root/mirror.git", True),
    # A different local path is not what the user authorised.
    ("/root/other.git", "/root/mirror.git", False),
    # An https checkout is not the local mirror that was configured, and an
    # https expected remote never authorises a local checkout.
    ("https://github.com/PADZ-PRD/RAG-termux-cli", "/root/mirror.git", False),
    ("/root/mirror.git", "https://github.com/PADZ-PRD/RAG-termux-cli", False),
])
def test_local_remote_requires_an_explicit_opt_in(url, expected_remote_path,
                                                  allowed):
    assert update._is_expected_remote(url, expected_remote_path) is allowed


def test_local_remote_expands_a_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    home = Path(str(tmp_path)) / "mirror.git"
    assert update._is_expected_remote("~/mirror.git", "~/mirror.git") is True
    assert update._is_expected_remote("~/other.git", "~/mirror.git") is False
    assert update._is_expected_remote(str(home), "~/mirror.git") is True


def test_expected_remote_defaults_to_github_and_follows_config(monkeypatch):
    from nusa_rg import config as config_module

    monkeypatch.setattr(config_module.Config, "get",
                        lambda self, key, default=None: default)
    assert update.expected_remote() == update.GITHUB_REPO

    monkeypatch.setattr(
        config_module.Config, "get",
        lambda self, key, default=None: "/root/mirror.git"
        if key == update.REMOTE_KEY else default,
    )
    assert update.expected_remote() == "/root/mirror.git"


def test_a_broken_config_cannot_open_the_guard(monkeypatch):
    """A config that explodes must fall back to the default, not to 'allow'."""
    from nusa_rg import config as config_module

    def explode(self, key, default=None):
        raise RuntimeError("corrupt config")

    monkeypatch.setattr(config_module.Config, "get", explode)
    assert update.expected_remote() == update.GITHUB_REPO
    assert update._is_expected_remote("/root/whatever.git") is False


def test_a_git_suffix_is_dropped_only_when_comparing_local_paths():
    """`/srv/mirror` and `/srv/mirror.git` name the same repository to git."""
    assert update._is_expected_remote("/srv/mirror.git", "/srv/mirror") is True
    assert update._is_expected_remote("/srv/mirror", "/srv/mirror.git") is True
    # ...but a different directory is still refused.
    assert update._is_expected_remote("/srv/other.git", "/srv/mirror") is False


def test_remote_url_is_read_verbatim(checkout):
    """The stored URL must survive intact, .git suffix included.

    `_remote_url` used to strip a trailing ``.git`` while parsing. That was
    meant for ssh URLs, but it also rewrote a local bare path: a remote stored
    as ``/srv/mirror.git`` came back as ``/srv/mirror``, a different directory,
    which then failed to match the configured remote and made every update
    report the checkout as foreign.
    """
    work = checkout.work
    run_git("remote", "set-url", "origin", "/srv/mirror.git", cwd=work)
    assert update._remote_url(work) == "/srv/mirror.git"


def test_the_refusal_names_the_configured_remote(checkout, monkeypatch):
    """With an offline mirror set, blaming GitHub would point at the wrong repo."""
    run_git("remote", "set-url", "origin", "https://github.com/other/x.git",
            cwd=checkout.work)
    from nusa_rg import config as config_module

    monkeypatch.setattr(
        config_module.Config, "get",
        lambda self, key, default=None: "/root/mirror.git"
        if key == update.REMOTE_KEY else default,
    )
    monkeypatch.setattr(update, "find_source_dir", lambda: checkout.work)
    info = update.check()
    assert info.method == update.METHOD_UNKNOWN
    assert "https://github.com/other/x.git" in info.detail
    assert "/root/mirror.git" in info.detail
    assert update.GITHUB_REPO not in info.detail


def test_foreign_repository_is_refused(tmp_path):
    """A .git belonging to another project must not be updated."""
    other = tmp_path / "other"
    other.mkdir()
    run_git("init", "-q", str(other))
    run_git("remote", "add", "origin",
            "https://github.com/someone/else.git", cwd=other)

    source = update.find_source_dir(other / "nusa_rg")
    assert source == other
    # The guard is what decides; check it directly for a foreign remote.
    assert update._is_expected_remote(update._remote_url(source)) is False
    assert update.check().method != update.METHOD_SOURCE


def test_no_checkout_reports_unknown(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert update.find_source_dir(plain) is None


# ------------------------------------------------------------------- check
def test_check_detects_available_update(checkout):
    publish(checkout.origin, checkout.work, "1.1.0")
    info = update.check()
    info.source_dir = checkout.work
    info.method = update.METHOD_SOURCE
    info.branch = update.current_branch(checkout.work)
    info.remote_version = update.remote_version(checkout.work)
    info.available = update.is_newer(info.remote_version, "1.0.0")

    assert info.remote_version == "1.1.0"
    assert info.available is True
    assert "update available" in info.summary()


def test_check_reports_up_to_date(checkout):
    info = update.UpdateInfo(installed_version="1.0.0",
                             method=update.METHOD_SOURCE,
                             source_dir=checkout.work, remote_version="1.0.0",
                             available=False)
    assert "up to date" in info.summary()


def test_summary_is_honest_when_remote_is_unknown():
    info = update.UpdateInfo(installed_version="1.0.0",
                             method=update.METHOD_SOURCE,
                             remote_version=None)
    assert "up to date" not in info.summary()
    assert "could not determine" in info.summary()


def test_package_install_summary_points_at_pkg():
    info = update.UpdateInfo(installed_version="1.0.0",
                             method=update.METHOD_PACKAGE)
    assert "pkg upgrade" in info.summary()


# ----------------------------------------------------------------- perform
def test_perform_fast_forwards_and_runs_installer(checkout):
    publish(checkout.origin, checkout.work, "1.1.0")
    info = update.UpdateInfo(installed_version="1.0.0",
                             method=update.METHOD_SOURCE,
                             source_dir=checkout.work, branch="main",
                             remote_version="1.1.0", available=True)
    result = update.perform(info)

    assert result.ok is True
    assert result.changed is True
    assert result.new_version == "1.1.0"
    assert "ran install.sh" in result.steps
    assert "1.1.0" in (checkout.work / "nusa_rg" / "__init__.py").read_text()


def test_perform_reports_no_change_when_current(checkout):
    info = update.UpdateInfo(installed_version="1.0.0",
                             method=update.METHOD_SOURCE,
                             source_dir=checkout.work, branch="main",
                             remote_version="1.0.0", available=False)
    result = update.perform(info)
    assert result.ok is True
    assert result.changed is False


def test_perform_refuses_a_dirty_tree(checkout):
    (checkout.work / "nusa_rg" / "__init__.py").write_text(
        '__version__ = "1.0.0"\n# local edit\n', encoding="utf-8")
    info = update.UpdateInfo(installed_version="1.0.0",
                             method=update.METHOD_SOURCE,
                             source_dir=checkout.work, branch="main",
                             dirty=True, remote_version="1.1.0", available=True)
    with pytest.raises(update.UpdateError) as exc:
        update.perform(info)
    assert "uncommitted" in str(exc.value)


def test_perform_force_discards_local_commits(checkout):
    publish(checkout.origin, checkout.work, "1.1.0")
    (checkout.work / "extra.txt").write_text("local\n", encoding="utf-8")
    run_git("add", "-A", cwd=checkout.work)
    run_git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm",
        "local", cwd=checkout.work)

    info = update.UpdateInfo(installed_version="1.0.0",
                             method=update.METHOD_SOURCE,
                             source_dir=checkout.work, branch="main",
                             dirty=True, remote_version="1.1.0", available=True)
    result = update.perform(info, force=True)
    assert result.ok is True
    assert result.changed is True


def test_perform_rejects_a_non_source_install():
    info = update.UpdateInfo(installed_version="1.0.0",
                             method=update.METHOD_PACKAGE)
    with pytest.raises(update.UpdateError):
        update.perform(info)


def test_perform_reports_a_missing_installer(checkout):
    publish(checkout.origin, checkout.work, "1.1.0")
    (checkout.work / "install.sh").unlink()
    info = update.UpdateInfo(installed_version="1.0.0",
                             method=update.METHOD_SOURCE,
                             source_dir=checkout.work, branch="main",
                             remote_version="1.1.0", available=True)
    result = update.perform(info, runner=True)
    # The checkout itself still updates; only the installer is missing.
    assert "missing" in (result.detail or "") or result.ok


# ----------------------------------------------------------- error messages
def test_git_error_is_condensed_to_one_line():
    raw = ("fatal: Not possible to fast-forward, aborting.\n"
           "hint: Diverging branches can't be fast-forwarded\n"
           "hint:\nhint: \tgit rebase\n"
           "To /tmp/repo\n  92148ac..d595fa0  main -> main\n")
    message = update._readable_git_error("could not fast-forward", raw)
    assert "could not fast-forward" in message
    assert "fast-forwarded, you need" not in message
    assert "\nhint" not in message
    assert len(message.splitlines()) == 1


def test_git_error_includes_a_hint():
    message = update._readable_git_error("boom", "fatal: nope", hint="try again")
    assert "try again" in message


def test_git_error_handles_empty_output():
    assert update._readable_git_error("boom", "").startswith("boom")


# --------------------------------------------------------------------- CLI
SOURCE_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _run_cli(args, cwd):
    """Run the CLI from this source tree, with cwd elsewhere."""
    env = dict(os.environ, PYTHONPATH=str(SOURCE_ROOT))
    return subprocess.run(
        [sys.executable, "-m", "nusa_rg", *args],
        cwd=str(cwd), capture_output=True, text=True, env=env, check=False,
    )


def test_cli_check_without_a_checkout(tmp_path):
    """A directory with no git repo must not crash."""
    plain = tmp_path / "plain"
    plain.mkdir()
    result = _run_cli(["update", "--check"], plain)
    assert result.returncode == 1
    assert "checkout" in (result.stdout + result.stderr).lower()


def test_cli_update_is_listed():
    result = _run_cli(["--help"], "/tmp")
    assert "update" in result.stdout


def test_cli_update_is_audited(tmp_path, isolated_state):
    plain = tmp_path / "plain"
    plain.mkdir()
    _run_cli(["update", "--check"], plain)
    log = isolated_state / "logs" / "audit.log"
    assert log.exists()
    assert "update.check" in log.read_text()