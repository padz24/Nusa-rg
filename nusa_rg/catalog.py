"""Provider catalogue: 200+ OpenAI-compatible endpoints in one place.

The catalogue is a trimmed snapshot of `models.dev <https://models.dev>`_, the
community registry that lists every provider, its base URL, the environment
variable its key belongs in, and its models. ``nusa-rg`` bundles a snapshot
so this works offline, and ``nusa-rg providers refresh`` replaces it with a
fresh copy on disk when a network is available.

Only providers that speak the OpenAI chat-completions protocol -- the one
protocol :class:`~nusa_rg.llm.api_client.ApiClient` implements -- can be sent
a request; the rest are still listed and marked, because their key names and
docs are useful when wiring a manual ``api_base_url``.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import paths

CATALOG_URL = "https://models.dev/api.json"

#: Provider logos live next to the registry: one SVG per provider id.
LOGO_BASE_URL = "https://models.dev/logos"

#: Bundled snapshot shipped with the package.
BUNDLED_PATH = Path(__file__).resolve().parent / "data" / "catalog.json.gz"

#: npm packages whose endpoint is OpenAI chat-completions compatible. Anything
#: else (anthropic, google, bedrock, ...) needs an adapter this project does
#: not have, so it is listed but flagged.
COMPATIBLE_NPM = frozenset({
    "@ai-sdk/openai",
    "@ai-sdk/openai-compatible",
    "@ai-sdk/deepinfra",
    "@ai-sdk/cerebras",
    "@ai-sdk/groq",
    "@ai-sdk/perplexity",
    "@ai-sdk/xai",
    "@ai-sdk/mistral",
    "@ai-sdk/togetherai",
    "@openrouter/ai-sdk-provider",
    "@aihubmix/ai-sdk-provider",
    "venice-ai-sdk-provider",
})

#: models.dev leaves the base URL to the npm package for these providers, so
#: the snapshot has to know them. Keys are provider ids.
KNOWN_BASE_URLS = {
    "aihubmix": "https://aihubmix.com/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "deepinfra": "https://api.deepinfra.com/v1/openai",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "openai": "https://api.openai.com/v1",
    "perplexity": "https://api.perplexity.ai",
    "togetherai": "https://api.together.xyz/v1",
    "venice": "https://api.venice.ai/api/v1",
    "xai": "https://api.x.ai/v1",
}

#: Models whose id betrays a non-chat purpose. models.dev lists a few of these
#: beside the chat models; they cannot answer a question.
_NON_CHAT_ID = re.compile(
    r"embed|rerank|whisper|tts|moderation|dall-e|image|audio|video|guard|ocr",
    re.IGNORECASE,
)

_ENV_VAR = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


class CatalogError(RuntimeError):
    """The catalogue is missing, unreadable, or references an unknown value."""


@dataclass
class Provider:
    """One upstream service and the models it hosts."""

    id: str
    name: str
    api: str
    env: list[str]
    doc: str
    compatible: bool
    default_model: str
    models: dict[str, dict]
    logo: str = ""

    @property
    def model_count(self) -> int:
        return len(self.models)

    @property
    def selectable(self) -> bool:
        """True when this provider can be reached by the built-in client."""
        return self.compatible and bool(self.api)

    @property
    def logo_url(self) -> str:
        """Where the provider logo lives.

        The registry serves one SVG per provider id, so the address can always
        be derived; a snapshot that stored its own URL wins over the guess.
        """
        return self.logo or logo_url(self.id)


def logo_url(provider_id: str) -> str:
    """Address of one provider logo on models.dev."""
    return f"{LOGO_BASE_URL}/{urllib.parse.quote(provider_id.strip(), safe='')}.svg"


def _pick_default_model(models: dict[str, dict]) -> str:
    """Choose a sensible default chat model for a provider.

    Newest release wins; among same-day releases the cheapest input price, with
    the larger context as a tie-breaker. Tool-calling models are preferred when
    the provider has any, because the assistant uses structured citations.
    """
    candidates = []
    for model_id, model in models.items():
        if _NON_CHAT_ID.search(model_id):
            continue
        if model.get("status") in ("deprecated", "alpha"):
            continue
        date = model.get("released") or ""
        cost = model.get("input")
        cost = cost if isinstance(cost, (int, float)) else 9999.0
        context = model.get("context") or 0
        candidates.append((date, cost, context, model_id, bool(model.get("tool"))))
    if not candidates:
        return ""
    with_tool = [c for c in candidates if c[4]] or candidates
    newest = max(c[0] for c in with_tool)
    same_day = [c for c in with_tool if c[0] == newest]
    same_day.sort(key=lambda c: (c[1], -c[2], c[3]))
    return same_day[0][3]


def trim_catalog(raw: dict, *, source: str = CATALOG_URL, fetched_at: str = "") -> dict:
    """Reduce a raw models.dev document to the shape this project needs.

    Keeps one record per provider and per text-output model. Descriptions and
    capability matrices are dropped: they are the bulk of the 5 MB source and
    nothing here reads them.
    """
    providers: dict[str, dict] = {}
    for provider_id, provider in raw.items():
        if not isinstance(provider, dict):
            continue
        models: dict[str, dict] = {}
        for model_id, model in (provider.get("models") or {}).items():
            if not isinstance(model, dict):
                continue
            outputs = (model.get("modalities") or {}).get("output") or []
            if "text" not in outputs:
                continue
            if _NON_CHAT_ID.search(model_id):
                # Embedding/reranking/speech models cannot answer a question;
                # keep the catalogue to things this client can actually call.
                continue
            entry: dict = {"name": model.get("name") or model_id}
            context = (model.get("limit") or {}).get("context")
            if context:
                entry["context"] = int(context)
            cost = model.get("cost") or {}
            for field in ("input", "output"):
                value = cost.get(field)
                if isinstance(value, (int, float)):
                    entry[field] = round(float(value), 3)
            released = model.get("release_date")
            if released:
                entry["released"] = released
            entry["tool"] = bool(model.get("tool_call"))
            models[model_id] = entry

        api = str(provider.get("api") or "").strip()
        api = api or KNOWN_BASE_URLS.get(provider_id, "")
        providers[provider_id] = {
            "name": provider.get("name") or provider_id,
            "api": api,
            "env": [str(v) for v in (provider.get("env") or [])],
            "doc": str(provider.get("doc") or ""),
            "compatible": provider.get("npm") in COMPATIBLE_NPM,
            "default_model": _pick_default_model(models),
            "logo": logo_url(provider_id),
            "models": models,
        }
    return {
        "source": source,
        "fetched_at": fetched_at,
        "providers": providers,
    }


def resolve_url(url: str, *, environ=None) -> str:
    """Expand ``${VARIABLE}`` placeholders in a base URL from the environment.

    A handful of providers (Databricks, Cloudflare, Snowflake) embed an account
    id in their endpoint. Nothing is guessed: a missing variable is an error
    telling the user which one to export or to set ``api_base_url`` manually.
    """
    environ = os.environ if environ is None else environ
    missing: list[str] = []

    def _substitute(match: re.Match) -> str:
        name = match.group(1)
        value = environ.get(name, "")
        if not value:
            missing.append(name)
        return value

    resolved = _ENV_VAR.sub(_substitute, url)
    if missing:
        raise CatalogError(
            f"the provider URL needs {', '.join(sorted(set(missing)))}. "
            "Export the variable and try again, or set a literal api_base_url."
        )
    return resolved


class Catalog:
    """Look up providers and models from a (possibly refreshed) snapshot."""

    def __init__(self, document: dict):
        self.source = str(document.get("source") or CATALOG_URL)
        self.fetched_at = str(document.get("fetched_at") or "")
        self.providers: dict[str, Provider] = {}
        for provider_id, entry in (document.get("providers") or {}).items():
            self.providers[provider_id] = Provider(
                id=provider_id,
                name=str(entry.get("name") or provider_id),
                api=str(entry.get("api") or ""),
                env=[str(v) for v in (entry.get("env") or [])],
                doc=str(entry.get("doc") or ""),
                compatible=bool(entry.get("compatible")),
                default_model=str(entry.get("default_model") or ""),
                models=dict(entry.get("models") or {}),
                logo=str(entry.get("logo") or ""),
            )

    # ------------------------------------------------------------- lookups
    def get(self, provider_id: str) -> Provider | None:
        return self.providers.get(provider_id.strip().lower())

    def search(self, text: str = "", *, compatible_only: bool = False) -> list[Provider]:
        """Providers matching ``text`` in id or name, sorted by id."""
        needle = text.strip().lower()
        found = [
            provider for provider in self.providers.values()
            if (not compatible_only or provider.selectable)
            and (not needle or needle in provider.id.lower()
                 or needle in provider.name.lower())
        ]
        return sorted(found, key=lambda provider: provider.id)

    def models(self, provider_id: str, text: str = "") -> list[tuple[str, dict]]:
        """Models of one provider, newest first, optionally filtered."""
        provider = self.get(provider_id)
        if provider is None:
            return []
        needle = text.strip().lower()
        found = [
            (model_id, model) for model_id, model in provider.models.items()
            if not needle or needle in model_id.lower()
            or needle in str(model.get("name", "")).lower()
        ]
        # Newest first; ties keep a stable alphabetical order, so the same
        # catalogue always renders the same list.
        found.sort(key=lambda item: item[0])
        found.sort(key=lambda item: item[1].get("released") or "", reverse=True)
        return found

    def counts(self) -> tuple[int, int]:
        providers = len(self.providers)
        models = sum(p.model_count for p in self.providers.values())
        return providers, models


# --------------------------------------------------------------- loading
_cache: dict[str, tuple[float, "Catalog"]] = {}


def _read_document(path: Path) -> dict:
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                return json.load(handle)
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(
            f"provider catalogue not found at {path}. Reinstall the package, "
            "or run 'nusa-rg providers refresh' once a network is available."
        ) from exc
    except (OSError, ValueError) as exc:
        raise CatalogError(f"cannot read the provider catalogue at {path}: {exc}") from exc


def load(path: Path | str | None = None) -> Catalog:
    """Read one catalogue file. Defaults to the on-disk refresh, then bundled."""
    if path is None:
        state = paths.catalog_path()
        path = state if state.exists() else BUNDLED_PATH
    path = Path(path)
    document = _read_document(path)
    if not isinstance(document, dict) or not isinstance(document.get("providers"), dict):
        raise CatalogError(f"{path} is not a provider catalogue")
    return Catalog(document)


def load_catalog() -> Catalog:
    """Return the active catalogue, cached until the file changes on disk."""
    state = paths.catalog_path()
    path = state if state.exists() else BUNDLED_PATH
    mtime = path.stat().st_mtime
    cached = _cache.get(str(path))
    if cached is not None and cached[0] == mtime:
        return cached[1]
    catalog = load(path)
    _cache[str(path)] = (mtime, catalog)
    return catalog


def clear_cache() -> None:
    _cache.clear()


# --------------------------------------------------------------- refresh
def fetch_raw(url: str = CATALOG_URL, timeout: int = 45) -> dict:
    """Download the raw models.dev document."""
    from . import __version__

    request = urllib.request.Request(
        url, headers={"User-Agent": f"nusa-rg/{__version__} (Termux)"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise CatalogError(f"{url} answered HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise CatalogError(f"cannot reach {url}: {exc}") from exc
    try:
        raw = json.loads(payload)
    except ValueError as exc:
        raise CatalogError(f"{url} did not return JSON") from exc
    if not isinstance(raw, dict) or not raw:
        raise CatalogError(f"{url} returned an empty catalogue")
    return raw


def refresh(url: str = CATALOG_URL, timeout: int = 45) -> Catalog:
    """Fetch a fresh snapshot into the state directory, keeping it 0600."""
    raw = fetch_raw(url, timeout=timeout)
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    document = trim_catalog(raw, source=url, fetched_at=fetched_at)
    if not document["providers"]:
        raise CatalogError("the fetched catalogue has no providers")

    paths.ensure_dirs()
    target = paths.catalog_path()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    os.replace(tmp, target)
    paths.restrict(target)
    clear_cache()
    return Catalog(document)


__all__ = [
    "CATALOG_URL", "BUNDLED_PATH", "LOGO_BASE_URL", "Catalog", "CatalogError",
    "Provider", "fetch_raw", "load", "load_catalog", "logo_url",
    "refresh", "resolve_url", "trim_catalog",
]
