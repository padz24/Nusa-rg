"""Factory that selects the execution path from configuration (FR-07, AC-30).

The client is rebuilt from ``config.yaml`` every turn, so switching between
``external`` and ``local`` takes effect immediately (AC-30, FR-11/AC-15).

When ``fallback_providers`` names one or more catalogue entries, the primary
client is wrapped in a :class:`~nusa_rg.llm.failover.FailoverClient` that
tries them in order: a rate-limited or unreachable provider no longer ends the
session when a working alternative is configured.
"""

from __future__ import annotations

from typing import Callable
from urllib.parse import urlparse

from .. import catalog
from ..config import PROVIDERS, Config
from ..logging_setup import log_event
from .api_client import ApiClient
from .base import AuthenticationError, LLMClient, LLMError
from .failover import FailoverClient
from .local import LocalLLMRunner


def build_client(config: Config, *,
                gate: Callable[[str, str], str | None] | None = None) -> LLMClient:
    """Return the client matching the configuration, with any fallbacks.

    Raises :class:`LLMError` subclasses with actionable messages so the CLI can
    print them verbatim (AC-10). ``gate`` is the privacy check that runs
    before every provider, the fallbacks included.
    """
    provider = str(config.get("model_provider", "external")).lower()
    primary_key, primary = _build_primary(config, provider)

    chain: list[tuple[str, LLMClient]] = [(primary_key, primary)]
    for provider_id, model in config.fallback_entries():
        if provider_id == primary_key:
            continue  # already first in line
        client = _build_chain_entry(config, provider_id, model)
        if client is not None:
            chain.append((provider_id, client))

    if len(chain) == 1:
        return primary
    return FailoverClient(chain, gate=gate)


def _build_primary(config: Config, provider: str) -> tuple[str, LLMClient]:
    if provider == "local":
        model_path = str(config.get("local_model_path", "") or "")
        if not model_path:
            raise LLMError(
                "model_provider is 'local' but local_model_path is empty. Set it "
                "with: nusa-rg config set local_model_path /path/to/model.gguf"
            )
        return "local", LocalLLMRunner(
            model_path=model_path,
            binary=str(config.get("local_llama_bin", "llama-cli") or "llama-cli"),
            ctx_size=int(config.get("local_ctx_size", 4096) or 4096),
            threads=config.get("local_threads"),
            temperature=float(config.get("temperature", 0.2) or 0.0),
            timeout=int(config.get("request_timeout", 600) or 600),
        )

    # External path. Allow the URL to imply the provider when no key is set yet.
    base_url = _resolve(config.provider_base_url())
    provider_id = str(config.get("api_provider") or "").strip().lower()
    api_key = config.api_key_for(provider_id)
    if not api_key and not _is_local_url(base_url):
        # FR-08/AC-10: fail before sending a request that is guaranteed to be
        # rejected, and tell the user exactly how to fix it.
        if provider_id:
            names = ", ".join(_provider_env_names(provider_id)) or "its environment variable"
            raise AuthenticationError(
                f"no API key for provider '{provider_id}'. Store one with:\n"
                f"  nusa-rg config set api_key --provider {provider_id} --secret\n"
                f"or export {names}"
            )
        raise AuthenticationError(
            "no API key configured. Run: nusa-rg config set api_key --secret"
        )
    return provider_id or "external-api", ApiClient(
        base_url=base_url,
        api_key=api_key,
        model=str(config.get("api_model", "gpt-4o-mini") or "gpt-4o-mini"),
        timeout=int(config.get("request_timeout", 60) or 60),
        temperature=float(config.get("temperature", 0.2) or 0.0),
        max_tokens=_optional_int(config.get("max_tokens")),
        name=provider_id,
    )


def _build_chain_entry(config: Config, provider_id: str, model: str) -> LLMClient | None:
    """Build one fallback provider, or explain in the log why it is skipped.

    A misconfigured fallback never blocks the primary path; ``doctor`` and the
    log (``llm.chain.skip``) show what was left out and why.
    """
    provider = None
    try:
        provider = catalog.load_catalog().get(provider_id)
    except catalog.CatalogError:
        provider = None

    if provider is not None:
        if not provider.selectable:
            log_event("llm.chain.skip", provider=provider_id,
                      reason="not an OpenAI-compatible endpoint")
            return None
        base_url = provider.api
        model = model or provider.default_model
    else:
        base_url = PROVIDERS.get(provider_id, "")

    if not base_url:
        log_event("llm.chain.skip", provider=provider_id, reason="unknown provider")
        return None
    if not model:
        log_event("llm.chain.skip", provider=provider_id, reason="no model configured")
        return None
    try:
        base_url = catalog.resolve_url(base_url)
    except catalog.CatalogError as exc:
        log_event("llm.chain.skip", provider=provider_id, reason=str(exc))
        return None

    api_key = config.api_key_for(provider_id)
    if not api_key and not _is_local_url(base_url):
        log_event("llm.chain.skip", provider=provider_id, reason="no API key")
        return None

    return ApiClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=int(config.get("request_timeout", 60) or 60),
        temperature=float(config.get("temperature", 0.2) or 0.0),
        max_tokens=_optional_int(config.get("max_tokens")),
        name=provider_id,
    )


def _resolve(url: str) -> str:
    """Expand ``${VAR}`` placeholders, reported as an actionable LLM error."""
    try:
        return catalog.resolve_url(url)
    except catalog.CatalogError as exc:
        raise AuthenticationError(f"cannot build the endpoint URL: {exc}") from exc


def _provider_env_names(provider_id: str) -> list[str]:
    try:
        provider = catalog.load_catalog().get(provider_id)
    except catalog.CatalogError:
        provider = None
    return list(provider.env) if provider is not None else []


def _is_local_url(url: str) -> bool:
    """True for loopback and LAN endpoints, which need no API key."""
    host = (urlparse(url).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    return host.startswith(("10.", "192.168."))


def _optional_int(value) -> int | None:
    """Coerce a config value to int, treating blank/None as 'provider default'."""
    if value in (None, "", 0):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["build_client", "ApiClient", "FailoverClient", "LocalLLMRunner",
           "LLMClient", "LLMError"]
