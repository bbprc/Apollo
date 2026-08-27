"""The Draft Confidence Score.

This answers "how sure are we that taking this player here works out", which is
deliberately *not* "how many points will he score". Projected points are what
VORP measures. Confidence is about the reliability of that projection at this
draft slot, so expert disagreement pushes it down while durability, volume and
an easy schedule push it up.

Every component is z-scored before weighting so that a 30% target share and a
1.04 schedule rating can be added together at all. Shares and schedules are
standardised *within* position — a 25% target share means something different
for a tight end than for a receiver — while value against ADP is standardised
across the whole pool, because a bargain is a bargain wherever it comes from.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable

from app.config import ConfidenceWeights
from app.models.player import ScoreComponent


def zscore(values: list[float]) -> Callable[[float], float]:
    """Build a standardiser from a sample.

    Degenerate samples (fewer than two points, or no spread) return a function
    that maps everything to 0 — neutral, rather than dividing by zero.
    """
    clean = [v for v in values if v is not None and math.isfinite(v)]
    if len(clean) < 2:
        return lambda _v: 0.0
    mean = sum(clean) / len(clean)
    variance = sum((v - mean) ** 2 for v in clean) / len(clean)
    sd = math.sqrt(variance)
    if sd <= 1e-9:
        return lambda _v: 0.0
    return lambda v: (v - mean) / sd if v is not None and math.isfinite(v) else 0.0


def squash(weighted_sum: float, steepness: float = 1.0) -> float:
    """Map a weighted z-sum onto 0-100.

    A logistic keeps the middle of the range linear where most players sit, and
    compresses the tails so one extreme component cannot peg the score.
    """
    return round(100.0 / (1.0 + math.exp(-steepness * weighted_sum)), 1)


@dataclass
class ConfidenceInput:
    """One player's raw, pre-standardisation signals."""

    player_id: str
    position: str
    adp: float | None = None
    current_pick: int | None = None
    sos_season: float | None = None
    sos_playoffs: float | None = None
    injury_risk: float | None = None
    opportunity_share: float | None = None
    consensus_sd: float | None = None
    consensus_ecr: float | None = None

    def adp_value(self) -> float | None:
        """Picks of surplus at this slot.

        Positive means the player has fallen past his consensus and is a
        bargain here; negative means taking him now is a reach. The order
        matters: an ADP of 3 seen at pick 8 is five picks of surplus, not
        minus five.
        """
        if self.adp is None or self.current_pick is None:
            return None
        return float(self.current_pick) - float(self.adp)

    def blended_sos(self, playoff_share: float) -> float | None:
        if self.sos_season is None and self.sos_playoffs is None:
            return None
        if self.sos_playoffs is None:
            return self.sos_season
        if self.sos_season is None:
            return self.sos_playoffs
        return (1 - playoff_share) * self.sos_season + playoff_share * self.sos_playoffs

    def uncertainty(self) -> float | None:
        """Expert disagreement, scaled by where in the draft he sits.

        A two-rank spread at pick 3 is a real disagreement; the same spread at
        pick 150 is noise, so the standard deviation is taken relative to the
        consensus rank itself.
        """
        if self.consensus_sd is None:
            return None
        anchor = max(float(self.consensus_ecr or 0.0), 12.0)
        return float(self.consensus_sd) / math.sqrt(anchor)


class ConfidenceScorer:
    """Standardises a pool of players, then scores each one against it."""

    def __init__(self, inputs: Iterable[ConfidenceInput], weights: ConfidenceWeights):
        self.weights = weights
        self.inputs = list(inputs)

        pool = self.inputs
        by_position: dict[str, list[ConfidenceInput]] = {}
        for item in pool:
            by_position.setdefault(item.position, []).append(item)

        # Global: a bargain is a bargain at any position.
        self._z_adp = zscore([i.adp_value() for i in pool if i.adp_value() is not None])
        self._z_uncertainty = zscore(
            [i.uncertainty() for i in pool if i.uncertainty() is not None]
        )
        self._z_injury = zscore(
            [i.injury_risk for i in pool if i.injury_risk is not None]
        )

        # Positional: shares and schedules only compare like with like.
        share = weights.playoff_sos_share
        self._z_share: dict[str, Callable[[float], float]] = {}
        self._z_sos: dict[str, Callable[[float], float]] = {}
        for position, group in by_position.items():
            self._z_share[position] = zscore(
                [g.opportunity_share for g in group if g.opportunity_share is not None]
            )
            self._z_sos[position] = zscore(
                [g.blended_sos(share) for g in group if g.blended_sos(share) is not None]
            )

    def score(self, item: ConfidenceInput) -> tuple[float, list[ScoreComponent]]:
        """Confidence in ``[0, 100]`` and the per-component breakdown."""
        weights = self.weights
        share = weights.playoff_sos_share
        components: list[ScoreComponent] = []

        def add(name: str, raw: float | None, z: float, weight: float,
                detail: str | None = None) -> None:
            components.append(
                ScoreComponent(
                    name=name,
                    raw=round(raw, 4) if raw is not None else None,
                    z_score=round(z, 4),
                    weight=weight,
                    contribution=round(z * weight, 4),
                    detail=detail,
                )
            )

        adp_value = item.adp_value()
        add(
            "adp_value",
            adp_value,
            self._z_adp(adp_value) if adp_value is not None else 0.0,
            weights.adp_value,
            None if adp_value is None
            else f"{'falling' if adp_value > 0 else 'a reach'} by {abs(adp_value):.1f} picks",
        )

        sos = item.blended_sos(share)
        z_sos = self._z_sos.get(item.position, lambda _v: 0.0)
        add(
            "strength_of_schedule",
            sos,
            z_sos(sos) if sos is not None else 0.0,
            weights.strength_of_schedule,
            None if sos is None else f"blended matchup rating {sos:.3f} (1.00 = average)",
        )

        # Risk is the one component where more is worse, so the z-score flips.
        add(
            "injury_risk",
            item.injury_risk,
            -self._z_injury(item.injury_risk) if item.injury_risk is not None else 0.0,
            weights.injury_risk,
            None if item.injury_risk is None else f"risk {item.injury_risk:.2f} (0 = never missed a game)",
        )

        z_share = self._z_share.get(item.position, lambda _v: 0.0)
        add(
            "opportunity_share",
            item.opportunity_share,
            z_share(item.opportunity_share) if item.opportunity_share is not None else 0.0,
            weights.opportunity_share,
            None if item.opportunity_share is None
            else f"{item.opportunity_share:.1%} of his offense",
        )

        # Wide expert disagreement lowers confidence, so this flips too.
        uncertainty = item.uncertainty()
        add(
            "consensus_uncertainty",
            uncertainty,
            -self._z_uncertainty(uncertainty) if uncertainty is not None else 0.0,
            weights.consensus_uncertainty,
            None if item.consensus_sd is None
            else f"experts disagree by {item.consensus_sd:.1f} ranks",
        )

        total = sum(c.contribution for c in components)
        return squash(total), components
