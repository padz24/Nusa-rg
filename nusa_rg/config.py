"""YAML configuration and credential resolution (FR-11, FR-12, AC-15..AC-17).

Implements the ``Config.get()`` contract from AGENS.md section 9 and the
four fields required by AC-16: ``api_key``, ``model_provider``,
``local_model_path``, ``default_project_path`` (plus ``system_prompt`` for
FR-11).

The invariant enforced here is that ``config.yaml`` never holds a secret in
plaintext: credential fields are ``keystore://<alias>`` references, and
:meth:`Config.resolve` transparently dereferences them.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Iterable

import yaml

from . import catalog, crypto, paths
from .logging_setup import audit

#: Fields whose values must be stored as keystore references (SEC-01, AC-31).
CREDENTIAL_FIELDS = ("api_key",)

#: Accepted values for ``response_style``; see :mod:`nusa_rg.style`.
RESPONSE_STYLES = ("default", "caveman")

DEFAULTS: dict[str, Any] = {
    "model_provider": "external",       # "external" | "local"
    "api_provider": "",                  # catalogue id backing api_base_url
    "api_base_url": "https://api.openai.com/v1",
    "api_model": "gpt-4o-mini",
    "api_key": "",                       # stores keystore:// reference only
    "provider_keys": {},                 # provider id -> keystore:// reference
    "fallback_providers": [],            # ["groq", "deepseek:deepseek-flash"]
    "local_model_path": "",
    "local_llama_bin": "llama-cli",
    "default_project_path": "",
    "system_prompt": (
        "You are a concise programming assistant embedded in a Termux terminal. "
        "Answer using the provided project context when it is relevant, cite "
        "file paths and line numbers, and keep code blocks short and runnable."
    ),
    "response_style": "default",         # "default" | "caveman"
    "max_context_snippets": 3,
    "chunk_lines": 60,
    "chunk_overlap_lines": 10,
    "max_file_bytes": 2 * 1024 * 1024,
    "ignore_dirs": [".git", "node_modules", "__pycache__", ".venv", "venv",
                    "build", "dist", ".mypy_cache", ".pytest_cache"],
    "ignore_globs": ["*.min.js", "*.lock", "*.so", "*.png", "*.jpg", "*.zip"],
    "request_timeout": 60,
    # Remote this installation may update from. Left empty, self-update
    # only accepts the official GitHub repository; set a local path here
    # to authorise an offline mirror.
    "update_remote": "",
    "max_tokens": None,               # leave unset for the provider default
    "temperature": 0.2,
    "command_timeout": 120,           # seconds a `!command` may run
    "command_output_limit": 40000,    # bytes of command output kept for context
    "command_use_rtk": True,          # route commands through rtk when installed
    "log_level": "INFO",
}

#: Built-in aliases kept for compatibility and for installs whose catalogue
#: file is missing. The catalogue in :mod:`nusa_rg.catalog` covers the rest.
PROVIDERS = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "local": "",
}


class ConfigError(RuntimeError):
    """Raised for invalid or unreadable configuration."""


def _alias_for(field: str) -> str:
    return f"credential/{field}"


def _reject_plaintext(config: dict[str, Any]) -> None:
    """Fail loudly if a plaintext secret ever lands in the YAML (AC-31)."""
    for field in CREDENTIAL_FIELDS:
        value = config.get(field)
        if isinstance(value, str) and value and not crypto.is_reference(value):
            raise ConfigError(
                f"config.yaml field '{field}' holds a plaintext value. "
                "Run 'nusa-rg config set api_key --secret' so the credential "
                "is stored encrypted in the keystore."
            )
    per_provider = config.get("provider_keys")
    if isinstance(per_provider, dict):
        for provider, value in per_provider.items():
            if isinstance(value, str) and value and not crypto.is_reference(value):
                raise ConfigError(
                    f"config.yaml field 'provider_keys.{provider}' holds a "
                    "plaintext value. Run 'nusa-rg config set api_key "
                    f"--provider {provider} --secret' instead."
                )


def _normalize(key: str, value: Any) -> Any:
    """Coerce user-friendly input into the stored form."""
    if key == "fallback_providers" and isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


def _validate(key: str, value: Any) -> None:
    if key == "response_style" and value not in RESPONSE_STYLES:
        raise ConfigError(
            f"unknown response style '{value}'. Use one of: "
            f"{', '.join(RESPONSE_STYLES)}."
        )


def default_document() -> dict[str, Any]:
    return dict(DEFAULTS)


class Config:
    """Read/write access to ``~/.nusa-rg/config.yaml``."""

    def __init__(self, path=None):
        self._path = path or paths.config_path()
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self.load()

    # ---------------------------------------------------------------- loading
    def load(self) -> dict[str, Any]:
        """Read the YAML file, creating it with defaults when absent (AC-17)."""
        with self._lock:
            if not self._path.exists():
                self._data = default_document()
                self._flush()
                return self._data
            try:
                raw = yaml.safe_load(self._path.read_text()) or {}
            except (yaml.YAMLError, OSError) as exc:
                raise ConfigError(f"cannot read {self._path}: {exc}") from exc
            if not isinstance(raw, dict):
                raise ConfigError(f"{self._path} must contain a YAML mapping")
            merged = default_document()
            merged.update(raw)
            _reject_plaintext(merged)
            self._data = merged
            return self._data

    def _flush(self) -> None:
        paths.ensure_dirs()
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            yaml.safe_dump(self._data, sort_keys=True, allow_unicode=True),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)
        paths.restrict(self._path)

    def save(self) -> None:
        with self._lock:
            _reject_plaintext(self._data)
            self._flush()

    # ----------------------------------------------------------------- access
    def get(self, key: str, default: Any = None) -> Any:
        """Return a config value, or ``default`` when the key is unknown.

        Mirrors the ``Config.get({key}) -> {value}`` contract in AGENS.md.
        """
        with self._lock:
            value = self._data.get(key, default)
        if key in CREDENTIAL_FIELDS and crypto.is_reference(value):
            alias = value[len(crypto.KEYSTORE_PREFIX):]
            try:
                return crypto.get_secret(alias)
            except crypto.CredentialStoreError:
                return default
        return value

    def resolve(self, key: str, default: Any = None) -> Any:
        """Alias of :meth:`get`; kept for readability at call sites."""
        return self.get(key, default)

    def set(self, key: str, value: Any, *, secret: bool = False,
            audit_event: str | None = None) -> None:
        """Update a key, optionally routing credential fields to the keystore."""
        with self._lock:
            value = _normalize(key, value)
            _validate(key, value)
            before = self._data.get(key)
            if secret and key in CREDENTIAL_FIELDS:
                self._data[key] = crypto.store(
                    self._data.get(key), _alias_for(key), value
                )
            else:
                self._data[key] = value
            self._flush()
            # SEC-09: record the change, but never the value of a credential.
            audit(
                audit_event or f"config.set.{key}",
                "SUCCESS",
                f"key={key} changed={before != value}",
            )

    def update(self, values: dict[str, Any], *, audit_event: str = "config.update") -> None:
        """Batch update; credential keys are routed to the keystore."""
        with self._lock:
            changed = sorted(values)
            for key, value in values.items():
                value = _normalize(key, value)
                _validate(key, value)
                if key in CREDENTIAL_FIELDS:
                    self._data[key] = crypto.store(
                        self._data.get(key), _alias_for(key), value
                    )
                else:
                    self._data[key] = value
            self._flush()
            audit(audit_event, "SUCCESS", f"keys={','.join(changed)}")

    # ------------------------------------------------------------------ keys
    @property
    def data(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)

    def provider_base_url(self) -> str:
        """Resolve the chat-completions base URL for the configured provider."""
        configured = str(self._data.get("api_base_url") or "").strip()
        if configured:
            return configured.rstrip("/")
        provider = self.catalog_provider()
        if provider is not None and provider.api:
            return provider.api.rstrip("/")
        model = str(self._data.get("api_model") or "").lower()
        if "llama" in model or "gpt" not in model:
            return PROVIDERS["groq"]
        return PROVIDERS["openai"]

    def catalog_provider(self) -> catalog.Provider | None:
        """The catalogue entry backing the active provider, when known."""
        provider_id = str(self._data.get("api_provider") or "").strip()
        if not provider_id:
            return None
        try:
            return catalog.load_catalog().get(provider_id)
        except catalog.CatalogError:
            return None

    def set_provider(self, name: str) -> dict:
        """Switch provider and align the base URL (and model) with the catalogue.

        Returns a small report for the CLI to print. The legacy names
        ``external``/``local`` keep their old meaning.
        """
        name = name.lower().strip()
        if name in ("external", "local"):
            self.set("model_provider", name)
            return {"provider": name}

        provider = None
        try:
            provider = catalog.load_catalog().get(name)
        except catalog.CatalogError:
            provider = None

        if provider is not None:
            if not provider.selectable:
                raise ConfigError(
                    f"provider '{name}' is listed but does not expose an "
                    "OpenAI-compatible endpoint. nusa-rg sends "
                    "/chat/completions requests; if your gateway offers one, "
                    "point 'config set api_base_url' at it directly."
                )
            change: dict[str, Any] = {
                "model_provider": "external",
                "api_base_url": provider.api,
                "api_provider": name,
            }
            # Keep the configured model when the provider actually hosts it;
            # otherwise fall back to the catalogue's pick for this provider.
            current = str(self._data.get("api_model") or "")
            if provider.default_model and current not in provider.models:
                change["api_model"] = provider.default_model
            self.update(change, audit_event="config.set_provider")
            return {
                "provider": name,
                "name": provider.name,
                "base_url": provider.api,
                "model": change.get("api_model"),
                "model_count": provider.model_count,
            }

        if name in PROVIDERS:
            self.update(
                {"model_provider": "external", "api_base_url": PROVIDERS[name],
                 "api_provider": name},
                audit_event="config.set_provider",
            )
            return {"provider": name, "base_url": PROVIDERS[name]}

        raise ConfigError(
            f"unknown provider '{name}'. Search the catalogue with: "
            f"nusa-rg providers list --search {name}"
        )

    def api_key_for(self, provider_id: str = "") -> str:
        """Resolve one provider's API key.

        Order: the key stored for that provider in the keystore, then its
        conventional environment variable (``GROQ_API_KEY`` and friends), then
        the legacy single ``api_key`` slot.
        """
        provider_id = (provider_id or "").strip().lower()
        if provider_id:
            keys = self._data.get("provider_keys") or {}
            reference = keys.get(provider_id) if isinstance(keys, dict) else None
            if crypto.is_reference(reference):
                alias = reference[len(crypto.KEYSTORE_PREFIX):]
                try:
                    value = crypto.get_secret(alias)
                except crypto.CredentialStoreError:
                    value = None
                if value:
                    return value
            try:
                provider = catalog.load_catalog().get(provider_id)
            except catalog.CatalogError:
                provider = None
            if provider is not None:
                for variable in provider.env:
                    value = os.environ.get(variable, "")
                    if value:
                        return value
        return self.get("api_key", "") or ""

    def set_provider_key(self, provider: str, key: str) -> None:
        """Seal one provider's key; an empty value removes it."""
        provider = provider.strip().lower()
        if not provider:
            raise ConfigError("a provider id is required to store a key")
        with self._lock:
            keys = dict(self._data.get("provider_keys") or {})
            alias = f"credential/provider/{provider}"
            if key:
                keys[provider] = crypto.store(keys.get(provider), alias, key)
            else:
                crypto.delete_secret(alias)
                keys.pop(provider, None)
            self._data["provider_keys"] = keys
            self._flush()
            # SEC-09: record the change, never the value.
            audit("config.set_provider_key", "SUCCESS", f"provider={provider}")

    def fallback_entries(self) -> list[tuple[str, str]]:
        """Parse ``fallback_providers`` into ``(provider, model)`` pairs.

        Each entry is ``provider`` or ``provider:model``. Provider ids never
        contain a colon, so everything after the first one is the model --
        which matters for ids like ``vendor/model:free``.
        """
        value = self._data.get("fallback_providers") or []
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",") if part.strip()]
        entries: list[tuple[str, str]] = []
        for item in value:
            text = str(item).strip()
            if not text:
                continue
            provider, _, model = text.partition(":")
            entries.append((provider.strip().lower(), model.strip()))
        return entries

    def set_api_key(self, key: str) -> None:
        """Store an API key encrypted and leave only a reference in YAML (SEC-01)."""
        self.set("api_key", key, secret=True, audit_event="config.set_api_key")

    def has_api_key(self) -> bool:
        try:
            return bool(self.get("api_key"))
        except ConfigError:
            return False

    def project_path(self) -> str:
        return str(self._data.get("default_project_path") or "")

    def ignore_dirs(self) -> Iterable[str]:
        value = self._data.get("ignore_dirs") or []
        return value if isinstance(value, list) else list(value)