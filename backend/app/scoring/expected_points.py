"""Expected fantasy points, from what a player actually did on the field.

Everywhere else in the app, "projected points" is read off a rank-to-points
curve: the Nth-best back at a position is assigned what the Nth-best back has
historically scored. That is a restatement of the consensus ranking, so a board
built on it can never disagree with the experts - and disagreeing with the
experts is the only way a draft tool is worth anything.

ffverse computes expected fantasy points per play from down, distance and field
position. Averaged over a player's recent games it answers a different question:
not "where do the experts rank him" but "what has his actual usage been worth".
Where the two disagree is the edge.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from app.config import get_settings
from app.data import nflverse

log = logging.getLogger(__name__)

#: Below this many games the average is noise, not signal.
MIN_GAMES = 6
#: Regular-season games, for turning a season projection into a per-game price.
SEASON_GAMES = 17


class ExpectedPointsModel:
    """Recent-form-weighted expected fantasy points per game."""

    def __init__(self, seasons: list[int] | None = None) -> None:
        settings = get_settings()
        self.seasons = sorted(seasons or nflverse.lookback_seasons(), reverse=True)
        self.recent_games = settings.recent_form_games

        rows = nflverse.load_expected_points(self.seasons)

        # player -> games, newest first, so the recency window is just a slice.
        games: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            player_id = row.get("player_id")
            points = row.get("total_fantasy_points_exp")
            if not player_id or points is None:
                continue
            games[str(player_id)].append(
                {
                    "season": int(row.get("season") or 0),
                    "week": int(row.get("week") or 0),
                    "points": float(points),
                    "position": (row.get("position") or "").upper(),
                }
            )
        for played in games.values():
            played.sort(key=lambda g: (g["season"], g["week"]), reverse=True)
        self._games = games

        self._ppg: dict[str, float] = {}
        self._position: dict[str, str] = {}
        for player_id, played in games.items():
            window = played[: self.recent_games]
            if len(window) < MIN_GAMES:
                continue
            self._ppg[player_id] = round(
                sum(g["points"] for g in window) / len(window), 2
            )
            self._position[player_id] = window[0]["position"]

        # Rank within position on the same measure, so it can be compared like
        # for like against the consensus positional rank.
        self._rank: dict[str, int] = {}
        by_position: dict[str, list[tuple[float, str]]] = defaultdict(list)
        for player_id, ppg in self._ppg.items():
            by_position[self._position.get(player_id, "")].append((ppg, player_id))
        for group in by_position.values():
            for index, (_ppg, player_id) in enumerate(sorted(group, reverse=True), 1):
                self._rank[player_id] = index

        log.info(
            "expected points: %d players with %d+ games over %s",
            len(self._ppg), MIN_GAMES, self.seasons,
        )

    # -- lookup ------------------------------------------------------------

    def expected_ppg(self, gsis_id: str | None) -> float | None:
        """``None`` for a rookie or anyone without enough history to average."""
        return self._ppg.get(str(gsis_id)) if gsis_id else None

    def usage_rank(self, gsis_id: str | None) -> int | None:
        """His rank at his own position by expected points, 1 = best."""
        return self._rank.get(str(gsis_id)) if gsis_id else None

    def edge_ppg(
        self, gsis_id: str | None, projected_season_points: float | None
    ) -> float | None:
        """Expected points per game, minus what his draft price implies.

        ``projected_season_points`` is read off the rank curve, so it *is* the
        market's price expressed in points. Subtracting it leaves the part of a
        player's production the consensus is not paying for.

        Deliberately measured in points rather than ranks. A rank gap is not
        scale-free: WR173 to WR85 is eighty places and almost no points, while
        RB16 to RB6 is ten places and a great many - ranking by rank gap surfaces
        nothing but deep bench players.

        Positive means the market is discounting him. Negative is normal for
        rookies and for anyone whose situation has changed.
        """
        ppg = self.expected_ppg(gsis_id)
        if ppg is None or not projected_season_points:
            return None
        return round(ppg - (projected_season_points / SEASON_GAMES), 2)

    def ppg_at_rank(self, position: str, rank: int) -> float | None:
        """Expected points per game of the Nth-best player at a position.

        Needed to make "upside" comparable across positions. Raw points per game
        are not: a quarterback outscores a running back by half again, so the
        biggest number on the board is always a quarterback - and yet QB12 also
        scores nearly what QB1 does, so that raw edge is worth very little.
        Subtracting the replacement-level player is the same correction VORP
        makes, applied to this measure.
        """
        ranked = sorted(
            (ppg for player_id, ppg in self._ppg.items()
             if self._position.get(player_id) == position.upper()),
            reverse=True,
        )
        if not ranked:
            return None
        return ranked[min(max(rank, 1), len(ranked)) - 1]

    def above_replacement(
        self, gsis_id: str | None, position: str, replacement_rank: int | None
    ) -> float | None:
        """Expected points per game above the replacement-level player."""
        ppg = self.expected_ppg(gsis_id)
        if ppg is None or not replacement_rank:
            return None
        baseline = self.ppg_at_rank(position, replacement_rank)
        if baseline is None:
            return None
        return round(ppg - baseline, 2)

    def detail(self, gsis_id: str | None, position: str) -> str | None:
        """Human phrasing of the signal, for prompts and the drawer."""
        ppg = self.expected_ppg(gsis_id)
        rank = self.usage_rank(gsis_id)
        if ppg is None or rank is None:
            return None
        return f"{ppg:.1f} expected pts/game, {position}{rank} on usage"


_MODEL: ExpectedPointsModel | None = None


def get_expected_points() -> ExpectedPointsModel:
    """Process-wide singleton; the underlying frame is large."""
    global _MODEL
    if _MODEL is None:
        _MODEL = ExpectedPointsModel()
    return _MODEL
