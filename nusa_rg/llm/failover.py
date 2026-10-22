"""Try each configured provider in order until one answers (FR-07 extension).

``fallback_providers`` exists because one upstream being down or rate limiting
a key turns into a dead session. The chain is explicit configuration, not
automatic routing: only the providers named there are tried, in order, and the
error raised at the end lists what each one said.
"""

from __future__ import annotations

from typing import Callable, Iterator, Sequence

from .base import LLMClient, LLMError, LLMResponse, Usage


class FailoverClient(LLMClient):
    """A client made of an ordered list of ``(label, client)`` pairs."""

    name = "failover"

    def __init__(self, clients: list[tuple[str, LLMClient]], *,
                 gate: Callable[[str, str], str | None] | None = None):
        if not clients:
            raise LLMError("a failover chain needs at least one client")
        self.clients = clients
        #: Called before every attempt with ``(prompt, provider label)``. It
        #: returns the text to send, or None to refuse that provider.
        self.gate = gate

    @property
    def labels(self) -> list[str]:
        return [label for label, _ in self.clients]

    @staticmethod
    def _streams(client: LLMClient) -> bool:
        supports = getattr(client, "supports_stream", None)
        return bool(supports and supports())

    def _gated(self, prompt: str, label: str) -> str | None:
        """The text to send to one provider, or None when it is refused."""
        if self.gate is None:
            return prompt
        return self.gate(prompt, label)

    def generate(
        self,
        prompt: str,
        *,
        context: str = "",
        system: str = "",
        stream: bool = False,
        history: Sequence[dict[str, str]] | None = None,
    ) -> LLMResponse:
        failures: list[tuple[str, LLMError]] = []
        options: dict = {"context": context, "system": system, "stream": stream}
        if history:
            options["history"] = history
        for position, (label, client) in enumerate(self.clients):
            gated = self._gated(prompt, label)
            if gated is None:
                failures.append((label, LLMError("the privacy firewall refused it")))
                continue
            try:
                response = client.generate(gated, **options)
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
                    system: str = "",
                    history: Sequence[dict[str, str]] | None = None,
                    on_usage: Callable[[Usage], None] | None = None
                    ) -> Iterator[str]:
        """Stream from the first provider that produces a delta.

        A provider that fails *before* its first delta is skipped and the next
        one is tried; once text has been emitted the chain commits to that
        provider, because switching mid-answer would splice two completions.
        Usage is reported only for the provider that actually finishes the
        stream.
        """
        failures: list[tuple[str, LLMError]] = []
        options: dict = {"context": context, "system": system}
        if history:
            options["history"] = history
        for label, client in self.clients:
            if not self._streams(client):
                continue
            gated = self._gated(prompt, label)
            if gated is None:
                failures.append((label, LLMError("the privacy firewall refused it")))
                continue
            started = False
            reported: list[Usage] = []
            try:
                for delta in client.iter_stream(gated, on_usage=reported.append,
                                                **options):
                    started = True
                    yield delta
            except LLMError as exc:
                if started:
                    raise
                failures.append((label, exc))
                continue
            if on_usage is not None and reported:
                on_usage(reported[-1])
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
