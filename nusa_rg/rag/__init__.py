"""Local Project RAG module.

Pipeline order matches AGENS.md section 8:
``scanner`` -> ``index`` (Index Builder) -> ``retriever`` -> ``composer``.
"""

from .composer import ComposedPrompt, compose, format_context
from .index import IndexEvent, IndexStats, ProjectIndex, chunk_lines
from .retriever import RetrievalResult, Snippet, retrieve
from .scanner import ScanResult, ScannedFile, scan

__all__ = [
    "ComposedPrompt",
    "compose",
    "format_context",
    "IndexEvent",
    "IndexStats",
    "ProjectIndex",
    "chunk_lines",
    "RetrievalResult",
    "Snippet",
    "retrieve",
    "ScanResult",
    "ScannedFile",
    "scan",
]