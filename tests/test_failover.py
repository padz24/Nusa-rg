"""Tests for multi-provider failover and per-provider key resolution."""

from __future__ import annotations

import pytest

from nusa_rg import catalog, llm
from nusa_rg.config import Config
from nusa_rg.llm.api_client import ApiClient
from nusa_rg.llm.base import (
    LLMError,
    LLMResponse,
    ProviderUnavailableError,
    Usage,
)
from nusa_rg.llm.failover import FailoverClient


class StubClient:
    """Minimal LLMClient stand-in with programmable failure."""

    def __init__(self, name: str, *, fail: Exception | None = None,
                 text: str = "answer", healthy: bool = True):
        self.name = name
        self.fail = fail
        self.text = text
        self.healthy = healthy
        self.calls: list[dict] = []
        self.closed = False

    def generate(self, prompt, *, context="", system="", stream=False):
        self.calls.append({"prompt": prompt, "system": system})
        if self.fail is not None:
            raise self.fail
        return LLMResponse(text=self.text, usage=Usage(), provider=self.name)

    def health_check(self):
        if not self.healthy:
            return False, f"{self.name} is down"
        return True, f"{self.name} ready"

    def close(self):
        self.closed = True


# ------------------------------------------------------------------- client
def test_failover_uses_the_next_provider():
    primary = StubClient("openai", fail=ProviderUnavailableError("cannot reach"))
    secondary = StubClient("groq", text="from groq")
    client = FailoverClient([("openai", primary), ("groq", secondary)])

    response = client.generate("hi")
    assert response.text == "from groq"
    assert response.provider == "groq"
    assert response.used_fallback is True
    assert primary.calls and secondary.calls


def test_primary_success_does_not_mark_fallback():
    primary = StubClient("openai", text="first")
    secondary = StubClient("groq")
    response = FailoverClient([("openai", primary), ("groq", secondary)]).generate("hi")
    assert response.text == "first"
    assert response.used_fallback is False
    assert not secondary.calls


def test_all_providers_failing_reports_each_one():
    client = FailoverClient([
        ("openai", StubClient("openai", fail=ProviderUnavailableError("down"))),
        ("groq", StubClient("groq", fail=ProviderUnavailableError("rate limited"))),
    ])
    with pytest.raises(LLMError) as exc:
        client.generate("hi")
    message = str(exc.value)
    assert "openai" in message and "down" in message
    assert "groq" in message and "rate limited" in message


def test_health_check_reports_the_first_working_provider():
    client = FailoverClient([
        ("openai", StubClient("openai", healthy=False)),
        ("groq", StubClient("groq")),
    ])
    ok, message = client.health_check()
    assert ok is True
    assert "groq" in message and "first choice failed" in message


def test_close_closes_every_client():
    primary, secondary = StubClient("a"), StubClient("b")
    FailoverClient([("a", primary), ("b", secondary)]).close()
    assert primary.closed and secondary.closed


# ------------------------------------------------------------------ factory
def _configure(monkeypatch, fallbacks):
    settings = Config()
    settings.update({"model_provider": "external", "api_provider": "openai",
                     "api_base_url": "https://api.openai.com/v1",
                     "api_model": "gpt-4o-mini"})
    settings.set("fallback_providers", fallbacks)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    return settings


def test_factory_builds_a_chain_with_catalogue_defaults(monkeypatch):
    settings = _configure(monkeypatch, ["groq"])
    monkeypatch.setenv("GROQ_API_KEY", "gsk-groq")

    client = llm.build_client(settings)
    assert isinstance(client, FailoverClient)
    assert client.labels == ["openai", "groq"]

    label, fallback = client.clients[1]
    assert isinstance(fallback, ApiClient)
    assert fallback.base_url == "https://api.groq.com/openai/v1"
    assert fallback.model == catalog.load_catalog().get("groq").default_model
    assert fallback.api_key == "gsk-groq"


def test_factory_skips_a_fallback_without_a_key(monkeypatch):
    settings = _configure(monkeypatch, ["groq"])
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    client = llm.build_client(settings)
    assert isinstance(client, ApiClient), "a keyless fallback must not be attempted"


def test_factory_keeps_single_client_without_fallbacks(monkeypatch):
    settings = _configure(monkeypatch, [])
    assert isinstance(llm.build_client(settings), ApiClient)


def test_factory_skips_keyless_local_fallback_never(monkeypatch, tmp_path):
    """A loopback fallback needs no key, and the entry's model is honoured."""
    import json

    from nusa_rg import paths

    paths.ensure_dirs()
    paths.catalog_path().write_text(json.dumps({
        "source": "test", "providers": {
            "openai": {
                "name": "OpenAI", "api": "https://api.openai.com/v1",
                "env": ["OPENAI_API_KEY"], "compatible": True,
                "default_model": "gpt", "models": {"gpt": {"name": "GPT"}},
            },
            "localtest": {
                "name": "Local Test", "api": "http://127.0.0.1:9999/v1",
                "env": [], "compatible": True, "default_model": "m1",
                "models": {"m1": {"name": "M1"}},
            },
        },
    }), encoding="utf-8")
    catalog.clear_cache()
    try:
        settings = _configure(monkeypatch, ["localtest"])
        client = llm.build_client(settings)
        assert isinstance(client, FailoverClient)
        label, fallback = client.clients[1]
        assert label == "localtest"
        assert fallback.base_url == "http://127.0.0.1:9999/v1"
        assert fallback.model == "m1"
        assert fallback.api_key == ""
    finally:
        catalog.clear_cache()


def test_fallback_entry_model_after_colon_wins(monkeypatch):
    settings = _configure(monkeypatch, ["groq:llama-3.3-70b-versatile"])
    monkeypatch.setenv("GROQ_API_KEY", "gsk-groq")
    client = llm.build_client(settings)
    _, fallback = client.clients[1]
    assert fallback.model == "llama-3.3-70b-versatile"
