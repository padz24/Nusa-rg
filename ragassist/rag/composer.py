"""Stage 4: assemble the final instruction sent to the LLM (FR-10, AC-14).

Delimited blocks are used rather than free text so the boundary between trusted
instructions, retrieved project content, and the user's question is explicit.
Retrieved content is already sanitised at index time; the user question is
sanitised here as the last hop.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import sanitize
from .retriever import RetrievalResult

CONTEXT_OPEN = "<|RAG_CONTEXT|>"
CONTEXT_CLOSE = "<|/RAG_CONTEXT|>"
USER_OPEN = "<|RAG_USER|>"
USER_CLOSE = "<|/RAG_USER|>"


@dataclass
class ComposedPrompt:
    system: str
    user: str
    context: str
    used_context: bool

    def as_messages(self) -> list[dict[str, str]]:
        """Chat-completions payload shared by both the API and local runners."""
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.user},
        ]


def format_context(result: RetrievalResult, max_chars: int = 6000) -> str:
    """Render snippets as numbered, citable blocks."""
    if not result.snippets:
        return ""
    blocks: list[str] = []
    budget = max_chars
    for position, snippet in enumerate(result.snippets, start=1):
        body = snippet.content.strip()
        # Reserve room for the header so a truncated block stays parseable.
        header = f"[{position}] {snippet.path} (lines {snippet.start_line}-{snippet.end_line})"
        if len(header) + len(body) > budget:
            body = body[: max(0, budget - len(header) - 32)] + "\n... [truncated]"
        budget -= len(header) + len(body)
        blocks.append(f"{header}\n```{body}```")
        if budget <= 0:
            break
    return "\n\n".join(blocks)


def compose(
    query: str,
    system_prompt: str,
    retrieval: RetrievalResult | None = None,
    *,
    max_context_chars: int = 6000,
) -> ComposedPrompt:
    """Build the system/user message pair for one turn.

    When retrieval found nothing the question is sent unwrapped, so a small or
    empty project does not add pointless scaffolding tokens to every request.
    """
    clean_query = sanitize.sanitize_command_line(query.strip())
    clean_system = sanitize.sanitize_untrusted(system_prompt.strip())

    if retrieval is None or not retrieval.snippets:
        return ComposedPrompt(
            system=clean_system,
            user=f"{USER_OPEN}\n{clean_query}\n{USER_CLOSE}",
            context="",
            used_context=False,
        )

    context = format_context(retrieval, max_context_chars)
    user = (
        f"{CONTEXT_OPEN}\n{context}\n{CONTEXT_CLOSE}\n\n"
        f"Use the project excerpts above when they are relevant. "
        f"Cite them as [path:line].\n\n"
        f"{USER_OPEN}\n{clean_query}\n{USER_CLOSE}"
    )
    return ComposedPrompt(
        system=clean_system, user=user, context=context, used_context=True
    )