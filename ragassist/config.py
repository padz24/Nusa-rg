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

from . import crypto, paths
from .logging_setup import audit

#: Fields whose values must be stored as keystore references (SEC-01, AC-31).
CREDENTIAL_FIELDS = ("api_key",)

DEFAULTS: dict[str, Any] = {
    "model_provider": "external",       # "external" | "local"
    "api_base_url": "https://api.openai.com/v1",
    "api_model": "gpt-4o-mini",
    "api_key": "",                       # stores keystore:// reference only
    "local_model_path": "",
    "local_llama_bin": "llama-cli",
    "default_project_path": "",
    "system_prompt": (
        "You are a concise programming assistant embedded in a Termux terminal. "
        "Answer using the provided project context when it is relevant, cite "
        "file paths and line numbers, and keep code blocks short and runnable."
    ),
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
    "log_level": "INFO",
}

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
                "Run 'rag-assist config set api_key --secret' so the credential "
                "is stored encrypted in the keystore."
            )


def default_document() -> dict[str, Any]:
    return dict(DEFAULTS)


class Config:
    """Read/write access to ``~/.rag-assist/config.yaml``."""

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
        model = str(self._data.get("api_model") or "").lower()
        if not configured:
            if "llama" in model or "gpt" not in model:
                return PROVIDERS["groq"]
            return PROVIDERS["openai"]
        return configured.rstrip("/")

    def set_provider(self, name: str) -> None:
        """Switch provider and align the base URL with the provider default."""
        name = name.lower().strip()
        if name not in ("external", "local", *PROVIDERS):
            raise ConfigError(
                f"unknown provider '{name}'. Use external, local, "
                f"openai, or groq."
            )
        if name in ("external", "local"):
            self.set("model_provider", name)
            return
        self.update(
            {"model_provider": "external", "api_base_url": PROVIDERS[name]},
            audit_event="config.set_provider",
        )

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