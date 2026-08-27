"""Monte Carlo simulator properties.

These are the invariants the wait-vs-take and what-if answers rest on, so they
are asserted directly rather than inferred from the endpoints above.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def pool_and_league():
    from app.models.league import LeagueSettings
    from app.scoring.board import get_pool

    league = LeagueSettings(scoring="ppr", teams=12, my_draft_slot=3)
    return get_pool(league), league


@pytest.fixture
def simulator(pool_and_league):
    from app.engine.simulator import DraftSimulator

    pool, league = pool_and_league
    return DraftSimulator(pool, league)


def test_the_same_seed_produces_the_same_draft(simulator):
    first = simulator.run(current_pick=4, target_pick=22, drafted=set())
    second = simulator.run(current_pick=4, target_pick=22, drafted=set())
    assert first.survival == second.survival


def test_different_seeds_produce_different_drafts(pool_and_league):
    from app.engine.simulator import DraftSimulator

    pool, league = pool_and_league
    a = DraftSimulator(pool, league, seed=1).run(4, 22, set())
    b = DraftSimulator(pool, league, seed=2).run(4, 22, set())
    assert a.survival != b.survival


def test_survival_never_rises_with_a_later_target_pick(simulator, pool_and_league):
    """Nobody becomes more likely to be available the longer you wait."""
    pool, _league = pool_and_league
    early = simulator.run(current_pick=4, target_pick=15, drafted=set())
    late = simulator.run(current_pick=4, target_pick=40, drafted=set())

    checked = 0
    for player_id in list(early.survival)[:120]:
        if player_id in late.survival:
            assert late.survival[player_id] <= early.survival[player_id] + 1e-9
            checked += 1
    assert checked > 50


def test_survival_probabilities_are_ordered_by_adp(simulator, pool_and_league):
    """A player taken earlier on average should be likelier to be gone."""
    pool, _league = pool_and_league
    result = simulator.run(current_pick=1, target_pick=25, drafted=set())
    ranked = sorted(
        ((pool.adp(pid), probability) for pid, probability in result.survival.items()
         if pool.adp(pid) is not None),
        key=lambda pair: pair[0],
    )
    early = [p for adp, p in ranked if adp <= 10]
    late = [p for adp, p in ranked if 40 <= adp <= 60]
    assert sum(early) / len(early) < sum(late) / len(late)


def test_probabilities_stay_in_range(simulator):
    result = simulator.run(current_pick=4, target_pick=30, drafted=set())
    assert all(0.0 <= p <= 1.0 for p in result.survival.values())
    assert result.runs > 0


def test_an_empty_window_leaves_everyone_available(simulator):
    result = simulator.run(current_pick=10, target_pick=10, drafted=set())
    assert all(p == 1.0 for p in result.survival.values())


def test_drafted_players_are_excluded_from_the_pool(simulator, pool_and_league):
    pool, _league = pool_and_league
    board = pool.board(current_pick=1, limit=5)
    drafted = {s.player.player_id for s in board}
    result = simulator.run(current_pick=6, target_pick=25, drafted=drafted)
    assert not (drafted & set(result.survival))


def test_expected_values_are_reported_per_position(simulator):
    result = simulator.run(current_pick=4, target_pick=25, drafted=set())
    assert {"RB", "WR", "TE", "QB"} <= set(result.expected_vorp_by_position)
    assert all(v >= 0 for v in result.expected_available_by_position.values())
