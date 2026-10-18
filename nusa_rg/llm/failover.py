"""Try each configured provider in order until one answers (FR-07 extension).

``fallback_providers`` exists because one upstream being down or rate limiting
a key turns into a dead session. The chain is explicit configuration, not
automatic routing: only the providers named there are tried, in order, and the
error raised at the end lists what each one said.
"""

from __future__ import annotations

from typing import Iterator

from .base import LLMClient, LLMError, LLMResponse


class FailoverClient(LLMClient):
    """A client made of an ordered list of ``(label, client)`` pairs."""

    name = "failover"

    def __init__(self, clients: list[tuple[str, LLMClient]]):
        if not clients:
            raise LLMError("a failover chain needs at least one client")
        self.clients = clients

    @property
    def labels(self) -> list[str]:
        return [label for label, _ in self.clients]

    @staticmethod
    def _streams(client: LLMClient) -> bool:
        supports = getattr(client, "supports_stream", None)
        return bool(supports and supports())

    def generate(
        self,
        prompt: str,
        *,
        context: str = "",
        system: str = "",
        stream: bool = False,
    ) -> LLMResponse:
        failures: list[tuple[str, LLMError]] = []
        for position, (label, client) in enumerate(self.clients):
            try:
                response = client.generate(
                    prompt, context=context, system=system, stream=stream
                )
            except LLMError as exc:
                failures.append((label, exc))
                continue
            if position:
                response.used_fallback = True
            # A client that reports no provider name of its own gets its
            # chain label, so callers can say who answered.
            response.provider = response.provider or label
            return response

        detail = "; ".join(f"{label}: {exc}" for label, exc in failures)
        raise LLMError(f"every provider in the chain failed -- {detail}")

    # ------------------------------------------------------------- streaming
    def supports_stream(self) -> bool:
        return any(self._streams(client) for _, client in self.clients)

    def iter_stream(self, prompt: str, *, context: str = "",
                    system: str = "") -> Iterator[str]:
        """Stream from the first provider that produces a delta.

        A provider that fails *before* its first delta is skipped and the next
        one is tried; once text has been emitted the chain commits to that
        provider, because switching mid-answer would splice two completions.
        """
        failures: list[tuple[str, LLMError]] = []
        for label, client in self.clients:
            if not self._streams(client):
                continue
            started = False
            try:
                for delta in client.iter_stream(prompt, context=context,
                                                system=system):
                    started = True
                    yield delta
            except LLMError as exc:
                if started:
                    raise
                failures.append((label, exc))
                continue
            return

        detail = "; ".join(f"{label}: {exc}" for label, exc in failures)
        raise LLMError(f"every provider in the chain failed -- {detail}")

    def health_check(self) -> tuple[bool, str]:
        first_failure = ""
        for position, (label, client) in enumerate(self.clients):
            try:
                ok, message = client.health_check()
            except LLMError as exc:
                ok, message = False, str(exc)
            if ok:
                if position and first_failure:
                    return True, f"{label}: {message} (first choice failed: {first_failure})"
                return True, f"{label}: {message}"
            if not first_failure:
                first_failure = f"{label}: {message}"
        return False, first_failure or "no provider in the chain is reachable"

    def close(self) -> None:
        for _, client in self.clients:
            client.close()


__all__ = ["FailoverClient"]
