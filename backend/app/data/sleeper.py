"""Sleeper client — draft sync and the active-player dump.

The public API needs no auth and asks callers to stay under 1000 requests per
minute. The player dump is ~5MB, so it is cached aggressively; draft picks are
cached barely at all, since they are the thing that changes.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.data.cache import cache_key, cached

log = logging.getLogger(__name__)

BASE_URL = "https://api.sleeper.app/v1"
TIMEOUT = 30.0


class SleeperError(RuntimeError):
    """Sleeper returned something unusable."""


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{BASE_URL}{path}"
    try:
        response = httpx.get(url, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise SleeperError(
            f"Sleeper {exc.response.status_code} for {path}"
        ) from exc
    except httpx.HTTPError as exc:
        raise SleeperError(f"Sleeper request failed for {path}: {exc}") from exc


def load_active_players() -> dict[str, dict[str, Any]]:
    """Every active NFL player Sleeper knows about, keyed by Sleeper id.

    This is the second half of the registry intersection: nflverse says who is
    rostered, Sleeper says who is active.
    """

    def _load() -> dict[str, dict[str, Any]]:
        payload = _get("/players/nfl", params={"active": "true"})
        if not isinstance(payload, dict):
            raise SleeperError("unexpected shape from /players/nfl")
        return {
            pid: p
            for pid, p in payload.items()
            if isinstance(p, dict) and p.get("active")
        }

    return cached(cache_key("sleeper_players"), _load, ttl_hours=24)


def get_draft(draft_id: str) -> dict[str, Any]:
    """Draft metadata: type, status, settings, slot-to-roster mapping."""
    payload = _get(f"/draft/{draft_id}")
    if not isinstance(payload, dict):
        raise SleeperError(f"draft {draft_id} not found")
    return payload


def get_draft_picks(draft_id: str) -> list[dict[str, Any]]:
    """Picks made so far, in order.

    Deliberately uncached — this is polled during a live draft.
    """
    payload = _get(f"/draft/{draft_id}/picks")
    if not isinstance(payload, list):
        raise SleeperError(f"unexpected picks payload for draft {draft_id}")
    return sorted(payload, key=lambda p: p.get("pick_no") or 0)


def league_settings_from_draft(draft: dict[str, Any]) -> dict[str, Any]:
    """Translate a Sleeper draft object into our league vocabulary.

    Sleeper expresses the roster as ``settings.slots_<pos>`` and scoring as a
    ``rec`` points-per-reception value in the league metadata.
    """
    settings = draft.get("settings") or {}
    metadata = draft.get("metadata") or {}

    roster: dict[str, int] = {}
    for pos, key in (
        ("QB", "slots_qb"), ("RB", "slots_rb"), ("WR", "slots_wr"),
        ("TE", "slots_te"), ("FLEX", "slots_flex"), ("K", "slots_k"),
        ("DST", "slots_def"), ("BENCH", "slots_bn"),
    ):
        value = settings.get(key)
        if value:
            roster[pos] = int(value)

    superflex = bool(settings.get("slots_super_flex"))
    if superflex:
        roster["SUPERFLEX"] = int(settings["slots_super_flex"])

    scoring_type = (metadata.get("scoring_type") or "").lower()
    scoring = {
        "ppr": "ppr",
        "half_ppr": "half_ppr",
        "std": "standard",
        "standard": "standard",
    }.get(scoring_type, "ppr")

    out: dict[str, Any] = {
        "teams": int(settings.get("teams") or 12),
        "rounds": int(settings.get("rounds") or 15),
        "draft_type": "linear" if draft.get("type") == "linear" else "snake",
        "scoring": scoring,
    }
    if roster:
        out["roster"] = roster
    if superflex:
        out["superflex"] = True
    if metadata.get("name"):
        out["name"] = metadata["name"]
    return out


def user_by_username(username: str) -> dict[str, Any] | None:
    """Resolve a Sleeper username to the account behind it.

    Nobody knows their own 19-digit Sleeper user id, but everybody knows their
    username, and the slot resolution downstream needs the id.
    """
    try:
        payload = _get(f"/user/{username.strip()}")
    except SleeperError:
        return None
    return payload if isinstance(payload, dict) and payload.get("user_id") else None


def drafts_for_user(user_id: str, season: int) -> list[dict[str, Any]]:
    """Every draft this account is in for a season. Mock drafts are not listed."""
    payload = _get(f"/user/{user_id}/drafts/nfl/{season}")
    return payload if isinstance(payload, list) else []


def leagues_for_user(user_id: str, season: int) -> list[dict[str, Any]]:
    payload = _get(f"/user/{user_id}/leagues/nfl/{season}")
    return payload if isinstance(payload, list) else []


def team_names_for_draft(draft_id: str) -> dict[int, str]:
    """Draft slot -> manager display name.

    ``draft_order`` maps user ids to slots, and the league's user list maps
    those ids to names. Slots with no human behind them (the CPU teams in a
    mock) are simply absent, and the caller falls back to "Team N".
    """

    def _load() -> dict[str, str]:
        draft = get_draft(draft_id)
        order = draft.get("draft_order") or {}
        if not order:
            return {}
        league_id = (draft.get("metadata") or {}).get("league_id") or draft.get("league_id")
        if not league_id:
            return {}
        try:
            users = _get(f"/league/{league_id}/users") or []
        except SleeperError:
            log.warning("could not read league users for draft %s", draft_id)
            return {}

        names = {
            str(u.get("user_id")): (
                (u.get("metadata") or {}).get("team_name") or u.get("display_name")
            )
            for u in users
            if isinstance(u, dict) and u.get("user_id")
        }
        # Keys are stringified so the payload survives the JSON cache round trip.
        return {
            str(slot): names[str(user_id)]
            for user_id, slot in order.items()
            if names.get(str(user_id))
        }

    raw = cached(cache_key("sleeper_team_names", draft_id), _load, ttl_hours=6)
    return {int(slot): name for slot, name in (raw or {}).items()}


def my_slot_from_draft(draft: dict[str, Any], user_id: str | None) -> int | None:
    """Find which draft slot belongs to a Sleeper user id."""
    if not user_id:
        return None
    order = draft.get("draft_order") or {}
    slot = order.get(user_id)
    return int(slot) if slot else None
