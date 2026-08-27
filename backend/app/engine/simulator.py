"""Monte Carlo draft simulation.

Three questions in this app are really the same question — will he last, should
I wait, what happens if I take him — so they share one simulator rather than
three sets of assumptions that can drift apart.

Other teams are modelled as drafting from an ADP-weighted softmax over what is
left, tilted toward positions they still need to start. That is closer to how a
room actually behaves than assuming everyone follows ADP exactly (nobody does)
or that picks are independent draws (they are not — every pick removes a player
from everyone else's board).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from app.config import get_settings
from app.models.league import LeagueSettings
from app.scoring.board import PlayerPool

log = logging.getLogger(__name__)

#: Players whose ADP is far past the current pick are not realistically in
#: anyone's consideration set; capping the candidate pool keeps sims quick.
CANDIDATE_DEPTH = 180

#: Gumbel noise is generated in blocks of this many picks at a time.
_GUMBEL_BLOCK = 512

#: How strongly a roster hole pulls a team toward a position.
NEED_BOOST = 2.0
#: How strongly a filled position pushes them away from it.
SATURATION_PENALTY = 0.35


@dataclass
class SimulationResult:
    """Outcome of a Monte Carlo run between two picks."""

    runs: int
    target_pick: int
    #: player_id -> fraction of runs in which he was still on the board.
    survival: dict[str, float] = field(default_factory=dict)
    #: player_id -> fraction of runs in which he was the best available for us.
    best_available: dict[str, float] = field(default_factory=dict)
    #: position -> mean VORP of the best player left at that position.
    expected_vorp_by_position: dict[str, float] = field(default_factory=dict)
    #: position -> mean count of startable players left.
    expected_available_by_position: dict[str, float] = field(default_factory=dict)

    def probability_available(self, player_id: str) -> float:
        return self.survival.get(player_id, 0.0)


class DraftSimulator:
    """Simulates the picks between now and a pick we care about."""

    def __init__(self, pool: PlayerPool, league: LeagueSettings, seed: int | None = None):
        self.pool = pool
        self.league = league
        settings = get_settings()
        self.runs = settings.monte_carlo_runs
        self.temperature = settings.adp_softmax_temperature
        self.seed = settings.simulation_seed if seed is None else seed

    # -- candidate set -----------------------------------------------------

    def _candidates(self, drafted: set[str], current_pick: int) -> tuple[list[str], np.ndarray, list[str]]:
        """The players plausibly in play, with their ADPs and positions."""
        available = [
            pid for pid in self.pool.available_ids(drafted)
            if self.pool.adp(pid) is not None
        ]
        available.sort(key=lambda pid: self.pool.adp(pid) or 1e9)
        # Anyone whose ADP is well before now has already fallen; keep them,
        # they are exactly the bargains a room tends to snap up.
        trimmed = available[: max(CANDIDATE_DEPTH, 0)]
        adps = np.array([self.pool.adp(pid) or 1e9 for pid in trimmed], dtype=float)
        positions = [
            (self.pool.registry.get(pid).position if self.pool.registry.get(pid) else "")
            for pid in trimmed
        ]
        return trimmed, adps, positions

    # -- the run -----------------------------------------------------------

    def run(
        self,
        current_pick: int,
        target_pick: int,
        drafted: set[str],
        roster_positions: dict[int, dict[str, int]] | None = None,
        runs: int | None = None,
    ) -> SimulationResult:
        """Simulate from ``current_pick`` up to (not including) ``target_pick``.

        ``roster_positions`` maps draft slot -> position counts, so opponents
        draft for need. Missing slots are treated as empty rosters.
        """
        runs = runs or self.runs
        candidate_ids, adps, positions = self._candidates(drafted, current_pick)
        if not candidate_ids or target_pick <= current_pick:
            return SimulationResult(runs=0, target_pick=target_pick,
                                    survival={pid: 1.0 for pid in candidate_ids})

        n = len(candidate_ids)
        position_array = np.array(positions)
        unique_positions = sorted({p for p in positions if p})
        vorp = np.array(
            [self.pool.vorp.get(pid, 0.0) for pid in candidate_ids], dtype=float
        )

        # Which slots pick between now and the target, in order.
        picking_slots = [
            self.league.slot_on_the_clock(pick)
            for pick in range(current_pick, target_pick)
        ]
        pick_numbers = list(range(current_pick, target_pick))

        rng = np.random.default_rng(self.seed)
        # Gumbel noise is drawn in blocks; one call per pick is most of the cost.
        gumbel = rng.gumbel(size=(_GUMBEL_BLOCK, n))
        gumbel_row = 0
        survived = np.zeros(n, dtype=float)
        vorp_totals = {pos: 0.0 for pos in unique_positions}
        count_totals = {pos: 0.0 for pos in unique_positions}
        best_available_counts = np.zeros(n, dtype=float)

        base_needs = roster_positions or {}

        for _ in range(runs):
            alive = np.ones(n, dtype=bool)
            # Copy per-run so opponents' needs evolve as they draft.
            needs = {slot: dict(counts) for slot, counts in base_needs.items()}

            for slot, pick_no in zip(picking_slots, pick_numbers):
                if not alive.any():
                    break
                logits = -(adps - pick_no) / self.temperature

                counts = needs.setdefault(slot, {})
                multiplier = self._need_multipliers(counts, unique_positions)
                if multiplier:
                    adjust = np.array(
                        [multiplier.get(p, 1.0) for p in position_array], dtype=float
                    )
                    logits = logits + np.log(adjust)

                # Gumbel-max: argmax(logits + Gumbel noise) draws from the same
                # softmax as an explicit normalise-and-sample would, without
                # building the distribution on every pick.
                logits = np.where(alive, logits + gumbel[gumbel_row], -np.inf)
                gumbel_row += 1
                if gumbel_row >= gumbel.shape[0]:
                    gumbel = rng.gumbel(size=(_GUMBEL_BLOCK, n))
                    gumbel_row = 0

                choice = int(np.argmax(logits))
                if not np.isfinite(logits[choice]):
                    remaining = np.flatnonzero(alive)
                    if remaining.size == 0:
                        break
                    choice = int(remaining[0])

                alive[choice] = False
                taken_position = position_array[choice]
                if taken_position:
                    counts[taken_position] = counts.get(taken_position, 0) + 1

            survived += alive
            for pos in unique_positions:
                mask = alive & (position_array == pos)
                if mask.any():
                    vorp_totals[pos] += float(vorp[mask].max())
                    count_totals[pos] += float(mask.sum())
            if alive.any():
                best_available_counts[int(np.argmax(np.where(alive, vorp, -np.inf)))] += 1

        return SimulationResult(
            runs=runs,
            target_pick=target_pick,
            survival={
                pid: round(float(survived[i] / runs), 4)
                for i, pid in enumerate(candidate_ids)
            },
            best_available={
                pid: round(float(best_available_counts[i] / runs), 4)
                for i, pid in enumerate(candidate_ids)
                if best_available_counts[i] > 0
            },
            expected_vorp_by_position={
                pos: round(vorp_totals[pos] / runs, 2) for pos in unique_positions
            },
            expected_available_by_position={
                pos: round(count_totals[pos] / runs, 2) for pos in unique_positions
            },
        )

    @staticmethod
    def _need_multipliers(counts: dict[str, int], positions: list[str]) -> dict[str, float]:
        """Tilt a team toward positions it still has to fill.

        Deliberately crude: the aim is that a team with three backs and no
        receiver reaches for a receiver, not to model any particular manager.
        """
        # Roughly how many of each position a team wants before it stops caring.
        targets = {"QB": 2, "RB": 5, "WR": 6, "TE": 2, "K": 1, "DST": 1}
        multipliers: dict[str, float] = {}
        for position in positions:
            have = counts.get(position, 0)
            want = targets.get(position, 3)
            if have >= want:
                multipliers[position] = SATURATION_PENALTY
            elif have == 0 and want > 1:
                multipliers[position] = NEED_BOOST
            else:
                multipliers[position] = 1.0
        return multipliers
