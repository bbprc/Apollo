"""The current-player guardrail."""

from __future__ import annotations

import pytest

from app.models.player import normalize_name


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Ja'Marr Chase", "jamarr chase"),
        ("JaMarr Chase", "jamarr chase"),
        ("Marvin Harrison Jr.", "marvin harrison"),
        ("A.J. Brown", "aj brown"),
        ("Amon-Ra St. Brown", "amon ra st brown"),
        ("  Puka   Nacua  ", "puka nacua"),
    ],
)
def test_name_normalization_folds_the_usual_mismatches(raw, expected):
    assert normalize_name(raw) == expected


def test_resolution_by_name_and_by_source_id(fake_registry):
    assert fake_registry.resolve("Ja'Marr Chase").player_id == "p1"
    assert fake_registry.resolve("jamarr chase").player_id == "p1"
    assert fake_registry.resolve("Marvin Harrison Jr").player_id == "p3"
    assert fake_registry.by_fantasypros_id("2").name == "Bijan Robinson"
    assert fake_registry.by_sleeper_id("s4").name == "Patrick Mahomes"
    assert fake_registry.by_gsis_id("g1").name == "Ja'Marr Chase"


def test_last_name_shorthand_resolves(fake_registry):
    assert fake_registry.resolve("Mahomes").player_id == "p4"


def test_unknown_players_do_not_resolve(fake_registry):
    for name in ("Tom Brady", "Peyton Manning", "Zeus Thunderbolt", ""):
        assert fake_registry.resolve(name) is None
        assert not fake_registry.knows_name(name)


def test_unknown_names_flags_only_players_outside_the_registry(fake_registry):
    text = "Take Ja'Marr Chase over Bijan Robinson."
    assert fake_registry.unknown_names(text) == []

    flagged = fake_registry.unknown_names("Tom Brady is still available.")
    assert flagged == ["Tom Brady"]


def test_sentence_initial_capitals_do_not_mask_or_invent_names(fake_registry):
    """A leading stopword must neither hide a fake name nor create one."""
    assert fake_registry.unknown_names("Consider Ja'Marr Chase here.") == []
    assert fake_registry.unknown_names("Draft Zeus Thunderbolt now.") == ["Zeus Thunderbolt"]
    assert fake_registry.unknown_names(
        "Bijan Robinson is the pick. However Ja'Marr Chase has value."
    ) == []


def test_team_names_are_not_mistaken_for_players(fake_registry):
    text = "The Kansas City Chiefs defense is tough, and the Green Bay Packers travel in Week 4."
    assert fake_registry.unknown_names(text) == []


def test_multiple_fabricated_names_are_all_flagged(fake_registry):
    flagged = fake_registry.unknown_names("I like Johnny Fakeplayer and Marcus Notreal.")
    assert flagged == ["Johnny Fakeplayer", "Marcus Notreal"]


def test_a_leading_verb_is_not_glued_onto_a_flagged_name(fake_registry):
    """The finding should be the name, not the sentence wrapped around it."""
    assert fake_registry.unknown_names("Consider Tom Brady instead.") == ["Tom Brady"]
    assert fake_registry.unknown_names(
        "Tom Brady is available. Consider Tom Brady instead."
    ) == ["Tom Brady"]


def test_search_and_position_filters(fake_registry):
    assert [p.name for p in fake_registry.search("chase")] == ["Ja'Marr Chase"]
    assert {p.name for p in fake_registry.by_position("WR")} == {
        "Ja'Marr Chase", "Marvin Harrison Jr.",
    }
    assert len(fake_registry) == 5


@pytest.mark.integration
def test_live_registry_holds_current_players_and_excludes_retired_ones():
    """The guardrail's real acceptance test, against live rosters."""
    from app.data.registry import get_registry

    registry = get_registry()
    assert len(registry) > 500

    for name in ("Ja'Marr Chase", "Patrick Mahomes", "Bijan Robinson"):
        player = registry.resolve(name)
        assert player is not None, f"{name} should be a current player"
        assert player.team

    for name in ("Tom Brady", "Peyton Manning", "Calvin Johnson", "Rob Gronkowski"):
        assert registry.resolve(name) is None, f"{name} is retired and must be excluded"
