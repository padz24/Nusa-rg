"""Tests for the provider catalogue (bundled snapshot, refresh, lookups)."""

from __future__ import annotations

import json

import pytest

from nusa_rg import catalog, paths

SYNTHETIC = {
    "groq": {
        "name": "Groq",
        "api": "",  # models.dev leaves it to the npm package; KNOWN_BASE_URLS fills it
        "env": ["GROQ_API_KEY"],
        "doc": "https://groq.com",
        "npm": "@ai-sdk/groq",
        "models": {
            "llama-3.3-70b": {
                "id": "llama-3.3-70b",
                "name": "Llama 3.3 70B",
                "modalities": {"output": ["text"]},
                "limit": {"context": 131072},
                "cost": {"input": 0.59, "output": 0.79},
                "release_date": "2025-01-01",
                "tool_call": True,
            },
            "mini-new": {
                "id": "mini-new",
                "name": "Mini New",
                "modalities": {"output": ["text"]},
                "limit": {"context": 65536},
                "cost": {"input": 0.05, "output": 0.1},
                "release_date": "2026-06-01",
                "tool_call": True,
            },
            "mini-new-pricey": {
                "id": "mini-new-pricey",
                "name": "Mini New Pricey",
                "modalities": {"output": ["text"]},
                "limit": {"context": 65536},
                "cost": {"input": 9.0, "output": 9.0},
                "release_date": "2026-06-01",
                "tool_call": True,
            },
            "whisper-large": {
                "id": "whisper-large",
                "name": "Whisper",
                "modalities": {"output": ["audio"]},
            },
            "text-embedding-3": {
                "id": "text-embedding-3",
                "name": "Embedding",
                "modalities": {"output": ["text"]},
                "release_date": "2026-07-01",
            },
            "old-model": {
                "id": "old-model",
                "name": "Old",
                "modalities": {"output": ["text"]},
                "release_date": "2026-08-01",
                "status": "deprecated",
            },
        },
    },
    "anthropic": {
        "name": "Anthropic",
        "api": "https://api.anthropic.com/v1",
        "env": ["ANTHROPIC_API_KEY"],
        "npm": "@ai-sdk/anthropic",
        "models": {
            "claude-x": {
                "id": "claude-x",
                "name": "Claude X",
                "modalities": {"output": ["text"]},
                "release_date": "2026-01-01",
            },
        },
    },
}


def _write_state(document: dict) -> None:
    paths.ensure_dirs()
    paths.catalog_path().write_text(json.dumps(document), encoding="utf-8")


# ------------------------------------------------------------------- trimming
def test_trim_catalog_filters_and_flags():
    document = catalog.trim_catalog(SYNTHETIC)
    providers = document["providers"]

    groq = providers["groq"]
    assert groq["compatible"] is True
    assert groq["api"] == "https://api.groq.com/openai/v1"  # from KNOWN_BASE_URLS

    # Non-text and non-chat models are dropped.
    assert "whisper-large" not in groq["models"]
    assert "text-embedding-3" not in groq["models"]
    # Deprecated models are not selected as the default.
    assert groq["default_model"] == "mini-new"

    anthropic = providers["anthropic"]
    assert anthropic["compatible"] is False
    assert anthropic["api"] == "https://api.anthropic.com/v1"


def test_default_model_prefers_cheapest_same_day_release():
    document = catalog.trim_catalog(SYNTHETIC)
    # Both "mini-new" and "mini-new-pricey" were released on 2026-06-01; the
    # cheaper input price wins.
    assert document["providers"]["groq"]["default_model"] == "mini-new"


def test_bundled_snapshot_is_shipped():
    """The repository ships a snapshot big enough to be useful offline."""
    loaded = catalog.load(catalog.BUNDLED_PATH)
    providers, models = loaded.counts()
    assert providers > 200, f"only {providers} providers bundled"
    assert models > 500, f"only {models} models bundled"
    groq = loaded.get("groq")
    assert groq is not None and groq.selectable
    assert groq.api == "https://api.groq.com/openai/v1"


# --------------------------------------------------------------------- logos
def test_logo_url_follows_the_registry_pattern():
    assert catalog.logo_url("anthropic") == \
        "https://models.dev/logos/anthropic.svg"
    assert catalog.logo_url(" 302ai ") == "https://models.dev/logos/302ai.svg"


def test_trim_catalog_records_the_logo_of_every_provider():
    document = catalog.trim_catalog(SYNTHETIC)
    assert document["providers"]["groq"]["logo"] == \
        "https://models.dev/logos/groq.svg"
    assert document["providers"]["anthropic"]["logo"] == \
        "https://models.dev/logos/anthropic.svg"


def test_provider_logo_falls_back_to_the_derived_url():
    """A snapshot written before logos existed still resolves an icon."""
    provider = catalog.Provider(id="groq", name="Groq", api="", env=[],
                                doc="", compatible=True, default_model="",
                                models={})
    assert provider.logo_url == "https://models.dev/logos/groq.svg"


# -------------------------------------------------------------------- lookups
def test_search_and_model_filters():
    loaded = catalog.Catalog(catalog.trim_catalog(SYNTHETIC))
    assert [p.id for p in loaded.search("gro")] == ["groq"]
    assert [p.id for p in loaded.search("") if p.selectable] == ["groq"]
    ids = [model_id for model_id, _ in loaded.models("groq", "mini")]
    assert ids == ["mini-new", "mini-new-pricey"]
    assert loaded.get("nope") is None


# -------------------------------------------------------------------- loading
def test_state_snapshot_overrides_bundled():
    document = catalog.trim_catalog(SYNTHETIC)
    _write_state(document)
    catalog.clear_cache()
    try:
        loaded = catalog.load_catalog()
        assert loaded.get("groq") is not None
        assert len(loaded.providers) == 2  # the synthetic file, not the bundle
    finally:
        catalog.clear_cache()


def test_load_missing_file_is_reported(tmp_path):
    with pytest.raises(catalog.CatalogError) as exc:
        catalog.load(tmp_path / "absent.json.gz")
    assert "not found" in str(exc.value)


# -------------------------------------------------------------------- refresh
def test_refresh_writes_private_state(monkeypatch):
    monkeypatch.setattr(catalog, "fetch_raw", lambda url, timeout=45: SYNTHETIC)
    refreshed = catalog.refresh()
    assert refreshed.counts()[0] == 2

    target = paths.catalog_path()
    assert target.exists()
    assert target.stat().st_mode & 0o077 == 0, "catalogue must stay owner-only"
    stored = json.loads(target.read_text(encoding="utf-8"))
    assert "groq" in stored["providers"]
    assert stored["source"] == catalog.CATALOG_URL
    catalog.clear_cache()


def test_refresh_rejects_an_empty_document(monkeypatch):
    monkeypatch.setattr(catalog, "fetch_raw", lambda url, timeout=45: {})
    from nusa_rg.catalog import CatalogError

    with pytest.raises(CatalogError):
        catalog.refresh()


# ---------------------------------------------------------------- url resolve
def test_resolve_url_expands_environment(monkeypatch):
    monkeypatch.setenv("ACCOUNT_ID", "abc123")
    assert catalog.resolve_url("https://x/v1/${ACCOUNT_ID}") == "https://x/v1/abc123"


def test_resolve_url_names_the_missing_variable():
    with pytest.raises(catalog.CatalogError) as exc:
        catalog.resolve_url("https://x/${DEFINITELY_UNSET_VAR}/v1", environ={})
    assert "DEFINITELY_UNSET_VAR" in str(exc.value)
