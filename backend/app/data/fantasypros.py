"""FantasyPros v2 client.

Primary source for consensus rankings, ADP and projections when an API key is
configured. Without a key we fall back to the nflverse mirror of the same
FantasyPros draft rankings, which carries ecr/sd/best/worst but no projections.

Note the free FantasyPros tier returns *sample* data — good enough to exercise
the code path, not to draft on. Production use needs the paid key.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.data.cache import cache_key, cached

log = logging.getLogger(__name__)

BASE_URL = "https://api.fantasypros.com/public/v2/json"
TIMEOUT = 30.0

#: Our scoring presets -> the FantasyPros `scoring` query value.
SCORING_PARAM = {"standard": "STD", "half_ppr": "HALF", "ppr": "PPR", "custom": "PPR"}


class FantasyProsError(RuntimeError):
    pass


def is_configured() -> bool:
    return get_settings().fantasypros_enabled


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = get_settings()
    if not settings.fantasypros_api_key:
        raise FantasyProsError("FANTASYPROS_API_KEY is not set")
    try:
        response = httpx.get(
            f"{BASE_URL}{path}",
            params=params,
            headers={"x-api-key": settings.fantasypros_api_key},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        hint = " (check the key and its plan)" if code in (401, 403) else ""
        raise FantasyProsError(f"FantasyPros {code} for {path}{hint}") from exc
    except httpx.HTTPError as exc:
        raise FantasyProsError(f"FantasyPros request failed for {path}: {exc}") from exc


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def fetch_consensus_rankings(
    season: int, scoring: str = "ppr", position: str = "ALL"
) -> list[dict[str, Any]]:
    """Draft consensus rankings, normalized to the nflverse mirror's shape.

    Emitting the same keys as ``nflverse.load_consensus_rankings`` means the
    registry and scoring layers never learn which source they got.
    """

    def _load() -> list[dict[str, Any]]:
        payload = _get(
            f"/nfl/{season}/consensus-rankings",
            params={
                "position": position,
                "scoring": SCORING_PARAM.get(scoring, "PPR"),
                "type": "draft",
                "week": 0,
            },
        )
        rows = []
        for entry in payload.get("players", []) or []:
            rows.append(
                {
                    "player": entry.get("player_name"),
                    "id": entry.get("player_id"),
                    "pos": (entry.get("player_position_id") or "").upper() or None,
                    "team": entry.get("player_team_id"),
                    "ecr": _as_float(entry.get("rank_ecr")),
                    "sd": _as_float(entry.get("rank_std")),
                    "best": _as_float(entry.get("rank_min")),
                    "worst": _as_float(entry.get("rank_max")),
                    "adp": _as_float(entry.get("player_positional_adp"))
                    or _as_float(entry.get("rank_ave")),
                    "bye": entry.get("player_bye_week"),
                    "source": "fantasypros",
                }
            )
        return rows

    return cached(
        cache_key("fp_rankings", season, scoring, position), _load, ttl_hours=6
    )


def fetch_projections(
    season: int, position: str, week: int = 0, scoring: str = "ppr"
) -> list[dict[str, Any]]:
    """Season projections for one position group.

    ``week=0`` is FantasyPros' convention for rest-of-season / full season.
    """

    def _load() -> list[dict[str, Any]]:
        payload = _get(
            f"/nfl/{season}/projections",
            params={
                "position": position.upper(),
                "week": week,
                "scoring": SCORING_PARAM.get(scoring, "PPR"),
            },
        )
        rows = []
        for entry in payload.get("players", []) or []:
            stats = entry.get("stats") or {}
            rows.append(
                {
                    "id": entry.get("fpid") or entry.get("player_id"),
                    "player": entry.get("name") or entry.get("player_name"),
                    "pos": position.upper(),
                    "team": entry.get("team_id") or entry.get("player_team_id"),
                    "stats": {k: _as_float(v) for k, v in stats.items()},
                    "source": "fantasypros",
                }
            )
        return rows

    return cached(
        cache_key("fp_projections", season, position, week, scoring), _load, ttl_hours=12
    )


def health() -> dict[str, Any]:
    """Cheap reachability probe, used by ``/health``."""
    if not is_configured():
        return {"configured": False, "reachable": False, "detail": "no api key"}
    try:
        fetch_consensus_rankings(get_settings().season)
        return {"configured": True, "reachable": True}
    except FantasyProsError as exc:
        return {"configured": True, "reachable": False, "detail": str(exc)}
