"""Shared fixtures: an isolated state directory and a sample project tree."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("NO_COLOR", "1")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point RAG_ASSIST_HOME at a tmp dir so tests never touch ~/.rag-assist."""
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("RAG_ASSIST_HOME", str(state))
    monkeypatch.setenv("NO_COLOR", "1")
    yield state


@pytest.fixture
def sample_project(tmp_path):
    """A small project with enough signal to test retrieval."""
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)

    (root / "src" / "auth.py").write_text(
        "import hashlib\n"
        "\n"
        "\n"
        "def hash_password(password: str) -> str:\n"
        '    """Hash a plaintext password with SHA-256."""\n'
        "    return hashlib.sha256(password.encode()).hexdigest()\n"
        "\n"
        "\n"
        "def verify_password(password: str, digest: str) -> bool:\n"
        "    return hash_password(password) == digest\n",
        encoding="utf-8",
    )
    (root / "src" / "db.py").write_text(
        "import sqlite3\n"
        "\n"
        "\n"
        "def connect(path):\n"
        '    """Open a SQLite database connection."""\n'
        "    return sqlite3.connect(path)\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "# Sample\n\nThis project hashes passwords using SHA-256.\n",
        encoding="utf-8",
    )
    (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00binary")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "junk.js").write_text("const x = 1;\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    return root


@pytest.fixture
def indexed(sample_project):
    """A ProjectIndex with sample_project already indexed."""
    from ragassist.rag import ProjectIndex

    with ProjectIndex() as index:
        index.index(
            sample_project,
            ignore_dirs={"node_modules", ".git"},
            chunk_size=20,
            overlap=5,
        )
        yield index