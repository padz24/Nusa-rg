"""External API connector for OpenAI-compatible endpoints (FR-07, FR-08).

Both OpenAI and Groq expose ``POST /v1/chat/completions`` (AGENS.md section 9),
so one implementation covers both; only the base URL and key differ.

Uses ``requests`` when available and falls back to ``urllib`` otherwise, so the
package keeps working in a bare Termux Python install.
"""

from __future__ import annotations

import json
from typing import Callable, Iterator, Sequence

from .base import (
    AuthenticationError,
    LLMClient,
    LLMResponse,
    ProviderUnavailableError,
    RateLimitError,
    Usage,
)


def _requests():
    """Import ``requests`` on demand, or ``None`` when it is not installed.

    Deferring the import keeps ``nusa-rg --help`` and ``status`` fast;
    ``requests`` plus urllib3 costs close to a second of startup on ARM64, and
    the urllib fallback below works without it.
    """
    try:
        import requests
    except ImportError:
        return None
    return requests


class ApiClient(LLMClient):
    """Chat-completions client for OpenAI / Groq."""

    name = "external-api"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "gpt-4o-mini",
        *,
        timeout: int = 60,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        name: str = "",
    ):
        if not base_url:
            raise AuthenticationError("no API base URL configured")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        if name:
            # The catalogue id ("groq", "deepseek") reads better in logs and
            # in the "[provider]" note than the generic class default.
            self.name = name

    # ------------------------------------------------------------ transport
    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(self, messages: list[dict[str, str]], stream: bool) -> dict:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": stream,
        }
        if self.max_tokens:
            body["max_tokens"] = self.max_tokens
        if stream:
            # OpenAI-compatible servers only put token counts in the final SSE
            # event when this is set. Servers that reject the field are retried
            # without it in _stream_response().
            body["stream_options"] = {"include_usage": True}
        return body

    @staticmethod
    def _messages(user: str, system: str,
                  history: Sequence[dict[str, str]] | None
                  ) -> list[dict[str, str]]:
        """Build the ordered chat payload: system, prior turns, current turn."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        for item in history or ():
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role in ("user", "assistant") and isinstance(content, str) and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user})
        return messages

    def _stream_response(self, messages: list[dict[str, str]]):
        """POST a streaming request, retrying without ``stream_options``.

        A few OpenAI-compatible servers reject unknown request fields with a
        400. The retry is safe because it happens before any body is read.
        """
        payload = self._payload(messages, stream=True)
        response = self._post(payload, stream=True)
        if (self._status(response) == 400
                and "stream_options" in self._body_text(response).lower()):
            payload.pop("stream_options", None)
            response = self._post(payload, stream=True)
        return response

    def _post(self, payload: dict, stream: bool = False):
        """POST the payload, translating transport errors into LLMError."""
        http = _requests()
        if http is not None:
            return self._post_requests(http, payload, stream)
        return self._post_urllib(payload, stream)

    def _post_requests(self, http, payload: dict, stream: bool):
        try:
            return http.post(
                self.endpoint,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
                stream=stream,
            )
        except http.exceptions.Timeout as exc:
            raise ProviderUnavailableError(
                f"request to {self.base_url} timed out after {self.timeout}s"
            ) from exc
        except http.exceptions.RequestException as exc:
            raise ProviderUnavailableError(
                f"cannot reach {self.base_url}: {exc}"
            ) from exc

    def _post_urllib(self, payload: dict, stream: bool):
        # Imported lazily: urllib pulls in ~0.4s of module loading that is
        # wasted whenever requests is available.
        import urllib.error
        import urllib.request

        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode(),
            headers=self._headers(),
            method="POST",
        )
        try:
            return urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            return exc  # caller inspects the status like a response object
        except (urllib.error.URLError, OSError) as exc:
            raise ProviderUnavailableError(
                f"cannot reach {self.base_url}: {exc}"
            ) from exc

    # ------------------------------------------------------------- handling
    @staticmethod
    def _status(response) -> int:
        """Read an HTTP status from either transport.

        ``requests.Response`` exposes ``status_code`` while ``http.client``
        responses (the urllib fallback) expose ``status``/``code``. Probing
        ``status`` alone silently returned 0 under requests, which made every
        4xx/5xx look like a success.
        """
        for attribute in ("status_code", "status", "code"):
            value = getattr(response, attribute, None)
            if isinstance(value, int):
                return value
        return 0

    @staticmethod
    def _body_text(response) -> str:
        """Return the raw response body as text for either transport.

        ``requests`` exposes ``.text``/``.content`` and has no ``read()``;
        the urllib fallback returns an ``http.client`` response with ``read()``.
        """
        if hasattr(response, "read"):
            raw = response.read()
        else:
            raw = getattr(response, "content", b"")
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return raw or ""

    def _raise_for_status(self, response) -> None:
        status = self._status(response)
        if status < 400:
            return
        detail = ""
        try:
            error = json.loads(self._body_text(response) or "{}").get("error", {})
            detail = error.get("message", "") if isinstance(error, dict) else str(error)
        except (ValueError, AttributeError, TypeError):
            # Body may be HTML, empty, or truncated; the status alone still tells
            # us enough to raise a useful error.
            pass

        if status in (401, 403):
            raise AuthenticationError(
                "the provider rejected the API key (HTTP "
                f"{status}). Set a valid key with: nusa-rg config set api_key --secret"
            )
        if status == 404:
            # Providers overload 404 for both a wrong path and a missing model;
            # Ollama cloud does exactly this, so follow the detail when given.
            if detail and "model" in detail.lower():
                raise AuthenticationError(
                    f"the provider does not know this model (HTTP 404): {detail}. "
                    f"Fix it with: nusa-rg config set api_model <model>"
                )
            raise AuthenticationError(
                f"endpoint not found (HTTP 404): {self.endpoint}. "
                "Check api_base_url in config.yaml."
            )
        if status == 429:
            raise RateLimitError(
                f"rate limited by the provider (HTTP 429). {detail}".strip()
            )
        raise ProviderUnavailableError(
            f"provider returned HTTP {status}. {detail}".strip()
        )

    def _read_json(self, response) -> dict:
        try:
            return json.loads(self._body_text(response) or "{}")
        except ValueError as exc:
            raise ProviderUnavailableError(
                "provider returned a non-JSON response"
            ) from exc

    # -------------------------------------------------------------- public
    def generate(
        self,
        prompt: str,
        *,
        context: str = "",
        system: str = "",
        stream: bool = False,
        history: Sequence[dict[str, str]] | None = None,
    ) -> LLMResponse:
        user = prompt
        if context:
            user = f"{context}\n\n{prompt}"
        messages = self._messages(user, system, history)

        if stream:
            response = self._stream_response(messages)
            self._raise_for_status(response)
            parts: list[str] = []
            usage = Usage()
            for text, event_usage in _iter_sse_events(response):
                if text:
                    parts.append(text)
                if event_usage is not None:
                    usage = event_usage
            return LLMResponse(text="".join(parts), usage=usage,
                               provider=self.name)

        response = self._post(self._payload(messages, stream), stream=stream)
        self._raise_for_status(response)

        body = self._read_json(response)
        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderUnavailableError(
                "provider response did not contain any completion"
            ) from exc

        text = message.get("content") or ""
        if not text.strip():
            # Reasoning models (e.g. Ollama's "beam") spend the first part of
            # the token budget thinking and can return an empty content field
            # when that budget runs out mid-thought. Surface what happened
            # instead of reporting a malformed response.
            text = self._explain_empty_completion(body, message)

        usage = body.get("usage") or {}
        return LLMResponse(
            text=text,
            usage=Usage(
                prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
                completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            ),
            provider=self.name,
        )

    @staticmethod
    def _explain_empty_completion(body: dict, message: dict) -> str:
        """Build a useful message for an empty completion."""
        reasoning = (message.get("reasoning") or message.get("reasoning_content") or "").strip()
        finish = ((body.get("choices") or [{}])[0] or {}).get("finish_reason", "")
        if reasoning:
            if finish == "length":
                return (
                    "The model spent its whole token budget reasoning and "
                    "produced no answer. Raise the limit with:\n"
                    "  nusa-rg config set max_tokens 4096\n\n"
                    f"Partial reasoning:\n{reasoning[:400]}"
                )
            return reasoning
        if finish == "length":
            return (
                "The response was cut off before any answer was produced. "
                "Increase max_tokens and try again:\n"
                "  nusa-rg config set max_tokens 4096"
            )
        return "The model returned an empty response."

    def supports_stream(self) -> bool:
        return True

    def iter_stream(self, prompt: str, *, context: str = "", system: str = "",
                    history: Sequence[dict[str, str]] | None = None,
                    on_usage: Callable[[Usage], None] | None = None
                    ) -> Iterator[str]:
        """Yield text deltas for a streaming completion (AC-41).

        ``on_usage`` is called once with the final token counts when the
        provider includes them in the stream. ``history`` supplies prior
        session turns, oldest first.
        """
        user = f"{context}\n\n{prompt}" if context else prompt
        messages = self._messages(user, system, history)

        response = self._stream_response(messages)
        self._raise_for_status(response)
        for text, usage in _iter_sse_events(response):
            if usage is not None and on_usage is not None:
                on_usage(usage)
            if text:
                yield text

    def health_check(self) -> tuple[bool, str]:
        """Probe the endpoint before a query is attempted (FR-08, AC-10)."""
        if not self.api_key:
            return False, (
                "no API key configured. Run: "
                "nusa-rg config set api_key --secret"
            )
        try:
            response = self._post(
                {"model": self.model, "messages": [{"role": "user", "content": "ping"}],
                 "max_tokens": 1, "stream": False},
                stream=False,
            )
        except ProviderUnavailableError as exc:
            return False, str(exc)
        status = self._status(response)
        if status == 429:
            return False, "provider is rate limiting this key right now"
        if status >= 400:
            return False, f"provider returned HTTP {status}"
        return True, f"{self.base_url} reachable, model={self.model}"


def _usage_from(event: dict) -> Usage | None:
    """Token counts carried by one SSE event, or None when absent/empty."""
    usage = event.get("usage")
    if not isinstance(usage, dict):
        return None
    try:
        prompt = int(usage.get("prompt_tokens",
                              usage.get("input_tokens", 0)) or 0)
        completion = int(usage.get("completion_tokens",
                                  usage.get("output_tokens", 0)) or 0)
    except (TypeError, ValueError):
        return None
    if not (prompt or completion):
        return None
    return Usage(prompt_tokens=prompt, completion_tokens=completion)


def _iter_sse_events(response) -> Iterator[tuple[str | None, Usage | None]]:
    """Yield ``(text, usage)`` from an SSE stream, tolerating missing streams.

    Content events carry text and no usage; the final usage event carries
    counts and no text. Providers that report neither simply omit the event.
    """
    if hasattr(response, "iter_lines"):
        # A small chunk keeps the stream live even when the server closes the
        # connection instead of using chunked transfer encoding: the default
        # 512-byte read would otherwise wait for half a kilobyte of deltas.
        iterator = response.iter_lines(chunk_size=1)
    else:  # urllib fallback: iterate lines instead of reading the whole body
        if hasattr(response, "__iter__"):
            iterator = response
        else:
            iterator = response.read().decode(errors="replace").splitlines()

    for line in iterator:
        if not line:
            continue
        if isinstance(line, bytes):
            line = line.decode(errors="replace")
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            return
        try:
            event = json.loads(payload)
        except ValueError:
            continue
        usage = _usage_from(event)
        if usage is not None:
            yield None, usage
        for choice in event.get("choices") or []:
            delta = choice.get("delta") or {}
            chunk = delta.get("content")
            if chunk:
                yield chunk, None


def _iter_sse(response) -> Iterator[str]:
    """Yield just the content deltas (callers that don't need usage)."""
    for text, _usage in _iter_sse_events(response):
        if text:
            yield text


__all__ = ["ApiClient"]