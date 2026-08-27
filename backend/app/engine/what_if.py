"""What if I take this player — how does my next round look?

Takes the pick hypothetically, then simulates the room's response up to the
next one or two turns, and reports what the board is expected to look like when
it comes back around: who is likely there, what each roster hole is worth by
then, and what the pick has done to the shape of the team.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.engine.simulator import DraftSimulator
from app.models.draft import DraftSession
from app.scoring.board import PlayerPool

log = logging.getLogger(__name__)

#: How many turns forward to project. Two is the useful horizon — beyond that
#: the simulation is dominated by picks nobody can anticipate.
DEFAULT_HORIZON = 2


@dataclass
class RoundOutlook:
    pick: int
    round: int
    expected_best_available: list[dict[str, Any]] = field(default_factory=list)
    expected_vorp_by_position: dict[str, float] = field(default_factory=dict)
    expected_available_by_position: dict[str, float] = field(default_factory=dict)


@dataclass
class WhatIf:
    player_id: str
    player_name: str
    position: str
    pick: int
    roster_after: dict[str, int]
    remaining_needs: dict[str, int]
    outlook: list[RoundOutlook] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "position": self.position,
            "pick": self.pick,
            "roster_after": self.roster_after,
            "remaining_needs": self.remaining_needs,
            "outlook": [
                {
                    "pick": o.pick,
                    "round": o.round,
                    "expected_best_available": o.expected_best_available,
                    "expected_vorp_by_position": o.expected_vorp_by_position,
                    "expected_available_by_position": o.expected_available_by_position,
                }
                for o in self.outlook
            ],
            "summary": self.summary,
        }


def simulate_pick(
    pool: PlayerPool,
    session: DraftSession,
    player_id: str,
    horizon: int = DEFAULT_HORIZON,
    simulator: DraftSimulator | None = None,
) -> WhatIf:
    """Project the next ``horizon`` turns if we take ``player_id`` now."""
    player = pool.registry.get(player_id)
    if player is None:
        raise KeyError(f"{player_id} is not a current player")
    if player_id in session.drafted_ids:
        raise ValueError(f"{player.name} has already been drafted")

    league = session.league
    simulator = simulator or DraftSimulator(pool, league)

    # Work on a copy — a hypothetical must never mutate the live draft.
    hypothetical = session.model_copy(deep=True)
    hypothetical.add_pick(player_id, player.name, player.position, source="what_if")

    my_roster = hypothetical.my_roster()
    roster_after = dict(my_roster.positions)
    remaining_needs = {
        position: count
        for position, count in my_roster.needs(league).items()
        if count > 0
    }

    # The needs we report describe the roster right after the hypothetical
    # pick. The forward simulation needs its own copy to draw down, or the
    # reported needs would silently reflect picks we only imagined making.
    projected_needs = dict(remaining_needs)

    outlook: list[RoundOutlook] = []
    cursor = hypothetical.current_pick
    drafted = set(hypothetical.drafted_ids)
    roster_positions = {
        slot: dict(roster.positions) for slot, roster in hypothetical.rosters().items()
    }

    for _ in range(horizon):
        target = next(
            (p for p in league.my_picks() if p >= cursor), None
        )
        if target is None:
            break

        result = simulator.run(
            current_pick=cursor,
            target_pick=target,
            drafted=drafted,
            roster_positions=roster_positions,
        )

        survivors = [
            {
                "player_id": pid,
                "name": pool.registry.get(pid).name,
                "position": pool.registry.get(pid).position,
                "team": pool.registry.get(pid).team,
                "vorp": pool.vorp.get(pid),
                "adp": pool.adp(pid),
                "probability_available": probability,
                "fills_a_need": pool.registry.get(pid).position in projected_needs,
            }
            for pid, probability in result.survival.items()
            if probability >= 0.4 and pool.registry.get(pid) is not None
        ]
        survivors.sort(key=lambda r: (r["vorp"] or -1e9), reverse=True)

        outlook.append(
            RoundOutlook(
                pick=target,
                round=(target - 1) // league.teams + 1,
                expected_best_available=survivors[:8],
                expected_vorp_by_position=result.expected_vorp_by_position,
                expected_available_by_position=result.expected_available_by_position,
            )
        )

        # Advance past our own turn: assume we take the best thing on the board
        # that fills a hole, which is what the rest of this app would advise.
        if survivors:
            needed = [s for s in survivors if s["fills_a_need"]] or survivors
            taken = needed[0]
            drafted.add(taken["player_id"])
            slot = league.my_draft_slot
            roster_positions.setdefault(slot, {})
            roster_positions[slot][taken["position"]] = (
                roster_positions[slot].get(taken["position"], 0) + 1
            )
            position = taken["position"]
            if projected_needs.get(position):
                projected_needs[position] -= 1
                if projected_needs[position] <= 0:
                    projected_needs.pop(position, None)
        cursor = target + 1

    return WhatIf(
        player_id=player_id,
        player_name=player.name,
        position=player.position,
        pick=session.current_pick,
        roster_after=roster_after,
        remaining_needs=remaining_needs,
        outlook=outlook,
        summary=_summarise(player, roster_after, remaining_needs, outlook),
    )


def _summarise(player, roster_after, remaining_needs, outlook) -> list[str]:
    lines = [
        f"Taking {player.name} leaves you with "
        + ", ".join(f"{count} {pos}" for pos, count in sorted(roster_after.items()))
        + "."
    ]
    if remaining_needs:
        lines.append(
            "Still to fill: "
            + ", ".join(f"{count} {pos}" for pos, count in sorted(remaining_needs.items()))
            + "."
        )
    else:
        lines.append("Your starting lineup would be complete.")

    for entry in outlook:
        if not entry.expected_best_available:
            continue
        top = entry.expected_best_available[0]
        needs_at = [
            f"{pos} ~{value:.0f}"
            for pos, value in sorted(
                entry.expected_vorp_by_position.items(),
                key=lambda kv: kv[1], reverse=True,
            )[:3]
        ]
        lines.append(
            f"At pick {entry.pick} (round {entry.round}) expect {top['name']} "
            f"({top['position']}) to be there {top['probability_available']:.0%} of "
            f"the time; best value by position: {', '.join(needs_at)}."
        )
    return lines


def compare(
    pool: PlayerPool,
    session: DraftSession,
    player_ids: list[str],
    horizon: int = DEFAULT_HORIZON,
) -> list[WhatIf]:
    """Run the same what-if across several candidates for side-by-side reading."""
    simulator = DraftSimulator(pool, session.league)
    return [
        simulate_pick(pool, session, player_id, horizon=horizon, simulator=simulator)
        for player_id in player_ids
    ]
