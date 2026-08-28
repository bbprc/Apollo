"""Positional timing: the rules that stop an arithmetically fine pick being a bad one."""

import pytest

from app.models.league import LeagueSettings
from app.scoring.draft_strategy import note_for, timing_multiplier, windows_for


@pytest.fixture
def league() -> LeagueSettings:
    return LeagueSettings(name="t", teams=12, rounds=15, my_draft_slot=12)


def test_elite_te_passes_in_round_two_but_elite_qb_does_not(league):
    """The whole point of declaring the exception per position.

    Both are the best player at their position, and a generic "tier one" rule
    would let both through. Tight end replacement is dreadful so the exception
    is real; QB12 scores nearly what QB1 does, so it is not.
    """
    assert timing_multiplier("TE", 2, 2, league) == 1.0
    assert timing_multiplier("QB", 2, 1, league) < 0.5


def test_quarterback_becomes_legal_in_its_window(league):
    early = timing_multiplier("QB", 2, 1, league)
    later = timing_multiplier("QB", 4, 1, league)
    assert early < later < 1.0
    assert timing_multiplier("QB", 6, 1, league) == 1.0


def test_superflex_inverts_the_quarterback_rule(league):
    superflex = league.model_copy(update={"superflex": True})
    assert timing_multiplier("QB", 1, 1, league) < 0.5
    assert timing_multiplier("QB", 1, 1, superflex) == 1.0


@pytest.mark.parametrize("profile", ["balanced", "zero_rb", "robust_rb", "hero_rb", "late_qb"])
def test_kicker_and_defense_are_never_early_whatever_the_strategy(league, profile):
    assert timing_multiplier("K", 5, 1, league, profile) < 0.5
    assert timing_multiplier("DST", 5, 1, league, profile) < 0.5
    assert timing_multiplier("K", league.rounds, 1, league, profile) == 1.0


def test_windows_scale_to_a_shorter_draft():
    short = LeagueSettings(name="t", teams=12, rounds=10, my_draft_slot=1)
    windows = windows_for(short)
    assert windows["K"].normal == (10, 10)
    assert windows["QB"].earliest < 6


def test_hero_rb_frees_the_first_back_and_holds_the_rest(league):
    assert timing_multiplier("RB", 2, 1, league, "hero_rb", {}) == 1.0
    assert timing_multiplier("RB", 2, 1, league, "hero_rb", {"RB": 1}) < 0.5


def test_robust_rb_makes_receivers_wait_until_two_backs_are_banked(league):
    assert timing_multiplier("WR", 2, 1, league, "robust_rb", {}) < 1.0
    assert timing_multiplier("WR", 2, 1, league, "robust_rb", {"RB": 2}) == 1.0


def test_note_explains_a_held_back_position_and_stays_quiet_otherwise(league):
    assert "rounds" in (note_for("QB", 2, league) or "")
    assert note_for("QB", 8, league) is None
    assert note_for("RB", 1, league) is None
