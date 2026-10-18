"""Common contract for both LLM execution paths (NFR-06).

``ApiClient`` and ``LocalLLMRunner`` are interchangeable behind
:class:`LLMClient`, which is what lets AC-30 switch providers through config
without touching the RAG module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator


class LLMError(RuntimeError):
    """Base class for recoverable LLM failures."""


class ProviderUnavailableError(LLMError):
    """Network unreachable, DNS failure, or connection refused (FR-08, AC-10)."""


class AuthenticationError(LLMError):
    """API key missing, malformed, or rejected by the provider (FR-08, AC-10)."""


class RateLimitError(LLMError):
    """Provider returned 429; carries the retry delay when advertised."""


class LocalModelError(LLMError):
    """llama.cpp binary missing, or the GGUF model failed to load."""


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }


@dataclass
class LLMResponse:
    """Matches the ``LLM.generate()`` output contract in AGENS.md."""

    text: str
    usage: Usage = field(default_factory=Usage)
    provider: str = ""
    used_fallback: bool = False

    def as_dict(self) -> dict:
        return {"text": self.text, "usage": self.usage.as_dict()}


class LLMClient(ABC):
    """Interface implemented by every execution path."""

    name: str = "base"

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        context: str = "",
        system: str = "",
        stream: bool = False,
    ) -> LLMResponse:
        """Produce a completion for ``prompt``.

        ``context`` is the retrieved project text and ``system`` the configured
        persona; implementations decide whether to embed or forward them.
        """

    def supports_stream(self) -> bool:
        """True when :meth:`iter_stream` can produce incremental deltas."""
        return False

    def iter_stream(self, prompt: str, *, context: str = "",
                    system: str = "") -> Iterator[str]:
        """Yield text deltas as they arrive (AC-41).

        Clients whose backend cannot stream incrementally leave
        ``supports_stream`` at ``False``; callers then use ``generate`` and
        render the answer whole.
        """
        raise LLMError(f"{self.name} does not support streaming")

    def health_check(self) -> tuple[bool, str]:
        """Return ``(ok, message)`` describing readiness (FR-08)."""
        return True, f"{self.name} ready"

    def close(self) -> None:  # pragma: no cover - most clients hold nothing
        return None