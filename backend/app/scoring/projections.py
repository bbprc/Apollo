"""Projected season points.

VORP needs a points estimate for every player, and FantasyPros only supplies
projections to paying keys. So there are two paths:

* **FantasyPros projections** when a key is configured — the stat lines are
  scored through the league's own rules, not FantasyPros' scoring.
* **A rank-to-points curve** otherwise. Historical seasons give the actual
  points scored by the Nth-best player at each position; a player's consensus
  positional rank is read off that curve. This is deliberately a statement
  about *the slot*, not about the player: the WR12 has scored roughly the same
  in every recent season even though a different man occupies the spot.

The curve degrades gracefully — it is what makes the app useful on day one and
it stays as the fallback when a projection is missing for one player.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from app.config import get_settings
from app.data import fantasypros, nflverse
from app.data.registry import PlayerRegistry
from app.models.league import LeagueSettings
from app.models.player import PlayerProjection
from app.scoring.league_scoring import score_stat_line, season_totals

log = logging.getLogger(__name__)

CURVE_POSITIONS = ("QB", "RB", "WR", "TE", "K")

#: Beyond this rank a position's curve is flat enough that extrapolating a
#: floor is more honest than reading noise off the tail.
MAX_CURVE_RANK = 80

#: Team defenses have no row in player stats, so they get a synthetic curve.
#: The spread is small and late-round by design: the point is to keep DST from
#: distorting VORP at other positions, not to pick the right defense.
DST_CURVE = [140.0 - 3.0 * i for i in range(32)]


def _smooth(values: list[float], window: int = 3) -> list[float]:
    """Rolling mean, so one freak season doesn't put a kink in the curve."""
    if len(values) < window:
        return values
    out = []
    half = window // 2
    for i in range(len(values)):
        lo, hi = max(0, i - half), min(len(values), i + half + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def build_rank_curves(league: LeagueSettings, seasons: list[int] | None = None
                      ) -> dict[str, list[float]]:
    """Points scored by the Nth-best player at each position, averaged.

    Returns ``{position: [points_at_rank_1, points_at_rank_2, ...]}`` under this
    league's scoring rules.
    """
    seasons = seasons or nflverse.lookback_seasons()
    weekly = nflverse.load_weekly_stats(seasons)
    totals = season_totals(weekly, league)

    # position -> season -> descending list of season point totals
    by_position: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for (_player_id, season), row in totals.items():
        position = (row.get("position") or "").upper()
        if position in CURVE_POSITIONS:
            by_position[position][season].append(row["points"])

    curves: dict[str, list[float]] = {}
    for position, seasons_map in by_position.items():
        ranked = [sorted(points, reverse=True) for points in seasons_map.values()]
        if not ranked:
            continue
        depth = min(max(len(r) for r in ranked), MAX_CURVE_RANK)
        curve = []
        for rank in range(depth):
            at_rank = [r[rank] for r in ranked if len(r) > rank]
            if at_rank:
                curve.append(sum(at_rank) / len(at_rank))
        curves[position] = _smooth(curve)

    curves.setdefault("DST", list(DST_CURVE))

    log.info(
        "rank curves built from %s: %s",
        seasons, {k: round(v[0], 1) if v else 0 for k, v in curves.items()},
    )
    return curves


def points_at_rank(curves: dict[str, list[float]], position: str, rank: int) -> float:
    """Read a positional rank off the curve, extrapolating past its tail."""
    curve = curves.get(position.upper())
    if not curve:
        return 0.0
    index = max(0, int(rank) - 1)
    if index < len(curve):
        return round(curve[index], 2)
    # Past the tail, decay the last known value rather than cliff to zero.
    tail = curve[-1]
    overshoot = index - len(curve) + 1
    return round(max(tail - overshoot * (tail * 0.02), 0.0), 2)


def positional_ranks(consensus_rows: list[dict[str, Any]]) -> dict[Any, int]:
    """Rank within position, derived from overall consensus rank."""
    by_position: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in consensus_rows:
        position = (row.get("pos") or "").upper()
        # FantasyPros suffixes positional ranks onto pos for some pages.
        position = "".join(c for c in position if c.isalpha())
        if position:
            by_position[position].append(row)

    ranks: dict[Any, int] = {}
    for position, rows in by_position.items():
        ordered = sorted(rows, key=lambda r: (r.get("ecr") is None, r.get("ecr") or 1e9))
        for index, row in enumerate(ordered, start=1):
            key = row.get("id")
            if key is not None:
                ranks[str(key)] = index
    return ranks


def project_players(
    league: LeagueSettings,
    registry: PlayerRegistry,
    consensus_rows: list[dict[str, Any]],
) -> dict[str, PlayerProjection]:
    """Projected season points for every player we have a consensus rank for."""
    settings = get_settings()
    curves = build_rank_curves(league)
    pos_ranks = positional_ranks(consensus_rows)

    projections: dict[str, PlayerProjection] = {}

    # --- preferred: real FantasyPros projections, scored our way ----------
    fp_stats: dict[str, dict[str, float]] = {}
    if fantasypros.is_configured():
        for position in CURVE_POSITIONS:
            try:
                for row in fantasypros.fetch_projections(
                    settings.season, position, scoring=league.scoring
                ):
                    if row.get("id") is not None:
                        fp_stats[str(row["id"])] = row.get("stats") or {}
            except fantasypros.FantasyProsError as exc:
                log.warning("FantasyPros projections for %s failed: %s", position, exc)

    rules = league.scoring_rules()

    for row in consensus_rows:
        fp_id = row.get("id")
        player = registry.by_fantasypros_id(fp_id) or registry.resolve(
            row.get("player") or "", row.get("pos"), row.get("team")
        )
        if player is None:
            continue

        stats = fp_stats.get(str(fp_id)) if fp_id is not None else None
        if stats:
            projections[player.player_id] = PlayerProjection(
                player_id=player.player_id,
                projected_points=score_stat_line(stats, rules),
                stat_line=stats,
                source="fantasypros",
            )
            continue

        rank = pos_ranks.get(str(fp_id))
        if rank is None:
            continue
        projections[player.player_id] = PlayerProjection(
            player_id=player.player_id,
            projected_points=points_at_rank(curves, player.position, rank),
            source="rank_curve",
        )

    log.info("projected %d players", len(projections))
    return projections
