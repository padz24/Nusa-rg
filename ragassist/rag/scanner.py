"""Stage 1 of the RAG pipeline: walk a project and select indexable files.

Keeps the index small and fast on a phone by skipping binary files, oversized
files, vendored directories, and anything matched by an ignore glob.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path

#: Extensions treated as source/text by default (AC-11). An empty
#: ``text_extensions`` in config falls back to this set.
DEFAULT_TEXT_EXTENSIONS = frozenset({
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh",
    ".java", ".kt", ".kts", ".go", ".rs", ".rb", ".php", ".swift",
    ".sh", ".bash", ".zsh", ".fish", ".ps1",
    ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env",
    ".xml", ".md", ".markdown", ".rst", ".txt", ".sql", ".gradle",
    ".dart", ".lua", ".pl", ".r", ".jl", ".ex", ".exs", ".scala",
})

#: Sniffed to avoid indexing binaries that merely carry a text-ish extension.
_BINARY_SNIFF_BYTES = 8192


@dataclass
class ScannedFile:
    path: str
    size: int
    relpath: str


@dataclass
class ScanResult:
    files: list[ScannedFile] = field(default_factory=list)
    skipped: int = 0
    root: str = ""


def looks_binary(path: Path, sniff: int = _BINARY_SNIFF_BYTES) -> bool:
    """True when the file contains NUL bytes in its first ``sniff`` bytes."""
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(sniff)
    except OSError:
        return True


def scan(
    root: str | os.PathLike[str],
    *,
    ignore_dirs: frozenset[str] | set[str] | list[str] = frozenset(),
    ignore_globs: list[str] | None = None,
    max_file_bytes: int = 2 * 1024 * 1024,
    text_extensions: frozenset[str] | set[str] | None = None,
) -> ScanResult:
    """Collect indexable text files under ``root`` (AC-11).

    Hidden directories are skipped along with the configured ignore list so a
    ``.git`` or ``.venv`` tree never bloats the index.
    """
    root_path = Path(root).expanduser().resolve()
    result = ScanResult(root=str(root_path))
    if not root_path.exists():
        raise FileNotFoundError(f"project path does not exist: {root_path}")
    if root_path.is_file():
        result.files.append(ScannedFile(str(root_path), root_path.stat().st_size, root_path.name))
        return result

    ignore_dirs = set(ignore_dirs)
    ignore_globs = list(ignore_globs or [])
    extensions = frozenset(text_extensions) if text_extensions else DEFAULT_TEXT_EXTENSIONS

    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in ignore_dirs and not (d.startswith(".") and d not in {".", ".."})
        )
        for name in sorted(filenames):
            candidate = Path(dirpath) / name
            relpath = os.path.relpath(candidate, root_path)

            if candidate.suffix.lower() not in extensions:
                result.skipped += 1
                continue
            if any(fnmatch.fnmatch(relpath, g) or fnmatch.fnmatch(name, g) for g in ignore_globs):
                result.skipped += 1
                continue
            try:
                size = candidate.stat().st_size
            except OSError:
                result.skipped += 1
                continue
            if size == 0 or size > max_file_bytes:
                result.skipped += 1
                continue
            if looks_binary(candidate):
                result.skipped += 1
                continue

            result.files.append(ScannedFile(str(candidate), size, relpath))

    return result