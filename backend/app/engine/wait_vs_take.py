"""Take him now, or wait?

The question is not "is he good" — it is "what do I give up by waiting". So the
comparison is between his value over replacement now and the value over
replacement of whoever would still be there at my next pick, weighted by how
likely he is to survive that long.

The number the UI shows as the rating value is that gap, in projected points.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.engine.availability import Availability, probability_available
from app.engine.simulator import DraftSimulator, SimulationResult
from app.models.draft import DraftSession
from app.scoring.board import PlayerPool

log = logging.getLogger(__name__)

Verdict = str  # "TAKE" | "WAIT" | "EITHER"


@dataclass
class WaitVsTake:
    player_id: str
    player_name: str
    position: str
    verdict: Verdict
    #: Expected projected points surrendered by waiting. This is the headline.
    rating_value: float
    confidence: float
    current_pick: int
    next_pick: int | None
    availability: Availability | None
    take_value: float
    wait_value: float
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "position": self.position,
            "verdict": self.verdict,
            "rating_value": self.rating_value,
            "confidence": self.confidence,
            "current_pick": self.current_pick,
            "next_pick": self.next_pick,
            "probability_available_next_pick": (
                self.availability.probability if self.availability else None
            ),
            "availability_method": self.availability.method if self.availability else None,
            "take_value": self.take_value,
            "wait_value": self.wait_value,
            "alternatives": self.alternatives,
            "reasons": self.reasons,
        }


def evaluate(
    pool: PlayerPool,
    session: DraftSession,
    player_id: str,
    simulator: DraftSimulator | None = None,
    simulation: SimulationResult | None = None,
) -> WaitVsTake:
    """Decide whether to take a player now or wait for the next turn."""
    settings = get_settings()
    league = session.league
    player = pool.registry.get(player_id)
    if player is None:
        raise KeyError(f"{player_id} is not a current player")

    current_pick = session.current_pick
    next_pick = session.my_following_pick() if session.is_my_pick() else session.my_next_pick()
    take_value = pool.vorp.get(player_id, 0.0)

    if next_pick is None:
        return WaitVsTake(
            player_id=player_id,
            player_name=player.name,
            position=player.position,
            verdict="TAKE",
            rating_value=round(take_value, 2),
            confidence=1.0,
            current_pick=current_pick,
            next_pick=None,
            availability=None,
            take_value=round(take_value, 2),
            wait_value=0.0,
            reasons=["this is your last pick, so there is nothing to wait for"],
        )

    simulator = simulator or DraftSimulator(pool, league)
    if simulation is None or simulation.target_pick != next_pick:
        roster_positions = {
            slot: dict(roster.positions) for slot, roster in session.rosters().items()
        }
        simulation = simulator.run(
            current_pick=current_pick,
            target_pick=next_pick,
            drafted=session.drafted_ids,
            roster_positions=roster_positions,
        )

    availability = probability_available(pool, player_id, next_pick, simulation)

    # What the position is expected to yield if we pass now.
    wait_value = simulation.expected_vorp_by_position.get(player.position, 0.0)
    # Surviving is one of the futures, so blend it in: some of the time the
    # player we are considering is himself the best thing left.
    blended_wait = (
        availability.probability * max(take_value, wait_value)
        + (1 - availability.probability) * wait_value
    )

    gap = take_value - blended_wait
    threshold = settings.wait_vs_take_threshold

    if gap > threshold:
        verdict = "TAKE"
    elif gap < -threshold:
        verdict = "WAIT"
    else:
        verdict = "EITHER"

    # How sure we are of the verdict: distance past the threshold, saturating.
    confidence = round(min(abs(gap) / (threshold * 3.0), 1.0), 3)

    reasons = _reasons(player, availability, gap, take_value, blended_wait, verdict,
                       next_pick, session.picks_until(next_pick))

    alternatives = _alternatives(pool, simulation, player.position, exclude=player_id)

    return WaitVsTake(
        player_id=player_id,
        player_name=player.name,
        position=player.position,
        verdict=verdict,
        rating_value=round(gap, 2),
        confidence=confidence,
        current_pick=current_pick,
        next_pick=next_pick,
        availability=availability,
        take_value=round(take_value, 2),
        wait_value=round(blended_wait, 2),
        alternatives=alternatives,
        reasons=reasons,
    )


def _reasons(player, availability, gap, take_value, wait_value, verdict,
             next_pick, picks_between) -> list[str]:
    reasons = [
        f"{player.name} is worth {take_value:.0f} points over replacement at "
        f"{player.position} right now.",
        f"Your next pick is {next_pick}, {picks_between} picks away; he survives "
        f"that stretch {availability.probability:.0%} of the time "
        f"({availability.method.replace('_', ' ')}).",
        f"The best {player.position} expected to be there is worth about "
        f"{wait_value:.0f} over replacement.",
    ]
    if verdict == "TAKE":
        reasons.append(
            f"Waiting costs about {gap:.0f} projected points, so take him."
        )
    elif verdict == "WAIT":
        reasons.append(
            f"You gain about {abs(gap):.0f} projected points by waiting — the "
            f"position holds up better than he does."
        )
    else:
        reasons.append(
            f"The gap is only {gap:+.0f} points, inside the noise. Take the "
            f"player you prefer, or the scarcer position."
        )
    return reasons


def _alternatives(pool: PlayerPool, simulation: SimulationResult, position: str,
                  exclude: str, limit: int = 5) -> list[dict[str, Any]]:
    """Who else at this position is likely to be there next turn."""
    rows = []
    for player_id, probability in simulation.survival.items():
        if player_id == exclude or probability < 0.25:
            continue
        player = pool.registry.get(player_id)
        if player is None or player.position != position:
            continue
        rows.append(
            {
                "player_id": player_id,
                "name": player.name,
                "team": player.team,
                "vorp": pool.vorp.get(player_id),
                "adp": pool.adp(player_id),
                "probability_available": probability,
            }
        )
    rows.sort(key=lambda r: (r["vorp"] or -1e9), reverse=True)
    return rows[:limit]
