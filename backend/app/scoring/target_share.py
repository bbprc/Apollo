"""Opportunity share — the volume a player commands.

Target share is the single most stable predictor of fantasy production, and it
is the thing FantasyPros does not expose. nflverse already computes
``target_share`` per game; this weights it toward recent form and blends in the
rushing side so the number means the same thing for a back as for a receiver.

Output is a 0-1 share of his own offense that a player accounts for.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from app.config import get_settings
from app.data import nflverse

log = logging.getLogger(__name__)

#: How much of a back's opportunity comes from carries vs. targets. Receptions
#: are worth more per touch in PPR, but carries are the larger share of volume.
RB_CARRY_WEIGHT = 0.65
RB_TARGET_WEIGHT = 0.35


class OpportunityModel:
    """Recent-form-weighted share of team volume."""

    def __init__(self, seasons: list[int] | None = None) -> None:
        settings = get_settings()
        self.seasons = sorted(seasons or nflverse.lookback_seasons(), reverse=True)
        self.recent_games = settings.recent_form_games

        rows = [
            r for r in nflverse.load_weekly_stats(self.seasons)
            if r.get("season_type") in (None, "REG")
        ]

        # Team carry totals per game, so a back's rush share can be computed
        # the same way nflverse computes target share.
        team_carries: dict[tuple[str, int, int], float] = defaultdict(float)
        for row in rows:
            key = (row.get("team"), row.get("season"), row.get("week"))
            if all(k is not None for k in key):
                team_carries[key] += float(row.get("carries") or 0)

        # player -> list of (season, week, target_share, rush_share, snaps)
        self._games: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            player_id = row.get("player_id")
            if not player_id:
                continue
            key = (row.get("team"), row.get("season"), row.get("week"))
            carries = float(row.get("carries") or 0)
            team_total = team_carries.get(key, 0.0)
            self._games[str(player_id)].append(
                {
                    "season": int(row.get("season") or 0),
                    "week": int(row.get("week") or 0),
                    "target_share": float(row.get("target_share") or 0.0),
                    "rush_share": (carries / team_total) if team_total else 0.0,
                    "targets": float(row.get("targets") or 0),
                    "carries": carries,
                    "wopr": float(row.get("wopr") or 0.0),
                }
            )

        for games in self._games.values():
            games.sort(key=lambda g: (g["season"], g["week"]), reverse=True)

    def share(self, player_id: str | None, position: str) -> tuple[float | None, str]:
        """Opportunity share in ``[0, 1]`` plus a human-readable detail line.

        ``None`` means we have no history — a rookie or a player who has never
        taken a snap. Callers treat that as neutral rather than as zero, since
        it is missing data, not evidence of a small role.
        """
        position = (position or "").upper()
        games = self._games.get(str(player_id)) if player_id else None
        if not games:
            return None, "no usage history"

        window = games[: self.recent_games]
        if not window:
            return None, "no usage history"

        target_share = sum(g["target_share"] for g in window) / len(window)
        rush_share = sum(g["rush_share"] for g in window) / len(window)

        if position == "RB":
            share = RB_CARRY_WEIGHT * rush_share + RB_TARGET_WEIGHT * target_share
            detail = (
                f"{rush_share:.1%} rush share, {target_share:.1%} target share "
                f"over last {len(window)} games"
            )
        elif position in ("WR", "TE"):
            share = target_share
            detail = f"{target_share:.1%} target share over last {len(window)} games"
        elif position == "QB":
            # A quarterback's "share" is close to 1 by construction; what
            # separates them is rushing volume, so use that as the signal.
            carries = sum(g["carries"] for g in window) / len(window)
            share = min(carries / 10.0, 1.0)
            detail = f"{carries:.1f} rush attempts per game"
        else:
            return None, "opportunity share not modelled for this position"

        return round(min(max(share, 0.0), 1.0), 4), detail

    def usage_trend(self, player_id: str | None) -> str | None:
        """Whether recent usage is rising or falling — context for the chat layer."""
        games = self._games.get(str(player_id)) if player_id else None
        if not games or len(games) < 6:
            return None
        recent = games[:3]
        prior = games[3:8]
        if not prior:
            return None
        recent_share = sum(g["target_share"] + g["rush_share"] for g in recent) / len(recent)
        prior_share = sum(g["target_share"] + g["rush_share"] for g in prior) / len(prior)
        if prior_share <= 0:
            return None
        delta = (recent_share - prior_share) / prior_share
        if delta > 0.15:
            return "rising"
        if delta < -0.15:
            return "falling"
        return "steady"


def build_opportunity_model(seasons: list[int] | None = None) -> OpportunityModel:
    return OpportunityModel(seasons)
