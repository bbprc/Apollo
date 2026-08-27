"""Value over replacement.

Raw projected points cannot answer "should I take the RB or the WR" — 250
points means something different at each position. VORP measures a player
against the worst starter a league of this size will tolerate at his position,
which is what makes cross-position comparison, and therefore wait-vs-take,
meaningful.

Replacement level is a property of the *league*: more teams or more flex slots
push it deeper, and every number here moves with it.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from app.models.league import LeagueSettings
from app.models.player import PlayerProjection

log = logging.getLogger(__name__)

#: How flex slots are expected to break down across eligible positions. Real
#: drafters put running backs and receivers in flex far more than tight ends.
FLEX_TENDENCY = {"RB": 0.45, "WR": 0.45, "TE": 0.10, "QB": 1.0}


def replacement_ranks(league: LeagueSettings) -> dict[str, int]:
    """The positional rank at which a starter becomes replaceable.

    ``{"RB": 30}`` means the 30th-best back is the baseline: in a 12-team
    league starting 2 RB plus flex, that is roughly the worst back anybody
    starts each week.
    """
    ranks: dict[str, float] = {}
    for position in ("QB", "RB", "WR", "TE", "K", "DST"):
        ranks[position] = league.teams * league.starters_at(position)

    total_flex = league.teams * league.flex_slots()
    if total_flex:
        eligible = list(league.flex_eligible)
        if league.superflex and "QB" not in eligible:
            eligible.append("QB")
        weights = {p: FLEX_TENDENCY.get(p, 0.1) for p in eligible}
        weight_sum = sum(weights.values()) or 1.0
        for position, weight in weights.items():
            ranks[position] = ranks.get(position, 0) + total_flex * (weight / weight_sum)

    # At least one startable player per position, and whole numbers.
    return {p: max(1, int(round(v))) for p, v in ranks.items()}


def replacement_levels(
    league: LeagueSettings,
    projections: dict[str, PlayerProjection],
    positions: dict[str, str],
) -> dict[str, float]:
    """Projected points of the replacement-level player at each position.

    ``positions`` maps player_id -> position.
    """
    ranks = replacement_ranks(league)

    by_position: dict[str, list[float]] = defaultdict(list)
    for player_id, projection in projections.items():
        position = positions.get(player_id)
        if position:
            by_position[position].append(projection.projected_points)

    levels: dict[str, float] = {}
    for position, points in by_position.items():
        points.sort(reverse=True)
        index = min(ranks.get(position, len(points)), len(points)) - 1
        levels[position] = round(points[max(index, 0)], 2) if points else 0.0

    log.info("replacement levels: %s", {k: round(v) for k, v in levels.items()})
    return levels


def compute_vorp(
    league: LeagueSettings,
    projections: dict[str, PlayerProjection],
    positions: dict[str, str],
) -> dict[str, float]:
    """Points above replacement for every projected player."""
    levels = replacement_levels(league, projections, positions)
    vorp: dict[str, float] = {}
    for player_id, projection in projections.items():
        position = positions.get(player_id)
        if not position:
            continue
        baseline = levels.get(position, 0.0)
        vorp[player_id] = round(projection.projected_points - baseline, 2)
    return vorp
