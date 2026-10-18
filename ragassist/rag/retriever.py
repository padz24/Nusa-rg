"""Stage 3: turn a user query into ranked snippets (FR-10, AC-13).

Wraps :class:`~ragassist.rag.index.ProjectIndex` with timing instrumentation
so the CLI can report the sub-2-second retrieval budget from NFR-02.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from .index import ProjectIndex


@dataclass
class Snippet:
    """One retrieved chunk plus the metadata needed to cite it."""

    path: str
    start_line: int
    end_line: int
    content: str
    score: float = 0.0

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"

    def as_dict(self) -> dict:
        """Shape required by the ``RAG.retrieve()`` contract in AGENS.md."""
        return {
            "snippet": self.content,
            "score": self.score,
            "source": self.location,
        }


@dataclass
class RetrievalResult:
    snippets: list[Snippet] = field(default_factory=list)
    duration: float = 0.0
    query: str = ""

    def __bool__(self) -> bool:
        return bool(self.snippets)

    def __len__(self) -> int:
        return len(self.snippets)

    def as_dict(self) -> dict:
        """``{snippets: [str], scores: [float], sources: [str]}``."""
        return {
            "snippets": [s.content for s in self.snippets],
            "scores": [s.score for s in self.snippets],
            "sources": [s.location for s in self.snippets],
        }


def _display_path(path: str, root: str) -> str:
    """Shorten absolute paths to project-relative ones for cleaner prompts."""
    if not root:
        return path
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return path


def retrieve(
    query: str,
    index: ProjectIndex,
    *,
    limit: int = 3,
    root: str | None = None,
) -> RetrievalResult:
    """Return the top-``limit`` snippets for ``query``.

    FTS5's ``bm25`` returns a *lower-is-better* score; it is converted to a
    positive relevance so the ordering stays ascending while the reported
    number is meaningful.
    """
    started = time.perf_counter()
    rows = index.search(query, limit=limit)
    root = root or index.project_root

    snippets = []
    for row in rows:
        raw = float(row["score"] or 0.0)
        snippets.append(
            Snippet(
                path=_display_path(row["path"], root),
                start_line=row["start_line"],
                end_line=row["end_line"],
                content=row["content"],
                # bm25 is negative-ish; map to (0, 1] where 1 is the best hit.
                score=round(1.0 / (1.0 + abs(raw)), 4),
            )
        )

    return RetrievalResult(
        snippets=snippets, duration=time.perf_counter() - started, query=query
    )