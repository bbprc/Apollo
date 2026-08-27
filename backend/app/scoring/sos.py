"""Strength of schedule.

FantasyPros publishes an SOS grade but does not expose it through the API, so
we compute one: how many fantasy points each defense gave up to each position
last season, applied to this season's opponent list.

Two numbers come out, because they routinely disagree and only one of them
decides a league: the full regular season, and the fantasy playoff weeks.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from app.config import get_settings
from app.data import nflverse
from app.models.league import LeagueSettings
from app.scoring.league_scoring import score_stat_line

log = logging.getLogger(__name__)

SOS_POSITIONS = ("QB", "RB", "WR", "TE", "K")


def defense_ratings(
    league: LeagueSettings, seasons: list[int] | None = None
) -> dict[str, dict[str, float]]:
    """Points allowed per game by each defense to each position, as a ratio.

    ``1.0`` is league average; ``1.15`` means that defense gave up 15% more
    fantasy points to the position than a typical one. Higher is a better
    matchup for the offensive player facing it.
    """
    seasons = seasons or nflverse.lookback_seasons()
    # The most recent season carries the most signal about a defense.
    recent = seasons[-2:] if len(seasons) > 1 else seasons
    rows = nflverse.load_weekly_stats(recent)
    rules = league.scoring_rules()

    # defense -> position -> [points allowed, games seen]
    allowed: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(lambda: [0.0, 0.0])
    )
    weeks_seen: dict[str, set[tuple[int, int]]] = defaultdict(set)

    for row in rows:
        if row.get("season_type") not in (None, "REG"):
            continue
        defense = row.get("opponent_team")
        position = (row.get("position") or "").upper()
        if not defense or position not in SOS_POSITIONS:
            continue
        allowed[defense][position][0] += score_stat_line(row, rules)
        weeks_seen[defense].add((int(row.get("season") or 0), int(row.get("week") or 0)))

    per_game: dict[str, dict[str, float]] = {}
    for defense, positions in allowed.items():
        games = max(len(weeks_seen[defense]), 1)
        per_game[defense] = {pos: vals[0] / games for pos, vals in positions.items()}

    # Normalise each position against the league average for that position.
    ratings: dict[str, dict[str, float]] = defaultdict(dict)
    for position in SOS_POSITIONS:
        values = [d.get(position, 0.0) for d in per_game.values() if d.get(position)]
        if not values:
            continue
        average = sum(values) / len(values)
        if average <= 0:
            continue
        for defense, positions in per_game.items():
            value = positions.get(position)
            if value:
                ratings[defense][position] = round(value / average, 4)

    return dict(ratings)


def team_schedules(season: int) -> dict[str, dict[int, str]]:
    """``{team: {week: opponent}}`` for a season's regular season."""
    schedule: dict[str, dict[int, str]] = defaultdict(dict)
    for game in nflverse.load_schedules([season]):
        if game.get("game_type") not in (None, "REG"):
            continue
        week = game.get("week")
        home, away = game.get("home_team"), game.get("away_team")
        if week is None or not home or not away:
            continue
        schedule[home][int(week)] = away
        schedule[away][int(week)] = home
    return dict(schedule)


class StrengthOfSchedule:
    """Season and fantasy-playoff matchup quality, by team and position."""

    def __init__(self, league: LeagueSettings, season: int | None = None) -> None:
        settings = get_settings()
        self.season = season or settings.season
        self.playoff_weeks = set(settings.playoff_weeks)
        self.ratings = defense_ratings(league)
        self.schedule = team_schedules(self.season)
        if not self.schedule:
            log.warning("no %s schedule available; SOS will be neutral", self.season)

    def _average(self, team: str, position: str, weeks: set[int] | None) -> float | None:
        opponents = self.schedule.get((team or "").upper())
        if not opponents:
            return None
        values = [
            self.ratings.get(opponent, {}).get(position)
            for week, opponent in opponents.items()
            if weeks is None or week in weeks
        ]
        values = [v for v in values if v is not None]
        if not values:
            return None
        return round(sum(values) / len(values), 4)

    def season_sos(self, team: str, position: str) -> float | None:
        """Whole-season matchup quality. >1 is an easier-than-average slate."""
        return self._average(team, position, None)

    def playoff_sos(self, team: str, position: str) -> float | None:
        """Weeks 15-17 only — the ones that decide a league."""
        return self._average(team, position, self.playoff_weeks)

    def bye_week(self, team: str) -> int | None:
        opponents = self.schedule.get((team or "").upper())
        if not opponents:
            return None
        played = set(opponents)
        for week in range(1, 19):
            if week not in played:
                return week
        return None
