"""Stage 2: chunk files and persist them in a SQLite FTS5 index.

Design notes
------------
* **Two tables.** ``chunks`` holds the payload and metadata with rowids that
  stay stable across re-indexing; ``chunks_fts`` is an external-content FTS5
  mirror queried with ``MATCH``. Keeping them separate avoids the known FTS5
  delete-by-rowid awkwardness and makes crash recovery (NFR-04) a simple
  "delete rows whose path no longer exists" pass.
* **WAL + transactional writes.** A force-close during indexing leaves the
  database loadable rather than half-written, satisfying AC-21.
* **Mtime skip.** Unchanged files are not re-read, so incremental re-indexing
  is cheap on a phone.
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .. import paths, sanitize
from .scanner import ScanResult, ScannedFile, scan

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS files (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    path      TEXT NOT NULL UNIQUE,
    relpath   TEXT NOT NULL,
    mtime     REAL NOT NULL,
    size      INTEGER NOT NULL,
    chunks    INTEGER NOT NULL DEFAULT 0,
    indexed_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id       INTEGER PRIMARY KEY,
    file_id  INTEGER NOT NULL,
    path     TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line   INTEGER NOT NULL,
    content  TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    path UNINDEXED,
    start_line UNINDEXED,
    end_line UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


@dataclass
class IndexStats:
    files_indexed: int = 0
    files_skipped: int = 0
    files_unchanged: int = 0
    files_removed: int = 0
    chunks: int = 0
    duration: float = 0.0
    root: str = ""
    scanned: int = 0

    def summary(self) -> str:
        return (
            f"indexed {self.files_indexed} file(s), {self.chunks} chunk(s) in "
            f"{self.duration:.2f}s ({self.files_unchanged} unchanged, "
            f"{self.files_skipped} skipped, {self.files_removed} removed)"
        )


@dataclass
class IndexEvent:
    """Progress ping emitted while indexing (phase, done, total, detail).

    Phases: ``scan`` (walking the tree), ``planned`` (file list is known),
    ``file`` (one scanned file processed, including skipped ones), ``done``.
    """

    phase: str
    done: int = 0
    total: int = 0
    detail: str = ""


def _fts_query_escape(text: str) -> str:
    """Turn free user text into a safe FTS5 MATCH expression.

    FTS5 treats a long run of punctuation as a syntax error, and query text is
    attacker-influenced via filenames/snippets, so every token is quoted and
    stripped of FTS operators rather than interpolated raw.
    """
    tokens = []
    for raw in sanitize.sanitize_untrusted(text).split():
        cleaned = raw.strip('"\'(){}[]*^-:,').replace('"', "")
        if cleaned:
            tokens.append(f'"{cleaned}"')
    return " OR ".join(tokens)


def chunk_lines(
    lines: list[str], size: int = 60, overlap: int = 10
) -> Iterator[tuple[int, int, str]]:
    """Yield ``(start_line, end_line, text)`` windows over ``lines`` (1-based).

    Overlap keeps a function split across a boundary retrievable from either
    side, which materially helps the top-3 relevance target in AC-29.
    """
    if not lines:
        return
    size = max(1, size)
    overlap = min(max(0, overlap), size - 1)
    step = size - overlap
    total = len(lines)
    start = 0
    while start < total:
        end = min(start + size, total)
        block = "".join(lines[start:end])
        if block.strip():
            yield start + 1, end, block
        if end == total:
            break
        start += step


class ProjectIndex:
    """SQLite FTS5-backed index for one or more project roots."""

    def __init__(self, db_path: str | os.PathLike[str] | None = None):
        self.db_path = Path(db_path) if db_path else paths.index_db_path()
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------ lifecycle
    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)
            # SEC-04: index is owner-readable only.
            paths.restrict(self.db_path)
            paths.restrict(self.db_path.with_name(self.db_path.name + "-wal"))
            paths.restrict(self.db_path.with_name(self.db_path.name + "-shm"))
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "ProjectIndex":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------ metadata
    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    @property
    def project_root(self) -> str:
        return self.get_meta("project_root", "") or ""

    def clear(self) -> None:
        """Drop every indexed file. Used when switching project roots."""
        self.conn.executescript(
            "DELETE FROM chunks_fts; DELETE FROM chunks; DELETE FROM files;"
        )
        self.conn.commit()

    # ------------------------------------------------------------- indexing
    def _known(self) -> dict[str, sqlite3.Row]:
        return {row["path"]: row for row in self.conn.execute("SELECT * FROM files")}

    def _remove(self, path: str) -> None:
        # chunks_fts stores its own copy of `path`, so both tables can be
        # pruned with an equality filter on that column.
        self.conn.execute("DELETE FROM chunks_fts WHERE path=?", (path,))
        self.conn.execute("DELETE FROM chunks WHERE path=?", (path,))
        self.conn.execute("DELETE FROM files WHERE path=?", (path,))

    def _index_file(self, entry: ScannedFile, chunk_size: int, overlap: int) -> int:
        mtime = os.path.getmtime(entry.path)
        row = self.conn.execute("SELECT id FROM files WHERE path=?", (entry.path,)).fetchone()
        if row is None:
            cur = self.conn.execute(
                "INSERT INTO files(path, relpath, mtime, size, chunks, indexed_at) "
                "VALUES(?,?,?,?,0,?)",
                (entry.path, entry.relpath, mtime, entry.size, time.time()),
            )
            file_id = cur.lastrowid
        else:
            # Keep the id stable so existing chunk rows stay consistent.
            file_id = row["id"]
            self.conn.execute(
                "UPDATE files SET relpath=?, mtime=?, size=?, indexed_at=? WHERE id=?",
                (entry.relpath, mtime, entry.size, time.time(), file_id),
            )

        # Remove prior chunks for this file so re-indexing never duplicates.
        self.conn.execute("DELETE FROM chunks_fts WHERE path=?", (entry.path,))
        self.conn.execute("DELETE FROM chunks WHERE path=?", (entry.path,))

        try:
            text = Path(entry.path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return 0

        count = 0
        for start_line, end_line, block in chunk_lines(
            text.splitlines(keepends=True), chunk_size, overlap
        ):
            # Untrusted project text is neutralised before storage.
            safe = sanitize.sanitize_untrusted(block)
            cur = self.conn.execute(
                "INSERT INTO chunks(file_id, path, start_line, end_line, content) "
                "VALUES(?,?,?,?,?)",
                (file_id, entry.path, start_line, end_line, safe),
            )
            self.conn.execute(
                "INSERT INTO chunks_fts(rowid, content, path, start_line, end_line) "
                "VALUES(?,?,?,?,?)",
                (cur.lastrowid, safe, entry.path, start_line, end_line),
            )
            count += 1

        self.conn.execute("UPDATE files SET chunks=? WHERE id=?", (count, file_id))
        return count

    def index(
        self,
        root: str | os.PathLike[str],
        *,
        ignore_dirs: Iterable[str] = (),
        ignore_globs: Iterable[str] = (),
        max_file_bytes: int = 2 * 1024 * 1024,
        chunk_size: int = 60,
        overlap: int = 10,
        force: bool = False,
        on_event: Callable[[IndexEvent], None] | None = None,
    ) -> IndexStats:
        """Scan ``root`` and index its text files.

        Switching to a different project root clears the previous index, so the
        assistant never retrieves snippets from an unrelated directory.
        ``on_event`` receives :class:`IndexEvent` pings; it is only wired up
        when a caller (the CLI) wants a progress display.
        """
        emit = on_event or (lambda event: None)
        started = time.perf_counter()
        emit(IndexEvent("scan", 0, 0, str(root)))
        result: ScanResult = scan(
            root,
            ignore_dirs=frozenset(ignore_dirs),
            ignore_globs=list(ignore_globs),
            max_file_bytes=max_file_bytes,
        )
        stats = IndexStats(root=result.root, scanned=len(result.files))
        stats.files_skipped = result.skipped
        total_files = len(result.files)
        emit(IndexEvent("planned", 0, total_files))

        previous_root = self.project_root
        if previous_root and previous_root != result.root:
            self.clear()
        self.set_meta("project_root", result.root)
        self.set_meta("last_indexed_at", str(time.time()))

        known = {} if force else self._known()

        for position, entry in enumerate(result.files, start=1):
            emit(IndexEvent("file", position, total_files, entry.relpath))
            row = known.get(entry.path)
            unchanged = (
                row is not None
                and abs(row["mtime"] - os.path.getmtime(entry.path)) < 1e-6
                and row["size"] == entry.size
            )
            if unchanged:
                stats.files_unchanged += 1
                continue
            stats.chunks += self._index_file(entry, chunk_size, overlap)
            stats.files_indexed += 1

        # Drop files that vanished since the last run (keeps re-index idempotent).
        current = {entry.path for entry in result.files}
        for stale in set(known) - current:
            self._remove(stale)
            stats.files_removed += 1

        # One commit per batch keeps the transaction window small (AC-21).
        self.conn.commit()
        stats.duration = time.perf_counter() - started
        emit(IndexEvent("done", total_files, total_files))
        return stats

    # ------------------------------------------------------------ retrieval
    def search(self, query: str, limit: int = 3) -> list[sqlite3.Row]:
        """Return the ``limit`` best-matching chunks for ``query`` (AC-13)."""
        match = _fts_query_escape(query)
        if not match:
            return []
        try:
            return list(
                self.conn.execute(
                    "SELECT c.id, c.path, c.start_line, c.end_line, c.content, "
                    "       bm25(chunks_fts) AS score "
                    "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
                    "WHERE chunks_fts MATCH ? "
                    "ORDER BY score LIMIT ?",
                    (match, max(1, limit)),
                )
            )
        except sqlite3.OperationalError:
            # A malformed MATCH expression must never break the chat session.
            return []

    def count(self) -> tuple[int, int]:
        files = self.conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
        chunks = self.conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()["c"]
        return files, chunks