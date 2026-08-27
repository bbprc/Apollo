"""League configuration: scoring presets, draft order, and roster needs."""

from __future__ import annotations

import pytest

from app.models.draft import DraftSession, Roster
from app.models.league import LeagueSettings


def test_scoring_presets_differ_only_in_receptions():
    ppr = LeagueSettings(scoring="ppr", my_draft_slot=1).scoring_rules()
    half = LeagueSettings(scoring="half_ppr", my_draft_slot=1).scoring_rules()
    standard = LeagueSettings(scoring="standard", my_draft_slot=1).scoring_rules()

    assert (ppr["receptions"], half["receptions"], standard["receptions"]) == (1.0, 0.5, 0.0)
    for key in standard:
        if key != "receptions":
            assert ppr[key] == standard[key]


def test_custom_scoring_overrides_the_preset():
    league = LeagueSettings(
        scoring="custom", my_draft_slot=1,
        custom_scoring={"receptions": 1.5, "passing_tds": 6.0},
    )
    rules = league.scoring_rules()
    assert rules["receptions"] == 1.5
    assert rules["passing_tds"] == 6.0
    # Unlisted stats still fall back to the standard preset.
    assert rules["rushing_tds"] == 6.0


def test_custom_scoring_is_required_when_selected():
    with pytest.raises(ValueError, match="custom_scoring is required"):
        LeagueSettings(scoring="custom", my_draft_slot=1)


def test_draft_slot_must_fit_the_league():
    with pytest.raises(ValueError, match="exceeds teams"):
        LeagueSettings(teams=10, my_draft_slot=11)


def test_snake_order_reverses_on_even_rounds():
    league = LeagueSettings(teams=12, my_draft_slot=3, rounds=4)
    assert league.my_picks() == [3, 22, 27, 46]
    assert league.slot_on_the_clock(3) == 3
    assert league.slot_on_the_clock(13) == 12    # first pick of round 2
    assert league.slot_on_the_clock(24) == 1     # last pick of round 2


def test_linear_order_does_not_reverse():
    league = LeagueSettings(teams=10, my_draft_slot=4, rounds=3, draft_type="linear")
    assert league.my_picks() == [4, 14, 24]
    assert league.slot_on_the_clock(11) == 1


def test_every_pick_maps_to_exactly_one_slot():
    league = LeagueSettings(teams=12, my_draft_slot=1, rounds=15)
    for slot in range(1, 13):
        for pick in league.pick_numbers_for_slot(slot):
            assert league.slot_on_the_clock(pick) == slot


def test_flex_is_attributed_to_the_thinnest_eligible_position():
    league = LeagueSettings(teams=12, my_draft_slot=1)
    roster = Roster(slot=1)
    needs = roster.needs(league)
    # 3 WR required plus the flex, since nothing is filled yet.
    assert needs["WR"] == 4
    assert needs["RB"] == 2

    roster.add("WR", "a")
    roster.add("WR", "b")
    roster.add("WR", "c")
    assert roster.needs(league)["WR"] == 0


def test_superflex_deepens_quarterback_demand():
    from app.scoring.vorp import replacement_ranks

    normal = replacement_ranks(LeagueSettings(teams=12, my_draft_slot=1))
    superflex = replacement_ranks(
        LeagueSettings(teams=12, my_draft_slot=1, superflex=True)
    )
    assert superflex["QB"] > normal["QB"]


def test_session_tracks_the_clock():
    league = LeagueSettings(teams=12, my_draft_slot=3, rounds=15)
    session = DraftSession(session_id="t", league=league)
    assert session.current_pick == 1 and not session.is_my_pick()

    for i in range(2):
        session.add_pick(f"p{i}", f"Player {i}", "RB")
    assert session.current_pick == 3 and session.is_my_pick()
    assert session.my_next_pick() == 3
    assert session.my_following_pick() == 22
