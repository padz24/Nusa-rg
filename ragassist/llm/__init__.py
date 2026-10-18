"""Factory that selects the execution path from configuration (FR-07, AC-30).

The client is rebuilt from ``config.yaml`` on every turn, so switching between
``external`` and ``local`` takes effect in the *next* chat session with no
reinstall and no terminal restart (AC-30, FR-11/AC-15).
"""

from __future__ import annotations

from ..config import Config
from .api_client import ApiClient
from .base import AuthenticationError, LLMClient, LLMError
from .local import LocalLLMRunner


def build_client(config: Config) -> LLMClient:
    """Return the client matching ``model_provider``.

    Raises :class:`LLMError` subclasses with actionable messages so the CLI can
    print them verbatim (AC-10).
    """
    provider = str(config.get("model_provider", "external")).lower()

    if provider == "local":
        model_path = str(config.get("local_model_path", "") or "")
        if not model_path:
            raise LLMError(
                "model_provider is 'local' but local_model_path is empty. Set it "
                "with: rag-assist config set local_model_path /path/to/model.gguf"
            )
        return LocalLLMRunner(
            model_path=model_path,
            binary=str(config.get("local_llama_bin", "llama-cli") or "llama-cli"),
            ctx_size=int(config.get("local_ctx_size", 4096) or 4096),
            threads=config.get("local_threads"),
            temperature=float(config.get("temperature", 0.2) or 0.0),
            timeout=int(config.get("request_timeout", 600) or 600),
        )

    # External path. Allow the URL to imply the provider when no key is set yet.
    base_url = config.provider_base_url()
    api_key = config.get("api_key", "") or ""
    if not api_key:
        # FR-08/AC-10: fail before sending a request that is guaranteed to be
        # rejected, and tell the user exactly how to fix it.
        raise AuthenticationError(
            "no API key configured. Run: rag-assist config set api_key --secret"
        )
    return ApiClient(
        base_url=base_url,
        api_key=api_key,
        model=str(config.get("api_model", "gpt-4o-mini") or "gpt-4o-mini"),
        timeout=int(config.get("request_timeout", 60) or 60),
        temperature=float(config.get("temperature", 0.2) or 0.0),
        max_tokens=_optional_int(config.get("max_tokens")),
    )


def _optional_int(value) -> int | None:
    """Coerce a config value to int, treating blank/None as 'provider default'."""
    if value in (None, "", 0):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["build_client", "ApiClient", "LocalLLMRunner", "LLMClient", "LLMError"]