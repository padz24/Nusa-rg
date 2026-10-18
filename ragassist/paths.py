"""Filesystem locations used by the assistant.

Every mutable artefact lives under a single directory (``~/.rag-assist`` by
default) so that the whole install can be relocated, inspected, or removed by
acting on one path. See AGENS.md section 9 ("Struktur Penyimpanan Lokal").
"""

from __future__ import annotations

import os
from pathlib import Path


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def base_dir() -> Path:
    """Root directory for all application state.

    Honours ``RAG_ASSIST_HOME`` so tests (and users juggling several project
    trees) can redirect state without touching the real home directory.
    """
    override = os.environ.get("RAG_ASSIST_HOME")
    if override:
        return Path(override).expanduser()
    return _home() / ".rag-assist"


def config_path() -> Path:
    return base_dir() / "config.yaml"


def index_db_path() -> Path:
    return base_dir() / "index.db"


def keystore_path() -> Path:
    return base_dir() / "keystore.bin"


def catalog_path() -> Path:
    """Refreshed provider catalogue; the bundled snapshot is used without it."""
    return base_dir() / "catalog.json"


def log_dir() -> Path:
    return base_dir() / "logs"


def app_log_path() -> Path:
    return log_dir() / "app.log"


def audit_log_path() -> Path:
    return log_dir() / "audit.log"


def ensure_dirs() -> None:
    """Create the state directories with owner-only permissions.

    Directories get 0700 and files 0600; a 0600 directory would have no
    execute bit and could not be traversed.
    """
    base_dir().mkdir(parents=True, exist_ok=True)
    restrict(base_dir(), 0o700)
    log_dir().mkdir(parents=True, exist_ok=True)
    restrict(log_dir(), 0o700)


def restrict(path: Path, mode: int = 0o600) -> Path:
    """Apply ``mode`` to ``path`` (or its directory), ignoring errors.

    Android's app sandbox already isolates files, but SEC-03/SEC-04/SEC-07 ask
    for explicit 600 permissions, which is also what makes the requirement
    verifiable with a plain ``ls -l``.
    """
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    return path