#!/usr/bin/env python3
"""Regenerate the bundled provider catalogue.

Maintainers run this to refresh ``nusa_rg/data/catalog.json.gz``:

    python scripts/build_catalog.py                    # fetch models.dev
    python scripts/build_catalog.py raw-api.json       # or a downloaded copy

The output is deterministic for the same input: one file, sorted keys, compact
separators. Commit it together with the code that reads it.
"""

from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nusa_rg.catalog import BUNDLED_PATH, CATALOG_URL, fetch_raw, trim_catalog  # noqa: E402


def read_source(source: str) -> dict:
    path = Path(source)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return fetch_raw(source)


def main() -> int:
    source = sys.argv[1] if len(sys.argv) > 1 else CATALOG_URL
    raw = read_source(source)
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    document = trim_catalog(raw, source=source, fetched_at=fetched_at)

    BUNDLED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(BUNDLED_PATH, "wt", encoding="utf-8") as handle:
        json.dump(document, handle, sort_keys=True, separators=(",", ":"))

    providers = document["providers"]
    models = sum(len(p["models"]) for p in providers.values())
    selectable = sum(1 for p in providers.values()
                     if p["compatible"] and p["api"])
    size = BUNDLED_PATH.stat().st_size
    print(f"wrote {BUNDLED_PATH} ({size / 1024:.0f} KiB)")
    print(f"{len(providers)} providers ({selectable} selectable), {models} models")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
