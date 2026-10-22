"""Memory of failure: what went wrong, and what was already tried.

A note is written when something fails: a command that exits non-zero, or a
provider that errors out. The next time the same failure shows up, the note
comes back with the prompt, so the assistant does not walk into the same dead
end twice.

A note is identified by the fingerprint of the error, not by its text:
numbers, paths, timestamps and identifiers are normalised away, so the same
failure in two places is one note. Nothing secret goes into a fingerprint or
into a note: the text is screened before it is stored.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import privacy

MEMORY_OPEN = "<|RAG_MEMORY|>"
MEMORY_CLOSE = "<|/RAG_MEMORY|>"

#: The four states a note can be in.
STATUSES = ("investigating", "attempted", "blocked", "resolved")

#: What the block in the prompt is called.
LABEL = "pengalaman historis"

_NORMALISERS = (
    (re.compile(r"0x[0-9a-fA-F]+"), "#"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "#"),
    (re.compile(r"\b[0-9a-fA-F]{16,}\b"), "#"),
    (re.compile(r"/[\w./-]{4,}"), "<path>"),
    (re.compile(r"'[^']*'|\"[^\"]*\""), "#"),
    (re.compile(r"\b\d+(\.\d+)?\b"), "#"),
    (re.compile(r"\s+"), " "),
)


@dataclass
class MemoryNote:
    """One recorded failure."""

    id: str
    project: str
    status: str
    fingerprint: str
    summary: str
    detail: str
    subject: str
    created_at: float
    updated_at: float
    attempts: int = 1

    def summary_line(self) -> str:
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.created_at))
        return (f"{stamp} · {self.status} · {self.summary} "
                f"(percobaan {self.attempts})")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "project": self.project,
            "status": self.status,
            "fingerprint": self.fingerprint,
            "summary": self.summary,
            "detail": self.detail,
            "attempts": self.attempts,
        }


def project_key(root: str) -> str:
    """A project identity that is not an absolute path.

    The name is kept so a human can recognise it, and a digest of the path so
    two projects with the same name stay apart. The path itself never leaves
    the machine.
    """
    if not root:
        return "unknown"
    digest = hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()[:8]
    name = Path(root).name or "project"
    return f"{name}-{digest}"


def normalise(text: str) -> str:
    """The shape of an error, with the noise taken out."""
    cleaned = (text or "").strip().lower()
    for pattern, replacement in _NORMALISERS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned.strip()[:400]


def fingerprint(text: str) -> str:
    """A short, stable digest of the shape of an error."""
    return hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()[:16]


def _row_to_note(row: sqlite3.Row) -> MemoryNote:
    return MemoryNote(
        id=row["id"],
        project=row["project"],
        status=row["status"],
        fingerprint=row["fingerprint"],
        summary=row["summary"],
        detail=row["detail"],
        subject=row["subject"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        attempts=row["attempts"],
    )


def record(
    conn: sqlite3.Connection,
    project: str,
    summary: str,
    detail: str = "",
    *,
    subject: str = "",
    policy: privacy.PrivacyPolicy | None = None,
) -> MemoryNote:
    """Write a failure down, or count another attempt at a known one."""
    screen = policy or privacy.PrivacyPolicy()
    safe_summary, _ = screen.redact(summary or "")
    safe_detail, _ = screen.redact(detail or "")
    safe_subject, _ = screen.redact(subject or "")
    mark = fingerprint(f"{safe_summary}\n{safe_detail}")
    now = time.time()

    row = conn.execute(
        "SELECT * FROM memory_notes WHERE project=? AND fingerprint=?",
        (project, mark),
    ).fetchone()
    if row is not None:
        attempts = int(row["attempts"]) + 1
        status = "resolved" if row["status"] == "resolved" else "attempted"
        conn.execute(
            "UPDATE memory_notes SET attempts=?, status=?, detail=?, subject=?,"
            " updated_at=? WHERE id=?",
            (attempts, status, safe_detail, safe_subject, now, row["id"]),
        )
        conn.execute(
            "INSERT INTO memory_attempts(note_id, attempt, status, note, at)"
            " VALUES(?,?,?,?,?)",
            (row["id"], attempts, status, safe_detail, now),
        )
        conn.commit()
        return _row_to_note(conn.execute(
            "SELECT * FROM memory_notes WHERE id=?", (row["id"],)).fetchone())

    note_id = uuid.uuid4().hex[:10]
    conn.execute(
        "INSERT INTO memory_notes(id, project, status, fingerprint, summary,"
        " detail, subject, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (note_id, project, "investigating", mark, safe_summary, safe_detail,
         safe_subject, now, now),
    )
    conn.execute(
        "INSERT INTO memory_attempts(note_id, attempt, status, note, at)"
        " VALUES(?,?,?,?,?)",
        (note_id, 1, "investigating", safe_detail, now),
    )
    conn.commit()
    return _row_to_note(conn.execute(
        "SELECT * FROM memory_notes WHERE id=?", (note_id,)).fetchone())


def resolve_subject(conn: sqlite3.Connection, project: str, subject: str) -> int:
    """Mark the notes of a subject as solved when it finally worked."""
    if not subject:
        return 0
    rows = conn.execute(
        "SELECT id FROM memory_notes WHERE project=? AND subject=? "
        "AND status<>'resolved'",
        (project, subject),
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE memory_notes SET status='resolved', updated_at=? WHERE id=?",
            (time.time(), row["id"]),
        )
    conn.commit()
    return len(rows)


def list_notes(conn: sqlite3.Connection, project: str,
                status: str = "") -> list[MemoryNote]:
    """Every note of one project, newest first."""
    if status:
        rows = conn.execute(
            "SELECT * FROM memory_notes WHERE project=? AND status=? "
            "ORDER BY updated_at DESC", (project, status)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM memory_notes WHERE project=? ORDER BY updated_at DESC",
            (project,)).fetchall()
    return [_row_to_note(row) for row in rows]


def search(conn: sqlite3.Connection, project: str, text: str,
           limit: int = 10) -> list[MemoryNote]:
    """Notes whose fingerprint or text matches ``text``."""
    mark = fingerprint(text)
    rows = conn.execute(
        "SELECT * FROM memory_notes WHERE project=? AND ("
        " fingerprint=? OR summary LIKE ? OR detail LIKE ?) "
        "ORDER BY updated_at DESC LIMIT ?",
        (project, mark, f"%{text}%", f"%{text}%", limit),
    ).fetchall()
    if rows:
        return [_row_to_note(row) for row in rows]
    needle = normalise(text)
    words = {word for word in re.findall(r"[a-z]{4,}", needle)}
    if not words:
        return []
    found = []
    for note in list_notes(conn, project):
        haystack = set(re.findall(r"[a-z]{4,}", normalise(
            f"{note.summary} {note.detail}")))
        if len(words & haystack) >= 2:
            found.append(note)
    return found[:limit]


def get(conn: sqlite3.Connection, note_id: str) -> MemoryNote | None:
    row = conn.execute(
        "SELECT * FROM memory_notes WHERE id=?", (note_id,)).fetchone()
    return _row_to_note(row) if row else None


def attempts(conn: sqlite3.Connection, note_id: str) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT * FROM memory_attempts WHERE note_id=? ORDER BY attempt",
        (note_id,)))


def delete(conn: sqlite3.Connection, note_id: str) -> bool:
    """Remove one note and its attempts."""
    row = conn.execute(
        "SELECT id FROM memory_notes WHERE id=?", (note_id,)).fetchone()
    if row is None:
        return False
    conn.execute("DELETE FROM memory_attempts WHERE note_id=?", (note_id,))
    conn.execute("DELETE FROM memory_notes WHERE id=?", (note_id,))
    conn.commit()
    return True


def purge(conn: sqlite3.Connection, project: str) -> int:
    """Remove every note of one project."""
    rows = conn.execute(
        "SELECT id FROM memory_notes WHERE project=?", (project,)).fetchall()
    for row in rows:
        conn.execute("DELETE FROM memory_attempts WHERE note_id=?", (row["id"],))
    conn.execute("DELETE FROM memory_notes WHERE project=?", (project,))
    conn.commit()
    return len(rows)


def for_prompt(conn: sqlite3.Connection, project: str, text: str,
               limit: int = 3) -> list[MemoryNote]:
    """The notes worth putting in front of the model for this question."""
    notes = search(conn, project, text, limit=limit)
    return [note for note in notes if note.status != "resolved"]


def format_block(notes: list[MemoryNote]) -> str:
    """The block that goes into the prompt."""
    if not notes:
        return ""
    blocks = []
    for note in notes:
        body = note.detail or note.summary
        if len(body) > 800:
            body = body[:800] + "\n... [truncated]"
        blocks.append(f"[{LABEL}] {note.summary_line()}\n{body}")
    return f"{MEMORY_OPEN}\n" + "\n\n".join(blocks) + f"\n{MEMORY_CLOSE}"


__all__ = [
    "LABEL", "MEMORY_CLOSE", "MEMORY_OPEN", "STATUSES", "MemoryNote",
    "attempts", "delete", "fingerprint", "for_prompt", "format_block", "get",
    "list_notes", "normalise", "project_key", "purge", "record",
    "resolve_subject", "search",
]
