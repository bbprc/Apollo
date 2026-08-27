"""Will he still be there?

The Monte Carlo simulator is the real answer, because picks are not independent
— every pick removes a player from everyone's board. The closed-form normal
approximation is kept as a fast path for bulk questions where running a full
simulation per player would be wasteful.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.engine.simulator import DraftSimulator, SimulationResult
from app.scoring.board import PlayerPool


@dataclass
class Availability:
    player_id: str
    target_pick: int
    probability: float
    method: str
    detail: str

    @property
    def likely(self) -> bool:
        return self.probability >= 0.5


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def closed_form_probability(adp: float | None, spread: float | None,
                            target_pick: int) -> float | None:
    """P(a player lasts to ``target_pick``) under a normal ADP model.

    Treats his realised draft position as ``Normal(adp, spread)`` and asks for
    the mass beyond the target. Cheap, and reasonable for one player in
    isolation — but blind to the fact that a run at his position moves everyone.
    """
    if adp is None:
        return None
    sd = spread if spread and spread > 0 else max(adp * 0.15, 3.0)
    return round(1.0 - _normal_cdf((target_pick - adp) / sd), 4)


def probability_available(
    pool: PlayerPool,
    player_id: str,
    target_pick: int,
    simulation: SimulationResult | None = None,
) -> Availability:
    """Best available estimate, preferring the simulation when we have one."""
    if simulation is not None and player_id in simulation.survival:
        probability = simulation.probability_available(player_id)
        return Availability(
            player_id=player_id,
            target_pick=target_pick,
            probability=probability,
            method="monte_carlo",
            detail=(
                f"available in {probability:.0%} of {simulation.runs} simulated drafts"
            ),
        )

    adp = pool.adp(player_id)
    probability = closed_form_probability(adp, pool.adp_spread(player_id), target_pick)
    if probability is None:
        return Availability(
            player_id=player_id,
            target_pick=target_pick,
            probability=0.0,
            method="unknown",
            detail="no consensus ADP for this player",
        )
    return Availability(
        player_id=player_id,
        target_pick=target_pick,
        probability=probability,
        method="normal_approximation",
        detail=f"ADP {adp:.1f}; {probability:.0%} chance he lasts to pick {target_pick}",
    )


def run_simulation(
    pool: PlayerPool,
    simulator: DraftSimulator,
    current_pick: int,
    target_pick: int,
    drafted: set[str],
    roster_positions: dict[int, dict[str, int]] | None = None,
) -> SimulationResult:
    return simulator.run(
        current_pick=current_pick,
        target_pick=target_pick,
        drafted=drafted,
        roster_positions=roster_positions,
    )
