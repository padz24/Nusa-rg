"""Proof-first answers: what was read, what was inferred, what is not known.

A snippet is a fact about the project. Everything the model says beyond it
is either an inference drawn from it or something nobody has evidence for.
This module turns the retrieval result into a labelled evidence block, so the
answer can be checked against the code it claims to describe.

The confidence of a fact is the retrieval score, rounded: a snippet the
index ranked low is a weaker basis for a claim, and the label says so.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

EVIDENCE_OPEN = "<|RAG_EVIDENCE|>"
EVIDENCE_CLOSE = "<|/RAG_EVIDENCE|>"

#: Told to the model once per turn.
INSTRUCTIONS = (
    "Label every claim with [FACT], [INFERENCE] or [UNKNOWN]. [FACT] is only "
    "for what the evidence shows, [INFERENCE] for a conclusion drawn from it, "
    "and [UNKNOWN] for anything the evidence does not cover."
)

#: Said when the index holds nothing about the question.
NO_EVIDENCE = (
    "The index holds no excerpt that shows anything about this question. "
    "Answer with [UNKNOWN] and say what would have to be read to answer it."
)

#: The three kinds of claim.
FACT = "fact"
INFERENCE = "inference"
UNKNOWN = "unknown"


@dataclass
class Evidence:
    """One piece of proof, or the record that there is none."""

    path: str
    relpath: str
    start_line: int
    end_line: int
    excerpt: str
    kind: str = FACT
    confidence: float = 0.0
    symbols: list[str] = field(default_factory=list)

    @property
    def citation(self) -> str:
        return f"{self.relpath}:{self.start_line}-{self.end_line}"

    def label(self) -> str:
        parts = [f"[{self.kind.upper()}]", self.citation]
        if self.symbols:
            parts.append("symbol=" + ",".join(self.symbols[:3]))
        parts.append(f"confidence={self.confidence:.2f}")
        return " ".join(parts)


def _symbols_for(conn: sqlite3.Connection | None, relpath: str) -> list[str]:
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT name FROM symbols WHERE relpath=? ORDER BY start_line LIMIT 6",
            (relpath,),
        ).fetchall()
    except sqlite3.Error:
        return []
    return [row["name"] for row in rows]


def build(snippets, conn: sqlite3.Connection | None = None,
          root: str = "") -> list[Evidence]:
    """Turn retrieved snippets into labelled evidence."""
    evidence: list[Evidence] = []
    for snippet in snippets:
        relpath = snippet.path
        if root:
            try:
                from pathlib import Path
                relpath = str(Path(snippet.path).relative_to(root))
            except (ValueError, OSError):
                relpath = snippet.path
        evidence.append(Evidence(
            path=snippet.path,
            relpath=relpath,
            start_line=snippet.start_line,
            end_line=snippet.end_line,
            excerpt=snippet.content.strip(),
            kind=FACT,
            confidence=max(0.0, min(1.0, float(snippet.score or 0.0))),
            symbols=_symbols_for(conn, relpath),
        ))
    return evidence


def format_block(evidence: list[Evidence]) -> str:
    """The block that goes into the prompt."""
    if not evidence:
        return f"{EVIDENCE_OPEN}\n{NO_EVIDENCE}\n{EVIDENCE_CLOSE}"
    blocks = []
    for item in evidence:
        body = item.excerpt
        if len(body) > 1200:
            body = body[:1200] + "\n... [truncated]"
        blocks.append(f"{item.label()}\n```\n{body}\n```")
    return f"{EVIDENCE_OPEN}\n" + "\n\n".join(blocks) + f"\n{EVIDENCE_CLOSE}"


__all__ = [
    "EVIDENCE_CLOSE", "EVIDENCE_OPEN", "Evidence", "FACT", "INFERENCE",
    "INSTRUCTIONS", "NO_EVIDENCE", "UNKNOWN", "build", "format_block",
]
