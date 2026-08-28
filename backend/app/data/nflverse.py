"""nflverse loaders.

Everything here returns plain Python structures rather than Polars frames, so
the scoring and engine modules stay dependency-light and can be tested against
hand-written fixtures.

``nfl_data_py`` is deprecated; this uses its successor ``nflreadpy``, which
returns Polars.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.data.cache import cache_key, cached

log = logging.getLogger(__name__)

FANTASY_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K"})

#: Roster statuses that mean "could plausibly be drafted".
#: ACT active, RES injured reserve, PUP, NON non-football injury, DEV practice squad.
DRAFTABLE_STATUSES = frozenset({"ACT", "RES", "PUP", "NON", "DEV", "EXE", "TRC"})


def _nfl():
    import nflreadpy

    return nflreadpy


def _records(df) -> list[dict[str, Any]]:
    """Polars frame -> list of dicts, without importing Polars here."""
    return df.to_dicts() if df is not None and df.height else []


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------

def load_rosters(season: int) -> list[dict[str, Any]]:
    """Team rosters for a season, falling back a year if it isn't published yet."""

    def _load() -> list[dict[str, Any]]:
        nfl = _nfl()
        for candidate in (season, season - 1):
            try:
                rows = _records(nfl.load_rosters([candidate]))
            except Exception as exc:  # noqa: BLE001 - upstream file may not exist yet
                log.warning("rosters %s unavailable (%s)", candidate, exc)
                continue
            if rows:
                if candidate != season:
                    log.warning(
                        "rosters for %s not published; using %s", season, candidate
                    )
                return rows
        return []

    return cached(cache_key("rosters", season), _load)


def load_players() -> list[dict[str, Any]]:
    """The full player dictionary — biographical data and cross-source ids."""
    return cached(cache_key("players"), lambda: _records(_nfl().load_players()))


def load_id_map() -> list[dict[str, Any]]:
    """DynastyProcess id crosswalk. The only route to a FantasyPros id offline."""
    return cached(cache_key("ff_playerids"), lambda: _records(_nfl().load_ff_playerids()))


# --------------------------------------------------------------------------
# consensus rankings (the FantasyPros mirror)
# --------------------------------------------------------------------------

#: nflverse mirrors several FantasyPros ranking pages in one frame. These are
#: the redraft pages we care about; ``superflex`` covers 2QB leagues.
RANKING_PAGES = {
    "standard": "redraft-overall",
    "superflex": "redraft-op",
}


def load_consensus_rankings(superflex: bool = False) -> list[dict[str, Any]]:
    """FantasyPros redraft consensus rankings, mirrored by nflverse.

    Returns rows with ``player``, ``id`` (FantasyPros id), ``pos``, ``team``,
    ``ecr``, ``sd``, ``best``, ``worst``, ``bye``. Used when no FantasyPros API
    key is configured.
    """
    page = RANKING_PAGES["superflex" if superflex else "standard"]

    def _load() -> list[dict[str, Any]]:
        rows = _records(_nfl().load_ff_rankings("draft"))
        return [r for r in rows if r.get("page_type") == page]

    # Rankings move daily during draft season; keep the window short.
    return cached(cache_key("ff_rankings", page), _load, ttl_hours=6)


# --------------------------------------------------------------------------
# performance history
# --------------------------------------------------------------------------

def load_weekly_stats(seasons: list[int]) -> list[dict[str, Any]]:
    """Weekly player stat lines. Carries ``target_share`` already computed."""

    def _load() -> list[dict[str, Any]]:
        nfl = _nfl()
        rows: list[dict[str, Any]] = []
        for season in seasons:
            try:
                rows.extend(_records(nfl.load_player_stats([season])))
            except Exception as exc:  # noqa: BLE001
                log.warning("weekly stats %s unavailable (%s)", season, exc)
        return rows

    return cached(cache_key("weekly_stats", sorted(seasons)), _load, ttl_hours=24)


def load_expected_points(seasons: list[int]) -> list[dict[str, Any]]:
    """Weekly expected fantasy points, from ffverse's opportunity model.

    This is the one genuinely player-specific measure of value in the app.
    ``projected_points`` elsewhere is read off a rank-to-points curve, so it
    only ever restates the consensus; ``total_fantasy_points_exp`` is computed
    from what actually happened on the field - down, distance, field position -
    which is what lets the board disagree with the market.
    """

    def _load() -> list[dict[str, Any]]:
        nfl = _nfl()
        rows: list[dict[str, Any]] = []
        for season in seasons:
            try:
                frame = nfl.load_ff_opportunity(seasons=[season], stat_type="weekly")
                rows.extend(_records(frame))
            except Exception as exc:  # noqa: BLE001 - a missing season is not fatal
                log.warning("expected points %s unavailable (%s)", season, exc)
        return rows

    return cached(cache_key("ff_opportunity", sorted(seasons)), _load, ttl_hours=24)


def load_injuries(seasons: list[int]) -> list[dict[str, Any]]:
    """Weekly injury reports, available from 2009."""

    def _load() -> list[dict[str, Any]]:
        nfl = _nfl()
        rows: list[dict[str, Any]] = []
        for season in seasons:
            if season < 2009:
                continue
            try:
                rows.extend(_records(nfl.load_injuries([season])))
            except Exception as exc:  # noqa: BLE001
                log.warning("injuries %s unavailable (%s)", season, exc)
        return rows

    return cached(cache_key("injuries", sorted(seasons)), _load, ttl_hours=24)


def load_snap_counts(seasons: list[int]) -> list[dict[str, Any]]:
    """Snap counts, available from 2012. Keyed by pfr id, not gsis."""

    def _load() -> list[dict[str, Any]]:
        nfl = _nfl()
        rows: list[dict[str, Any]] = []
        for season in seasons:
            if season < 2012:
                continue
            try:
                rows.extend(_records(nfl.load_snap_counts([season])))
            except Exception as exc:  # noqa: BLE001
                log.warning("snap counts %s unavailable (%s)", season, exc)
        return rows

    return cached(cache_key("snaps", sorted(seasons)), _load, ttl_hours=24)


def load_schedules(seasons: list[int]) -> list[dict[str, Any]]:
    """Game schedules — the opponent list that strength of schedule reads."""

    def _load() -> list[dict[str, Any]]:
        try:
            return _records(_nfl().load_schedules(seasons))
        except Exception as exc:  # noqa: BLE001
            log.warning("schedules %s unavailable (%s)", seasons, exc)
            return []

    return cached(cache_key("schedules", sorted(seasons)), _load, ttl_hours=24)


def lookback_seasons(season: int | None = None) -> list[int]:
    """The prior seasons that feed the injury and opportunity models."""
    settings = get_settings()
    season = season or settings.season
    return list(range(season - settings.lookback_seasons, season))
