"""Core Engine: orchestrates retrieval, prompt composition, and generation.

This is the single place where the RAG module and the LLM clients meet, which
is what NFR-06/AC-27 asks for: swapping the LLM client must not require any
change to indexing or retrieval code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config
from . import llm
from .llm.base import LLMResponse
from .logging_setup import audit, log_event
from .rag import ComposedPrompt, ProjectIndex, RetrievalResult, compose, retrieve


@dataclass
class TurnResult:
    """Everything the CLI needs to render one completed turn."""

    answer: str
    prompt: ComposedPrompt
    retrieval: RetrievalResult
    response: LLMResponse

    @property
    def total_latency(self) -> float:
        return self.retrieval.duration


class CoreEngine:
    """Coordinates configuration, the index, and the active LLM client."""

    def __init__(
        self,
        config: Config | None = None,
        index: ProjectIndex | None = None,
    ):
        self.config = config or Config()
        self._index = index

    # ------------------------------------------------------------- resources
    @property
    def index(self) -> ProjectIndex:
        """Lazily open the shared index handle."""
        if self._index is None:
            self._index = ProjectIndex()
        return self._index

    def close(self) -> None:
        if self._index is not None:
            self._index.close()
            self._index = None

    # -------------------------------------------------------------- indexing
    def index_project(self, root: str | None = None, *, force: bool = False):
        """Index a project directory and record it as the default path."""
        target = root or self.config.project_path()
        if not target:
            raise ValueError(
                "no project path given. Usage: rag-assist index /path/to/project"
            )
        resolved = str(Path(target).expanduser().resolve())

        log_event("index.start", root=resolved)
        stats = self.index.index(
            resolved,
            ignore_dirs=self.config.ignore_dirs(),
            ignore_globs=self.config.get("ignore_globs", []) or [],
            max_file_bytes=int(self.config.get("max_file_bytes", 2 * 1024 * 1024)),
            chunk_size=int(self.config.get("chunk_lines", 60)),
            overlap=int(self.config.get("chunk_overlap_lines", 10)),
            force=force,
        )
        # Remember the indexed root so later sessions need no path argument.
        self.config.set("default_project_path", resolved,
                        audit_event="index.set_default_project_path")
        audit("index.build", "SUCCESS",
              f"root={resolved} files={stats.files_indexed} chunks={stats.chunks}")
        log_event("index.done", files=stats.files_indexed, chunks=stats.chunks,
                  duration=f"{stats.duration:.3f}")
        return stats

    # -------------------------------------------------------------- chat
    def ask(self, query: str, *, stream: bool = False,
            skip_retrieval: bool = False) -> TurnResult:
        """Run one full turn: retrieve -> compose -> generate (FR-10).

        Retrieval is skipped automatically when no project has been indexed, so
        a fresh install can still answer general questions.
        """
        retrieval = RetrievalResult(query=query)
        if not skip_retrieval:
            root = self.index.project_root
            if root:
                retrieval = retrieve(
                    query,
                    self.index,
                    limit=int(self.config.get("max_context_snippets", 3) or 3),
                    root=root,
                )
                # SEC-06: log only the fingerprint and the timing, never text.
                log_event("retrieve", query=query, hits=len(retrieval.snippets),
                          duration=f"{retrieval.duration:.3f}")

        prompt = compose(
            query,
            system_prompt=str(self.config.get("system_prompt", "") or ""),
            retrieval=retrieval,
        )

        # Resolved through the module so an alternative client can be
        # substituted without touching any RAG code (AC-27).
        client = llm.build_client(self.config)
        log_event("llm.generate", provider=client.name, context=prompt.used_context)
        response = client.generate(
            prompt.user, context="", system=prompt.system, stream=stream
        )
        return TurnResult(
            answer=response.text,
            prompt=prompt,
            retrieval=retrieval,
            response=response,
        )

    # ------------------------------------------------------------ diagnostics
    def health_check(self):
        """Report readiness of the active LLM path (FR-08)."""
        client = llm.build_client(self.config)
        return client.health_check()