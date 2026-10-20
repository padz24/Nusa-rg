"""Runtime facts for the startup banner: project, branch, index, model, rtk.

The banner shows live state, so gathering it must never block or crash a
command: every lookup degrades to a placeholder, the index database is only
opened when it already exists, and git runs with a short timeout.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import __version__, command, paths
from .config import Config
from .rag import ProjectIndex

#: ``git`` must answer fast: a stalled subprocess would delay the prompt.
_GIT_TIMEOUT = 2.0

#: Placeholder for a fact that could not be resolved.
_DASH = "—"


@dataclass(frozen=True)
class Facts:
    """Values rendered in the banner's identity lines and status chips."""

    version: str = __version__
    project: str = _DASH
    branch: str = ""
    index: str = "empty"
    model: str = _DASH
    rtk: str = "off"

    @property
    def index_ready(self) -> bool:
        """True when the index holds chunks (the green chip)."""
        return bool(self.index) and self.index not in ("empty", _DASH)


def _config() -> Config | None:
    """Load the config only when it exists; a banner must not create state."""
    if not paths.config_path().exists():
        return None
    try:
        return Config()
    except Exception:  # noqa: BLE001 - a broken config must not hide the banner
        return None


def _ago(seconds: float) -> str:
    """Human age of the index, e.g. ``2m ago`` (the reference wording)."""
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def _shorten(path: str) -> str:
    """Collapse the home prefix to ``~`` for display."""
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


def _git(project: Path) -> str:
    """Branch name for the checkout at ``project``, or ``""`` outside git."""
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(project),
             "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    branch = result.stdout.strip()
    return "detached" if branch == "HEAD" else branch


def _index_row() -> tuple[str, str]:
    """``(card value, indexed root)``; never creates the database."""
    if not paths.index_db_path().exists():
        return "empty", ""
    try:
        with ProjectIndex() as index:
            root = index.project_root
            _files, chunks = index.count()
            if not chunks:
                return "empty", root
            value = f"{chunks:,} chunks"
            stamp = index.get_meta("last_indexed_at")
            if stamp:
                try:
                    age = time.time() - float(stamp)
                except ValueError:
                    age = -1.0
                if age >= 0:
                    value += f" · {_ago(age)}"
            return value, root
    except Exception:  # noqa: BLE001 - a broken index must not hide the banner
        return _DASH, ""


def _model(config: Config | None) -> str:
    """Configured model: the API model id, or the local file name."""
    if config is None:
        return _DASH
    provider = str(config.get("model_provider", "external") or "external")
    if provider == "local":
        local = str(config.get("local_model_path") or "")
        return Path(local).name if local else "local"
    return str(config.get("api_model") or "") or _DASH


def _rtk(config: Config | None) -> str:
    """Whether rtk output filtering is enabled and actually installed."""
    enabled = True if config is None else bool(config.get("command_use_rtk", True))
    return "on" if enabled and command.rtk_path() else "off"


def collect() -> Facts:
    """Gather every banner fact, degrading instead of raising."""
    config = _config()

    project = ""
    if config is not None:
        try:
            project = str(config.project_path() or "")
        except Exception:  # noqa: BLE001 - a broken config must not hide the banner
            project = ""

    index_value, indexed_root = _index_row()
    if not project:
        if indexed_root:
            project = indexed_root
        else:
            try:
                project = str(Path.cwd())
            except OSError:
                project = "."

    checkout = Path(project).expanduser()
    branch = _git(checkout) if checkout.is_dir() else ""
    return Facts(
        project=_shorten(str(checkout)),
        branch=branch,
        index=index_value,
        model=_model(config),
        rtk=_rtk(config),
    )
