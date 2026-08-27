"""TTL disk cache shared by every upstream client.

Draft day means many repeated reads of slow-moving data (rosters, prior-season
stats, schedules). Caching keeps startup off the network and keeps us far under
Sleeper's rate limit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from app.config import get_settings

log = logging.getLogger(__name__)
T = TypeVar("T")


def _key_to_path(cache_dir: Path, key: str) -> Path:
    digest = hashlib.sha256(key.encode()).hexdigest()[:20]
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)[:60]
    return cache_dir / f"{safe}.{digest}.pkl"


def cached(key: str, loader: Callable[[], T], ttl_hours: float | None = None) -> T:
    """Return ``loader()``, memoized on disk under ``key``.

    A corrupt or unreadable cache entry is treated as a miss rather than an
    error — stale bytes should never take the app down.
    """
    settings = get_settings()
    ttl = (settings.cache_ttl_hours if ttl_hours is None else ttl_hours) * 3600
    path = _key_to_path(settings.cache_dir, key)

    if path.exists():
        age = time.time() - path.stat().st_mtime
        if age < ttl:
            try:
                with path.open("rb") as fh:
                    return pickle.load(fh)
            except Exception as exc:  # noqa: BLE001 - a bad entry is just a miss
                log.warning("cache read failed for %s (%s); refetching", key, exc)

    value = loader()

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("wb") as fh:
            pickle.dump(value, fh)
        tmp.replace(path)          # atomic, so a crash can't leave a half file
    except Exception as exc:       # noqa: BLE001 - caching is best effort
        log.warning("cache write failed for %s (%s)", key, exc)

    return value


def cache_key(*parts: Any) -> str:
    """Build a stable cache key from arbitrary parts."""
    rendered = []
    for part in parts:
        if isinstance(part, (dict, list, tuple, set)):
            rendered.append(json.dumps(part, sort_keys=True, default=str))
        else:
            rendered.append(str(part))
    return "-".join(rendered)


def clear_cache() -> int:
    """Delete every cache entry. Returns the number of files removed."""
    cache_dir = get_settings().cache_dir
    if not cache_dir.exists():
        return 0
    removed = 0
    for path in cache_dir.glob("*.pkl"):
        path.unlink(missing_ok=True)
        removed += 1
    return removed
