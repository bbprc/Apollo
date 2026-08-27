"""The player pool — where every scorer is composed into a draft board.

Building the pool is expensive (several seasons of stats, schedules and injury
reports), and none of it changes during a draft. Scoring a board against a
particular pick is cheap. So the two are separated: :class:`PlayerPool` is
built once per league configuration and cached, and :meth:`PlayerPool.board`
is called on every pick.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.data import fantasypros, nflverse
from app.data.registry import PlayerRegistry, get_registry
from app.models.league import LeagueSettings
from app.models.player import Player, PlayerConsensus, PlayerScore
from app.scoring import projections as projections_mod
from app.scoring.confidence import ConfidenceInput, ConfidenceScorer
from app.scoring.injury import InjuryModel, build_injury_model
from app.scoring.sos import StrengthOfSchedule
from app.scoring.target_share import OpportunityModel, build_opportunity_model
from app.scoring.vorp import compute_vorp, replacement_ranks

log = logging.getLogger(__name__)


def load_consensus(league: LeagueSettings) -> tuple[list[dict[str, Any]], str]:
    """Consensus rankings from FantasyPros if keyed, else the nflverse mirror."""
    settings = get_settings()
    if fantasypros.is_configured():
        try:
            rows = fantasypros.fetch_consensus_rankings(
                settings.season, scoring=league.scoring
            )
            if rows:
                return rows, "fantasypros"
            log.warning("FantasyPros returned no rankings; falling back to nflverse")
        except fantasypros.FantasyProsError as exc:
            log.warning("FantasyPros rankings unavailable (%s); using nflverse", exc)
    return nflverse.load_consensus_rankings(superflex=league.superflex), "nflverse"


class PlayerPool:
    """Static, league-scoped analytics for every draftable player."""

    def __init__(self, league: LeagueSettings, registry: PlayerRegistry | None = None):
        self.league = league
        self.registry = registry or get_registry()
        self.settings = get_settings()

        rows, self.consensus_source = load_consensus(league)
        self.consensus: dict[str, PlayerConsensus] = {}
        self.positional_rank: dict[str, int] = {}

        pos_ranks = projections_mod.positional_ranks(rows)
        for row in rows:
            player = self.registry.by_fantasypros_id(row.get("id")) or self.registry.resolve(
                row.get("player") or "", row.get("pos"), row.get("team")
            )
            if player is None:
                continue
            rank = pos_ranks.get(str(row.get("id")))
            self.consensus[player.player_id] = PlayerConsensus(
                player_id=player.player_id,
                ecr=row.get("ecr"),
                adp=row.get("adp") or row.get("ecr"),
                rank_min=row.get("best"),
                rank_max=row.get("worst"),
                rank_std=row.get("sd"),
                positional_rank=rank,
                source=self.consensus_source,
            )
            if rank:
                self.positional_rank[player.player_id] = rank

        self.projections = projections_mod.project_players(league, self.registry, rows)
        self.positions = {
            pid: (self.registry.get(pid).position if self.registry.get(pid) else None)
            for pid in self.projections
        }
        self.positions = {k: v for k, v in self.positions.items() if v}

        self.vorp = compute_vorp(league, self.projections, self.positions)
        self.replacement_ranks = replacement_ranks(league)

        self.sos = StrengthOfSchedule(league)
        self.injury: InjuryModel = build_injury_model()
        self.opportunity: OpportunityModel = build_opportunity_model()

        self._static = {pid: self._static_signals(pid) for pid in self.consensus}
        log.info(
            "pool ready: %d ranked players (%s), %d projected",
            len(self.consensus), self.consensus_source, len(self.projections),
        )

    # -- per-player static signals -----------------------------------------

    def _static_signals(self, player_id: str) -> dict[str, Any]:
        player = self.registry.get(player_id)
        if player is None:
            return {}
        risk, risk_detail = self.injury.risk(player.gsis_id, player.position, player.age)
        share, share_detail = self.opportunity.share(player.gsis_id, player.position)
        return {
            "sos_season": self.sos.season_sos(player.team or "", player.position),
            "sos_playoffs": self.sos.playoff_sos(player.team or "", player.position),
            "injury_risk": risk,
            "injury_detail": risk_detail,
            "opportunity_share": share,
            "opportunity_detail": share_detail,
            "usage_trend": self.opportunity.usage_trend(player.gsis_id),
            "bye_week": self.sos.bye_week(player.team or ""),
        }

    def signals(self, player_id: str) -> dict[str, Any]:
        return self._static.get(player_id, {})

    def available_ids(self, drafted: set[str] | None = None) -> list[str]:
        drafted = drafted or set()
        return [pid for pid in self.consensus if pid not in drafted]

    def adp(self, player_id: str) -> float | None:
        consensus = self.consensus.get(player_id)
        return consensus.adp if consensus else None

    def adp_spread(self, player_id: str) -> float | None:
        consensus = self.consensus.get(player_id)
        return consensus.adp_spread if consensus else None

    # -- board -------------------------------------------------------------

    def board(
        self,
        current_pick: int,
        drafted: set[str] | None = None,
        positions: list[str] | None = None,
        limit: int | None = None,
    ) -> list[PlayerScore]:
        """Score and rank the available players for a given pick.

        Confidence is standardised across the *available* pool, so it re-centres
        as the draft thins out — a 70 in round 10 means "good for what is left",
        which is the question a drafter is actually asking.
        """
        drafted = drafted or set()
        wanted = {p.upper() for p in positions} if positions else None

        candidates: list[tuple[Player, ConfidenceInput]] = []
        for player_id in self.available_ids(drafted):
            player = self.registry.get(player_id)
            if player is None:
                continue
            if wanted and player.position not in wanted:
                continue
            consensus = self.consensus[player_id]
            signals = self.signals(player_id)
            candidates.append(
                (
                    player,
                    ConfidenceInput(
                        player_id=player_id,
                        position=player.position,
                        adp=consensus.adp,
                        current_pick=current_pick,
                        sos_season=signals.get("sos_season"),
                        sos_playoffs=signals.get("sos_playoffs"),
                        injury_risk=signals.get("injury_risk"),
                        opportunity_share=signals.get("opportunity_share"),
                        consensus_sd=consensus.rank_std,
                        consensus_ecr=consensus.ecr,
                    ),
                )
            )

        scorer = ConfidenceScorer((c for _p, c in candidates), self.settings.weights)

        scores: list[PlayerScore] = []
        for player, item in candidates:
            confidence, components = scorer.score(item)
            consensus = self.consensus[player.player_id]
            signals = self.signals(player.player_id)
            projection = self.projections.get(player.player_id)
            notes = [
                note for note in (
                    signals.get("injury_detail"),
                    signals.get("opportunity_detail"),
                    f"usage {signals['usage_trend']}" if signals.get("usage_trend") else None,
                    f"bye week {signals['bye_week']}" if signals.get("bye_week") else None,
                ) if note
            ]
            scores.append(
                PlayerScore(
                    player=player,
                    confidence=confidence,
                    components=components,
                    projected_points=projection.projected_points if projection else None,
                    vorp=self.vorp.get(player.player_id),
                    adp=consensus.adp,
                    ecr=consensus.ecr,
                    positional_rank=consensus.positional_rank,
                    sos_season=signals.get("sos_season"),
                    sos_playoffs=signals.get("sos_playoffs"),
                    injury_risk=signals.get("injury_risk"),
                    opportunity_share=signals.get("opportunity_share"),
                    notes=notes,
                )
            )

        # Rank by value over replacement, not by confidence: confidence says how
        # sure we are, VORP says how much it is worth being right.
        scores.sort(key=lambda s: (s.vorp if s.vorp is not None else -1e9), reverse=True)
        return scores[:limit] if limit else scores


_POOL_CACHE: dict[str, PlayerPool] = {}


def pool_signature(league: LeagueSettings) -> str:
    """Only the league fields that change the numbers belong in the key."""
    return "|".join(
        str(x) for x in (
            league.scoring,
            sorted((league.custom_scoring or {}).items()),
            league.teams,
            sorted(league.roster.items()),
            sorted(league.flex_eligible),
            league.superflex,
            get_settings().season,
        )
    )


def get_pool(league: LeagueSettings, refresh: bool = False) -> PlayerPool:
    key = pool_signature(league)
    if refresh:
        _POOL_CACHE.pop(key, None)
    if key not in _POOL_CACHE:
        _POOL_CACHE[key] = PlayerPool(league)
    return _POOL_CACHE[key]


def clear_pools() -> None:
    _POOL_CACHE.clear()
