"""Stage 4: assemble the final instruction sent to the LLM (FR-10, AC-14).

Delimited blocks are used rather than free text so the boundary between trusted
instructions, retrieved project content, and the user's question is explicit.
Retrieved content is already sanitised at index time; the user question is
sanitised here as the last hop.

Two more blocks travel with it. The evidence block says what was actually
read, so the answer can be checked against it, and the memory block carries
what already failed before, so the same dead end is not walked into twice.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import sanitize
from .retriever import RetrievalResult

CONTEXT_OPEN = "<|RAG_CONTEXT|>"
CONTEXT_CLOSE = "<|/RAG_CONTEXT|>"
COMMAND_OPEN = "<|RAG_COMMAND|>"
COMMAND_CLOSE = "<|/RAG_COMMAND|>"
USER_OPEN = "<|RAG_USER|>"
USER_CLOSE = "<|/RAG_USER|>"


@dataclass
class ComposedPrompt:
    system: str
    user: str
    context: str
    used_context: bool
    evidence: str = ""

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


def format_command(output: str, max_chars: int) -> str:
    """Clip command output to the prompt budget, keeping head and tail."""
    body = output.strip()
    if len(body) <= max_chars:
        return body
    keep = max_chars // 2
    return f"{body[:keep]}\n... [output trimmed] ...\n{body[-keep:]}"


def compose(
    query: str,
    system_prompt: str,
    retrieval: RetrievalResult | None = None,
    *,
    command_output: str = "",
    evidence: str = "",
    memory: str = "",
    evidence_instructions: str = "",
    max_context_chars: int = 6000,
    max_command_chars: int = 8000,
) -> ComposedPrompt:
    """Build the system/user message pair for one turn.

    Blocks are only added when they carry something: a project with no index
    and no command run gets a bare question, so no turn pays for empty
    scaffolding tokens.
    """
    clean_query = sanitize.sanitize_command_line(query.strip())
    clean_system = sanitize.sanitize_untrusted(system_prompt.strip())

    used_context = bool(retrieval is not None and retrieval.snippets)
    clean_command = (
        sanitize.sanitize_untrusted(format_command(command_output, max_command_chars))
        if command_output.strip() else ""
    )
    if not used_context and not clean_command:
        return ComposedPrompt(
            system=clean_system,
            user=f"{USER_OPEN}\n{clean_query}\n{USER_CLOSE}",
            context="",
            used_context=False,
        )

    parts: list[str] = []
    context = ""
    if used_context:
        context = format_context(retrieval, max_context_chars)
        parts.append(
            f"{CONTEXT_OPEN}\n{context}\n{CONTEXT_CLOSE}\n\n"
            "Use the project excerpts above when they are relevant. "
            "Cite them as [path:line]."
        )
    if evidence:
        parts.append(f"{evidence}\n\n{evidence_instructions}".strip())
    if memory:
        parts.append(
            f"{memory}\n\n"
            "The block above holds what already failed before. Do not repeat a "
            "dead end without saying why it was different."
        )
    if clean_command:
        parts.append(
            f"{COMMAND_OPEN}\n{clean_command}\n{COMMAND_CLOSE}\n\n"
            "The command output above came from the user's terminal. "
            "Use it when it is relevant."
        )
    parts.append(f"{USER_OPEN}\n{clean_query}\n{USER_CLOSE}")

    return ComposedPrompt(
        system=clean_system,
        user="\n\n".join(parts),
        context=context,
        used_context=used_context,
        evidence=evidence,
    )