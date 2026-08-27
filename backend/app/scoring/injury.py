"""Injury history risk.

FantasyPros reports a player's *current* designation; it has no history. This
builds one from nflverse weekly injury reports (available from 2009) plus games
actually played, recency-weighted so last season counts most.

The output is a 0-1 risk score where higher is riskier.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from app.data import nflverse

log = logging.getLogger(__name__)

REGULAR_SEASON_WEEKS = 17

#: How much each season counts, most recent first.
RECENCY_WEIGHTS = (0.5, 0.3, 0.2)

#: Positions take contact at different rates; running backs break down fastest.
POSITION_FRAGILITY = {"RB": 1.15, "WR": 1.0, "TE": 1.05, "QB": 0.95, "K": 0.6, "DST": 0.5}

#: Age past which risk starts climbing, by position.
AGE_CLIFF = {"RB": 27.0, "WR": 30.0, "TE": 30.0, "QB": 34.0, "K": 38.0}

_OUT_STATUSES = {"Out", "Doubtful", "Injured Reserve", "IR"}
_DNP = "Did Not Participate In Practice"


class InjuryModel:
    """Per-player injury risk from report history and games played."""

    def __init__(self, seasons: list[int] | None = None) -> None:
        self.seasons = sorted(seasons or nflverse.lookback_seasons(), reverse=True)

        # (gsis_id, season) -> counters
        self._reports: dict[tuple[str, int], dict[str, int]] = defaultdict(
            lambda: {"out": 0, "questionable": 0, "dnp": 0}
        )
        for row in nflverse.load_injuries(self.seasons):
            gsis_id = row.get("gsis_id")
            season = row.get("season")
            if not gsis_id or season is None:
                continue
            bucket = self._reports[(str(gsis_id), int(season))]
            status = (row.get("report_status") or "").strip()
            if status in _OUT_STATUSES:
                bucket["out"] += 1
            elif status:
                bucket["questionable"] += 1
            if (row.get("practice_status") or "").strip() == _DNP:
                bucket["dnp"] += 1

        # (player_id, season) -> games played
        self._games: dict[tuple[str, int], int] = defaultdict(int)
        for row in nflverse.load_weekly_stats(self.seasons):
            if row.get("season_type") not in (None, "REG"):
                continue
            player_id, season = row.get("player_id"), row.get("season")
            if player_id and season is not None:
                self._games[(str(player_id), int(season))] += 1

    # -- components --------------------------------------------------------

    def games_missed(self, gsis_id: str, season: int) -> int | None:
        """Regular-season games a player was absent for."""
        played = self._games.get((gsis_id, season))
        if played is None:
            return None
        return max(0, REGULAR_SEASON_WEEKS - played)

    def history(self, gsis_id: str) -> list[dict[str, Any]]:
        """Per-season detail, newest first, for display and for prompts."""
        out = []
        for season in self.seasons:
            played = self._games.get((gsis_id, season))
            if played is None:
                continue
            reports = self._reports.get((gsis_id, season), {})
            out.append(
                {
                    "season": season,
                    "games_played": played,
                    "games_missed": max(0, REGULAR_SEASON_WEEKS - played),
                    "weeks_listed_out": reports.get("out", 0),
                    "practices_missed": reports.get("dnp", 0),
                }
            )
        return out

    def risk(self, gsis_id: str | None, position: str,
             age: float | None = None) -> tuple[float, str]:
        """Risk in ``[0, 1]`` plus a one-line explanation.

        A player with no history at all (a rookie) gets the neutral 0.5 rather
        than a flattering 0 — absence of evidence is not durability.
        """
        position = (position or "").upper()
        fragility = POSITION_FRAGILITY.get(position, 1.0)

        seasons = self.history(gsis_id) if gsis_id else []
        if not seasons:
            base = 0.5
            detail = "no NFL history on record"
        else:
            weighted, total_weight = 0.0, 0.0
            for index, season in enumerate(seasons):
                weight = RECENCY_WEIGHTS[index] if index < len(RECENCY_WEIGHTS) else 0.1
                missed_rate = season["games_missed"] / REGULAR_SEASON_WEEKS
                practice_rate = min(season["practices_missed"] / REGULAR_SEASON_WEEKS, 1.0)
                # Missing games is the real signal; missed practices are a
                # leading indicator worth about a third as much.
                weighted += weight * (0.75 * missed_rate + 0.25 * practice_rate)
                total_weight += weight
            base = weighted / total_weight if total_weight else 0.5
            missed = sum(s["games_missed"] for s in seasons)
            detail = (
                f"{missed} game(s) missed across {len(seasons)} season(s)"
            )

        score = base * fragility

        cliff = AGE_CLIFF.get(position)
        if age and cliff and age > cliff:
            penalty = min((age - cliff) * 0.04, 0.20)
            score += penalty
            detail += f", age {age:.1f} past the {position} curve"

        return round(min(max(score, 0.0), 1.0), 4), detail


def build_injury_model(seasons: list[int] | None = None) -> InjuryModel:
    return InjuryModel(seasons)
