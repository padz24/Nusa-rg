"""Core Engine: orchestrates retrieval, prompt composition, and generation.

This is the single place where the RAG module and the LLM clients meet, which
is what NFR-06/AC-27 asks for: swapping the LLM client must not require any
change to indexing or retrieval code.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Sequence

from .config import Config
from . import evidence as evidence_mod
from . import llm
from . import memory as memory_mod
from . import privacy as privacy_mod
from . import style as style_mod
from .llm.base import LLMError, LLMResponse, Usage
from .logging_setup import audit, log_event
from .rag import ComposedPrompt, ProjectIndex, RetrievalResult, compose, retrieve


@dataclass
class TurnResult:
    """Everything the CLI needs to render one completed turn."""

    answer: str
    prompt: ComposedPrompt
    retrieval: RetrievalResult
    response: LLMResponse
    privacy_notes: list[str] = field(default_factory=list)

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
                "no project path given. Usage: nusa-rg index /path/to/project"
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
            skip_retrieval: bool = False, style: str | None = None,
            command_output: str = "",
            history: Sequence[dict[str, str]] | None = None,
            confirm: Callable[[list], bool] | None = None,
            on_retrieval=None, on_token=None) -> TurnResult:
        """Run one full turn: retrieve -> compose -> generate (FR-10).

        Retrieval is skipped automatically when no project has been indexed, so
        a fresh install can still answer general questions. ``style`` overrides
        the configured ``response_style`` for this turn; ``command_output`` is
        terminal output the user captured with ``!command``.

        ``history`` carries the prior user/assistant turns of a resumed
        session, oldest first; retrieval and command output still describe the
        current turn only. ``confirm`` is asked before a context that held a
        secret is sent on. ``on_retrieval`` (if given) fires with the retrieval
        result as soon as it is ready, and ``on_token`` switches generation to
        incremental streaming: every text delta is handed to the callback while
        the full text still comes back in the ``TurnResult``. Providers without
        SSE support quietly fall back to a whole-answer call (AC-41).
        """
        retrieval = RetrievalResult(query=query)
        root = ""
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

        if on_retrieval is not None:
            on_retrieval(retrieval)

        # The privacy firewall decides what may leave the device. A file marked
        # local-only is dropped from the context before it is composed, and a
        # secret is redacted or the request is refused.
        policy = privacy_mod.PrivacyPolicy.from_config(self.config)
        external = str(self.config.get("model_provider", "external")).lower() != "local"
        notes: list[str] = []
        if retrieval.snippets:
            kept = []
            for snippet in retrieval.snippets:
                if external and policy.is_local_only(snippet.path, root):
                    notes.append(f"{snippet.path} is local-only and was not sent")
                    continue
                cleaned, matches = policy.redact(snippet.content)
                if matches:
                    notes.append(
                        f"a secret in {snippet.path} was replaced with a mask")
                snippet.content = cleaned
                kept.append(snippet)
            retrieval.snippets = kept

        base_system = str(self.config.get("system_prompt", "") or "")
        effective_style = style or str(
            self.config.get("response_style", "default") or "default")

        evidence_items = evidence_mod.build(retrieval.snippets, self.index.conn, root)
        evidence_block = evidence_mod.format_block(evidence_items) if root else ""
        memory_block = ""
        if root:
            try:
                notes_memory = memory_mod.for_prompt(
                    self.index.conn, memory_mod.project_key(root), query)
                memory_block = memory_mod.format_block(notes_memory)
            except Exception:  # noqa: BLE001 - memory must never block a turn
                memory_block = ""

        prompt = compose(
            query,
            system_prompt=style_mod.apply(base_system, effective_style),
            retrieval=retrieval,
            command_output=command_output,
            evidence=evidence_block,
            memory=memory_block,
            evidence_instructions=evidence_mod.INSTRUCTIONS,
        )

        screened = policy.screen(prompt.user, external=external, confirm=confirm)
        if not screened.ok:
            # Fail closed: the request is not sent.
            raise LLMError(screened.reason)
        if screened.matches:
            notes.append(
                f"{len(screened.matches)} secret(s) in the context were masked")
        prompt = replace(prompt, user=screened.text)

        # Resolved through the module so an alternative client can be
        # substituted without touching any RAG code (AC-27).
        client = llm.build_client(self.config, gate=self._gate(policy, external, confirm))
        log_event("llm.generate", provider=client.name, context=prompt.used_context)
        history_options = {"history": history} if history else {}
        if on_token is not None and client.supports_stream():
            parts: list[str] = []
            usage = Usage()

            def _remember(value: Usage) -> None:
                nonlocal usage
                usage = value

            for delta in client.iter_stream(prompt.user, context="",
                                            system=prompt.system,
                                            on_usage=_remember,
                                            **history_options):
                parts.append(delta)
                on_token(delta)
            response = LLMResponse(
                text="".join(parts), usage=usage, provider=client.name
            )
        else:
            response = client.generate(
                prompt.user, context="", system=prompt.system, stream=stream,
                **history_options
            )
        return TurnResult(
            answer=response.text,
            prompt=prompt,
            retrieval=retrieval,
            response=response,
            privacy_notes=notes,
        )

    def _gate(self, policy: privacy_mod.PrivacyPolicy, external: bool,
              confirm: Callable[[list], bool] | None):
        """The check that runs before every provider, fallbacks included."""
        def gate(text: str, label: str = "") -> str | None:
            target = external and label != "local"
            result = policy.screen(text, external=target, confirm=confirm)
            if not result.ok:
                log_event("privacy.refused", provider=label,
                          reason=result.reason)
                return None
            return result.text
        return gate

    # ------------------------------------------------------------ diagnostics
    def health_check(self):
        """Report readiness of the active LLM path (FR-08)."""
        client = llm.build_client(self.config)
        return client.health_check()