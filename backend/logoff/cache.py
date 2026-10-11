"""Tiny JSON file cache under data/cache/ (gitignored)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("LOGOFF_DATA_DIR", REPO_ROOT / "data"))
CACHE_DIR = DATA_DIR / "cache"


def _path(key: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", key)[:60]
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return CACHE_DIR / f"{safe}-{digest}.json"


def get(key: str, max_age_s: float) -> Any | None:
    """Return the cached value if it exists and is younger than max_age_s."""
    path = _path(key)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if time.time() - payload.get("saved_at", 0) > max_age_s:
        return None
    return payload.get("value")


def put(key: str, value: Any) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(key)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"saved_at": time.time(), "value": value}), encoding="utf-8")
    tmp.replace(path)
