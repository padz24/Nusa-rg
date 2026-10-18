"""Self-update: bring a source installation up to the latest release.

Three things make this more than "run git pull":

* **Install method matters.** A checkout can update itself; a package installed
  from a Termux repository cannot, and the honest advice there is ``pkg
  upgrade``. Guessing wrong would leave the user with a half-updated install.
* **The target must be verified.** The remote is checked against the expected
  repository before anything is fetched, and nothing is ever run through a
  shell (SEC-02). A ``.git`` directory left by an unrelated project must not be
  treated as this project.
* **It must fail loudly.** No network, a dirty tree, a detached checkout or a
  missing interpreter each produce a specific message rather than a traceback.

Configuration lives in ``~/.nusa-rg``, not in the checkout, so updating never
touches credentials or the index.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__, paths
from .logging_setup import audit

#: Upstream repository. A checkout pointing anywhere else is refused unless the
#: user pins a different remote explicitly (see :func:`expected_remote`).
GITHUB_REPO = "https://github.com/PADZ-PRD/RAG-termux-cli"

#: Config key naming the one remote this installation may update from. Setting
#: it is what authorises an offline or local mirror.
REMOTE_KEY = "update_remote"

#: A git remote we will fetch from.
#:
#: Captured verbatim. This used to strip a trailing ``.git``, which was meant
#: for ssh URLs but silently rewrote local paths too: a bare repository at
#: ``/srv/mirror.git`` was reported as ``/srv/mirror``, a different directory
#: that then failed to match the path the user had configured. Normalisation
#: belongs in the comparison, not in the read.
_REMOTE_RE = re.compile(r"^(?P<url>\S+)$")

METHOD_SOURCE = "source"
METHOD_PACKAGE = "package"
METHOD_UNKNOWN = "unknown"

DEFAULT_TIMEOUT = 900


class UpdateError(RuntimeError):
    """An update could not be attempted or completed."""


@dataclass
class UpdateInfo:
    """What the update check found."""

    installed_version: str
    method: str
    source_dir: Path | None = None
    remote_version: str | None = None
    branch: str = ""
    dirty: bool = False
    detail: str = ""
    available: bool | None = None

    def summary(self) -> str:
        if self.method == METHOD_SOURCE:
            if self.remote_version is None:
                return (f"installed {self.installed_version}; "
                        "could not determine the latest version")
            if self.available is None:
                return (f"installed {self.installed_version}; "
                        f"latest is {self.remote_version} (unorderable)")
            state = "update available" if self.available else "up to date"
            return (f"installed {self.installed_version} -> "
                    f"{self.remote_version} ({state})")
        if self.method == METHOD_PACKAGE:
            return ("installed from a package manager; "
                    "run: pkg upgrade termux-nusa-rg")
        return self.detail or "install method could not be determined"


@dataclass
class UpdateResult:
    """The outcome of a completed update."""

    ok: bool
    changed: bool = False
    old_version: str = ""
    new_version: str = ""
    steps: list[str] = field(default_factory=list)
    detail: str = ""


# ------------------------------------------------------------------ helpers

def _run(command: list[str], cwd: Path | None = None,
         timeout: int = 120,
         env: dict[str, str] | None = None) -> tuple[int, str, str]:
    """Run a command with no shell involved, never raising."""
    try:
        completed = subprocess.run(  # noqa: S603 - argv list, shell=False
            command,
            cwd=str(cwd) if cwd else None,
            env={**os.environ, **env} if env else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
    except FileNotFoundError:
        return 127, "", f"{command[0]} is not installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"{command[0]} timed out after {timeout}s"
    except OSError as exc:
        return 1, "", str(exc)
    return completed.returncode, (completed.stdout or "").strip(), \
        (completed.stderr or "").strip()


def find_source_dir(start: Path | None = None) -> Path | None:
    """Locate the checkout this package was installed from.

    Walks up from the package directory looking for a ``.git`` entry. The
    editable install points straight at the checkout, so this normally lands on
    the first step.
    """
    current = (start or Path(__file__).resolve()).parent
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _remote_url(source_dir: Path) -> str | None:
    """The origin URL as configured.

    Read with ``git config`` rather than ``git remote get-url``: the latter
    applies ``insteadOf`` rewrites and would report the rewritten target rather
    than what the user actually configured.
    """
    code, out, _ = _run(["git", "config", "--get", "remote.origin.url"],
                       cwd=source_dir)
    if code != 0 or not out:
        return None
    match = _REMOTE_RE.match(out.splitlines()[0].strip())
    return match.group("url") if match else None


def expected_remote() -> str:
    """The remote this installation is allowed to update from.

    Defaults to :data:`GITHUB_REPO`. A local or offline remote is only honoured
    when the user names it with ``nusa-rg config set update_remote <path>``:
    an update runs ``git reset --hard``, so the target has to be something the
    user chose, never merely whatever ``origin`` happens to point at.
    """
    try:
        from .config import Config

        configured = str(Config().get(REMOTE_KEY, "") or "").strip()
    except Exception:  # noqa: BLE001 - a broken config must not open the door
        configured = ""
    return configured or GITHUB_REPO


def _is_local_remote(url: str) -> bool:
    return not url.lower().startswith(("http://", "https://", "git@", "ssh://"))


def _local_path(value: str) -> str:
    """Canonical form of a local remote path.

    A trailing ``.git`` is dropped because a bare repository can be named
    either way and both refer to it. Keeping it would refuse a checkout over
    nothing the user could act on -- and it would also make ``/srv/mirror`` and
    ``/srv/mirror.git`` look like different repositories when they are the same
    one to git.
    """
    cleaned = os.path.normpath(os.path.expanduser(value.strip()))
    return cleaned[:-4] if cleaned.lower().endswith(".git") else cleaned


def _https_parts(url: str) -> tuple[str, str] | None:
    """(host, path) for an ``https://`` URL, or None for anything else.

    Returning None for every other scheme is deliberate. The original guard
    matched only on ``https://``, and loosening it to "strip the scheme and
    compare host and path" silently started accepting ``http://``, which is
    plain text: an update fetches code from that remote and runs it.
    """
    if not url.lower().startswith("https://"):
        return None
    host, _, path = url.strip()[len("https://"):].partition("/")
    path = path.strip("/")
    if path.lower().endswith(".git"):
        path = path[:-4]
    return host.strip().lower(), path.lower()


def _is_expected_remote(url: str | None, expected: str | None = None) -> bool:
    """True only for the remote the user is entitled to update from.

    Derived from :data:`GITHUB_REPO` (or an explicitly configured remote) so
    the two cannot drift apart, and strict about scheme, host and path so a
    ``.git`` directory belonging to some other project is never mistaken for
    this one.
    """
    if not url:
        return False
    expected = expected if expected is not None else expected_remote()
    if not expected:
        return False

    if _is_local_remote(expected):
        # An offline remote is only accepted when it was configured by hand,
        # and only when the checkout actually points at that exact path.
        if not _is_local_remote(url):
            return False
        return _local_path(url) == _local_path(expected)

    if _is_local_remote(url):
        return False
    return _https_parts(url) is not None and _https_parts(url) == _https_parts(expected)


def current_branch(source_dir: Path) -> str:
    code, out, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                       cwd=source_dir)
    return out if code == 0 else ""


def is_dirty(source_dir: Path) -> bool:
    code, out, _ = _run(["git", "status", "--porcelain"], cwd=source_dir)
    return code == 0 and bool(out)


def remote_version(source_dir: Path) -> str | None:
    """Read the latest tag from the remote without touching the working tree."""
    # Use the configured URL rather than the name "origin", so a checkout whose
    # remote was renamed still works.
    url = _remote_url(source_dir)
    if not url:
        return None
    code, out, err = _run(
        ["git", "ls-remote", "--tags", "--refs", "--sort=-v:refname", url],
        cwd=source_dir, timeout=60,
    )
    if code != 0:
        return None
    del err
    for line in out.splitlines():
        parts = line.split("refs/tags/")
        if len(parts) == 2 and parts[1].strip():
            return parts[1].strip().lstrip("v")
    return None


def _parse_version(text: str) -> tuple:
    """Parse the leading numeric release into a comparable tuple.

    Only the leading dotted-numeric part counts, so ``1.2.3-rc1`` orders as
    ``(1, 2, 3)`` rather than ``(1, 2, 3, 1)``; otherwise a release candidate
    would look newer than the release it precedes.
    """
    match = re.match(r"\s*v?(\d+(?:\.\d+)*)", text or "")
    if not match:
        return (0,)
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(remote: str | None, local: str) -> bool | None:
    """True when ``remote`` is newer; None when it cannot be determined."""
    if not remote:
        return None
    if remote == local:
        return False
    return _parse_version(remote) > _parse_version(local)


# -------------------------------------------------------------------- check

def check() -> UpdateInfo:
    """Determine whether an update is available."""
    info = UpdateInfo(installed_version=__version__, method=METHOD_UNKNOWN)

    source_dir = find_source_dir()
    if source_dir is None:
        if _package_installed():
            info.method = METHOD_PACKAGE
            info.detail = "installed as a package, not from a checkout"
        else:
            info.detail = ("no git checkout found; reinstall with install.sh "
                           "to enable self-update")
        return info

    info.source_dir = source_dir
    info.branch = current_branch(source_dir)
    info.dirty = is_dirty(source_dir)

    configured = expected_remote()
    actual = _remote_url(source_dir)
    if not _is_expected_remote(actual):
        info.method = METHOD_UNKNOWN
        # Name the remote the user actually configured, not the built-in
        # default: with an offline mirror configured, blaming GitHub would
        # point at the wrong repository.
        hint = ("" if configured == GITHUB_REPO
                else f" (update_remote is set to {configured})")
        info.detail = (f"{source_dir} is not a checkout of {configured}{hint}; "
                       f"its origin is {actual or 'unset'}; "
                       f"refusing to update it")
        return info

    info.method = METHOD_SOURCE
    info.remote_version = remote_version(source_dir)
    info.available = is_newer(info.remote_version, __version__)
    if info.remote_version is None:
        info.detail = "could not reach the remote to check for a newer version"
    return info


def _package_installed() -> bool:
    """True when this looks like a package-manager install rather than a checkout."""
    executable = shutil_which("pkg") or shutil_which("apt")
    if not executable:
        return False
    code, out, _ = _run([executable, "list-installed"], timeout=60)
    return code == 0 and "termux-nusa-rg" in out


def shutil_which(name: str) -> str | None:
    return shutil.which(name)


# ------------------------------------------------------------------ perform

def perform(info: UpdateInfo, *, force: bool = False,
            runner: bool = True) -> UpdateResult:
    """Update the checkout and, optionally, re-run the installer."""
    if info.method != METHOD_SOURCE or info.source_dir is None:
        raise UpdateError(info.detail or "this installation cannot self-update")

    source_dir = info.source_dir
    steps: list[str] = []

    if info.dirty and not force:
        raise UpdateError(
            f"{source_dir} has uncommitted changes; commit or discard them, "
            "or re-run with --force"
        )

    code, out, err = _run(["git", "fetch", "--tags", "--prune"],
                          cwd=source_dir, timeout=300)
    if code != 0:
        raise UpdateError(_readable_git_error(
            "git fetch failed", f"{out} {err}",
            hint="check the network connection and the remote URL"))
    steps.append("fetched from origin")

    before = _run(["git", "rev-parse", "HEAD"], cwd=source_dir)[1]

    target = info.branch or "main"
    if force:
        code, out, err = _run(["git", "reset", "--hard", f"origin/{target}"],
                              cwd=source_dir, timeout=120)
        verb = "reset to origin/" + target
    else:
        code, out, err = _run(["git", "merge", "--ff-only", f"origin/{target}"],
                              cwd=source_dir, timeout=120)
        verb = "fast-forward to origin/" + target
    if code != 0:
        raise UpdateError(_readable_git_error(
            f"could not {verb}",
            f"{out} {err}",
            hint=("the local branch has diverged; re-run with --force to "
                  "discard local commits" if not force else None),
        ))
    steps.append(verb)

    after = _run(["git", "rev-parse", "HEAD"], cwd=source_dir)[1]
    changed = before != after
    if not changed:
        steps.append("already at the latest commit")

    new_version = _version_from_checkout(source_dir)
    result = UpdateResult(
        ok=True, changed=changed,
        old_version=info.installed_version, new_version=new_version,
        steps=steps,
    )

    if runner and changed:
        script = source_dir / "install.sh"
        if not script.is_file():
            result.detail = f"updated the checkout, but {script} is missing"
            return result
        # Point the installer at the tree we just updated. It also works this
        # out on its own, but saying so explicitly keeps the two from drifting.
        env = {"NUSA_RG_REPO_DIR": str(source_dir)}
        if shutil.which("llama-cli") is None:
            # Never let an optional, multi-minute build block an update.
            env["NUSA_RG_SKIP_LLAMA"] = "1"
        code, out, err = _run(["bash", str(script)], cwd=source_dir,
                              timeout=DEFAULT_TIMEOUT, env=env)
        if code != 0:
            result.ok = False
            result.detail = (
                "the checkout updated, but install.sh failed:\n"
                + (err or out or f"exit code {code}")[-800:]
            )
            return result
        steps.append("ran install.sh")
        result.new_version = new_version

    audit("update", "SUCCESS" if result.ok else "FAILED",
          f"changed={changed} {info.installed_version}->{result.new_version}")
    return result


def _readable_git_error(prefix: str, raw: str, hint: str | None = None) -> str:
    """Condense git's multi-paragraph output into one actionable line.

    git prints several screens of hints after a failure; the first real line is
    the diagnosis, and the rest is advice the user does not need here.
    """
    for line in (raw or "").splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("hint:") or cleaned == "fatal:":
            continue
        if cleaned.startswith(("To ", "Disable ")):
            continue
        return f"{prefix}: {cleaned}" + (f" ({hint})" if hint else "")
    return prefix + (f" ({hint})" if hint else ": unknown error")


def _version_from_checkout(source_dir: Path) -> str:
    """Read __version__ from the updated source without importing it."""
    version_file = source_dir / "nusa_rg" / "__init__.py"
    try:
        text = version_file.read_text(encoding="utf-8")
    except OSError:
        return __version__
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']',
                      text, re.MULTILINE)
    return match.group(1) if match else __version__


def state_directory() -> Path:
    """The state directory, mentioned in the summary so users know it is safe."""
    return paths.base_dir()


def environment_note() -> str:
    """A caution that only applies to some installations."""
    if os.geteuid() == 0 if hasattr(os, "geteuid") else False:
        return ("running as root: pkg refuses to run as root, so a Termux "
                "package install would fail; prefer a normal user session")
    return ""


__all__ = [
    "UpdateInfo",
    "UpdateResult",
    "UpdateError",
    "check",
    "perform",
    "find_source_dir",
    "current_branch",
    "is_dirty",
    "remote_version",
    "is_newer",
    "GITHUB_REPO",
    "REMOTE_KEY",
    "expected_remote",
    "environment_note",
    "state_directory",
]