"""Turn stat lines into fantasy points under a league's rules.

Every projection and every historical total in the app passes through
:func:`score_stat_line`, so changing a league's scoring re-ranks the whole board
without any other module knowing it happened.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from app.models.league import LeagueSettings


def score_stat_line(stats: dict[str, Any], rules: dict[str, float]) -> float:
    """Fantasy points for one stat line.

    Unknown stats score zero rather than raising — upstream feeds add columns
    and we would rather ignore one than fall over on draft day.
    """
    total = 0.0
    for stat, points in rules.items():
        if not points:
            continue
        value = stats.get(stat)
        if value is None:
            continue
        try:
            total += float(value) * points
        except (TypeError, ValueError):
            continue
    return round(total, 2)


def season_totals(
    weekly_rows: Iterable[dict[str, Any]],
    league: LeagueSettings,
    *,
    regular_season_only: bool = True,
) -> dict[tuple[str, int], dict[str, Any]]:
    """Aggregate weekly stat lines into per-player, per-season totals.

    Returns ``{(player_id, season): {...}}`` carrying the league-scored points,
    games played, and the raw stat sums the other scorers reuse.
    """
    rules = league.scoring_rules()
    accumulator: dict[tuple[str, int], dict[str, Any]] = defaultdict(
        lambda: {
            "points": 0.0,
            "games": 0,
            "stats": defaultdict(float),
            "position": None,
            "team": None,
            "name": None,
        }
    )

    for row in weekly_rows:
        if regular_season_only and row.get("season_type") not in (None, "REG"):
            continue
        player_id = row.get("player_id")
        season = row.get("season")
        if not player_id or season is None:
            continue

        bucket = accumulator[(str(player_id), int(season))]
        bucket["points"] += score_stat_line(row, rules)
        bucket["games"] += 1
        bucket["position"] = bucket["position"] or row.get("position")
        bucket["team"] = row.get("team") or bucket["team"]
        bucket["name"] = bucket["name"] or row.get("player_display_name") or row.get("player_name")

        for stat in rules:
            value = row.get(stat)
            if value is not None:
                try:
                    bucket["stats"][stat] += float(value)
                except (TypeError, ValueError):
                    pass
        # Opportunity stats are not scored but are needed downstream.
        for stat in ("targets", "carries", "receptions", "attempts"):
            value = row.get(stat)
            if value is not None:
                try:
                    bucket["stats"][stat] += float(value)
                except (TypeError, ValueError):
                    pass

    return {
        key: {**value, "points": round(value["points"], 2), "stats": dict(value["stats"])}
        for key, value in accumulator.items()
    }


def points_per_game(total_points: float, games: int) -> float:
    return round(total_points / games, 2) if games else 0.0
