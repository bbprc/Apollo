"""Scoring maths: stat lines, confidence components, VORP, availability."""

from __future__ import annotations

import pytest

from app.config import ConfidenceWeights
from app.engine.availability import closed_form_probability
from app.models.league import LeagueSettings
from app.models.player import PlayerProjection
from app.scoring.confidence import ConfidenceInput, ConfidenceScorer, squash, zscore
from app.scoring.league_scoring import score_stat_line, season_totals
from app.scoring.projections import points_at_rank, positional_ranks
from app.scoring.vorp import compute_vorp, replacement_ranks

STAT_LINE = {
    "receptions": 8, "receiving_yards": 110, "receiving_tds": 1, "rushing_yards": 5,
}


def test_reception_scoring_scales_with_the_preset():
    scores = [
        score_stat_line(STAT_LINE, LeagueSettings(scoring=s, my_draft_slot=1).scoring_rules())
        for s in ("standard", "half_ppr", "ppr")
    ]
    assert scores == [17.5, 21.5, 25.5]
    assert scores[0] < scores[1] < scores[2]


def test_unknown_and_malformed_stats_are_ignored_not_fatal():
    rules = LeagueSettings(scoring="ppr", my_draft_slot=1).scoring_rules()
    assert score_stat_line({"not_a_stat": 99, "receptions": None}, rules) == 0.0
    assert score_stat_line({"receptions": "abc", "receiving_yards": 100}, rules) == 10.0


def test_season_totals_aggregate_and_skip_the_postseason():
    league = LeagueSettings(scoring="ppr", my_draft_slot=1)
    rows = [
        {"player_id": "A", "season": 2025, "week": w, "season_type": "REG",
         "position": "WR", "team": "CIN", "receptions": 5, "receiving_yards": 50,
         "targets": 8}
        for w in range(1, 18)
    ] + [
        {"player_id": "A", "season": 2025, "week": 19, "season_type": "POST",
         "position": "WR", "team": "CIN", "receptions": 10, "receiving_yards": 200,
         "targets": 15}
    ]
    totals = season_totals(rows, league)[("A", 2025)]
    assert totals["games"] == 17
    assert totals["points"] == pytest.approx(17 * 10.0)
    assert totals["stats"]["targets"] == 17 * 8


def test_ranking_by_ppr_differs_from_standard():
    """A volume receiver should climb in PPR relative to a touchdown scorer."""
    catcher = {"receptions": 100, "receiving_yards": 1000, "receiving_tds": 3}
    scorer = {"receptions": 40, "receiving_yards": 1000, "receiving_tds": 10}

    ppr = LeagueSettings(scoring="ppr", my_draft_slot=1).scoring_rules()
    standard = LeagueSettings(scoring="standard", my_draft_slot=1).scoring_rules()

    assert score_stat_line(catcher, standard) < score_stat_line(scorer, standard)
    assert score_stat_line(catcher, ppr) > score_stat_line(scorer, ppr)


# --- confidence -----------------------------------------------------------

def test_adp_value_rewards_a_faller_not_a_reach():
    """An ADP earlier than the current pick is surplus, not a deficit."""
    fell_to_you = ConfidenceInput("a", "WR", adp=3, current_pick=8)
    reaching = ConfidenceInput("b", "WR", adp=30, current_pick=8)
    assert fell_to_you.adp_value() == 5.0
    assert reaching.adp_value() == -22.0


def test_confidence_ranks_the_better_profile_higher():
    pool = [
        ConfidenceInput("good", "WR", adp=3, current_pick=8, sos_season=1.05,
                        sos_playoffs=1.08, injury_risk=0.02, opportunity_share=0.30,
                        consensus_sd=1.0, consensus_ecr=3),
        ConfidenceInput("bad", "WR", adp=30, current_pick=8, sos_season=0.92,
                        sos_playoffs=0.90, injury_risk=0.45, opportunity_share=0.15,
                        consensus_sd=9.0, consensus_ecr=30),
    ]
    scorer = ConfidenceScorer(pool, ConfidenceWeights())
    good, _ = scorer.score(pool[0])
    bad, _ = scorer.score(pool[1])
    assert good > bad


def test_risk_and_disagreement_lower_confidence():
    base = dict(adp=10, current_pick=10, sos_season=1.0, sos_playoffs=1.0,
                opportunity_share=0.25, consensus_ecr=10)
    pool = [
        ConfidenceInput("durable", "WR", injury_risk=0.05, consensus_sd=1.0, **base),
        ConfidenceInput("fragile", "WR", injury_risk=0.50, consensus_sd=1.0, **base),
        ConfidenceInput("disputed", "WR", injury_risk=0.05, consensus_sd=12.0, **base),
    ]
    scorer = ConfidenceScorer(pool, ConfidenceWeights())
    durable, _ = scorer.score(pool[0])
    fragile, _ = scorer.score(pool[1])
    disputed, _ = scorer.score(pool[2])
    assert durable > fragile
    assert durable > disputed


def test_components_carry_their_own_weights_and_contributions():
    item = ConfidenceInput("x", "WR", adp=5, current_pick=10, injury_risk=0.1,
                           opportunity_share=0.25, consensus_sd=2.0, consensus_ecr=5)
    other = ConfidenceInput("y", "WR", adp=40, current_pick=10, injury_risk=0.4,
                            opportunity_share=0.10, consensus_sd=8.0, consensus_ecr=40)
    scorer = ConfidenceScorer([item, other], ConfidenceWeights())
    _score, components = scorer.score(item)
    names = {c.name for c in components}
    assert names == {
        "adp_value", "strength_of_schedule", "injury_risk",
        "opportunity_share", "consensus_uncertainty",
    }
    for component in components:
        assert component.contribution == pytest.approx(component.z_score * component.weight)


def test_squash_and_degenerate_zscores_are_safe():
    assert squash(0.0) == 50.0
    assert squash(5.0) > squash(1.0) > squash(-1.0)
    assert 0 <= squash(-50) and squash(50) <= 100
    assert zscore([])(1.0) == 0.0          # empty sample
    assert zscore([3.0])(3.0) == 0.0       # single sample
    assert zscore([2.0, 2.0, 2.0])(2.0) == 0.0  # no spread


# --- vorp -----------------------------------------------------------------

def test_replacement_level_deepens_with_league_size():
    ten = replacement_ranks(LeagueSettings(teams=10, my_draft_slot=1))
    twelve = replacement_ranks(LeagueSettings(teams=12, my_draft_slot=1))
    fourteen = replacement_ranks(LeagueSettings(teams=14, my_draft_slot=1))
    for position in ("QB", "RB", "WR", "TE"):
        assert ten[position] < twelve[position] < fourteen[position]


def test_extra_flex_slots_deepen_flex_eligible_positions_only():
    one_flex = replacement_ranks(LeagueSettings(teams=12, my_draft_slot=1))
    two_flex = replacement_ranks(LeagueSettings(
        teams=12, my_draft_slot=1,
        roster={"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 2, "K": 1, "DST": 1, "BENCH": 6},
    ))
    assert two_flex["RB"] > one_flex["RB"]
    assert two_flex["WR"] > one_flex["WR"]
    assert two_flex["QB"] == one_flex["QB"]


def test_vorp_is_points_above_the_replacement_player():
    league = LeagueSettings(teams=2, my_draft_slot=1,
                            roster={"QB": 0, "RB": 1, "WR": 0, "TE": 0, "FLEX": 0,
                                    "K": 0, "DST": 0, "BENCH": 2})
    projections = {
        f"rb{i}": PlayerProjection(player_id=f"rb{i}", projected_points=float(100 - i * 10))
        for i in range(5)
    }
    positions = {f"rb{i}": "RB" for i in range(5)}
    # Two teams starting one back each: the 2nd best back is replacement level.
    vorp = compute_vorp(league, projections, positions)
    assert vorp["rb0"] == pytest.approx(10.0)
    assert vorp["rb1"] == pytest.approx(0.0)
    assert vorp["rb2"] < 0


# --- projections ----------------------------------------------------------

def test_rank_curve_decreases_and_extrapolates_past_its_tail():
    curves = {"WR": [300.0, 250.0, 200.0]}
    assert points_at_rank(curves, "WR", 1) == 300.0
    assert points_at_rank(curves, "WR", 3) == 200.0
    beyond = points_at_rank(curves, "WR", 10)
    assert 0 < beyond < 200.0
    assert points_at_rank(curves, "QB", 1) == 0.0   # unknown position


def test_positional_ranks_order_within_position():
    rows = [
        {"id": "a", "pos": "WR", "ecr": 5.0},
        {"id": "b", "pos": "WR", "ecr": 2.0},
        {"id": "c", "pos": "RB", "ecr": 9.0},
        {"id": "d", "pos": "WR", "ecr": None},
    ]
    ranks = positional_ranks(rows)
    assert ranks["b"] == 1 and ranks["a"] == 2
    assert ranks["d"] == 3        # missing ecr sorts last
    assert ranks["c"] == 1        # ranked within its own position


# --- availability ---------------------------------------------------------

def test_closed_form_availability_is_monotonic_in_the_target_pick():
    probabilities = [closed_form_probability(20.0, 5.0, pick) for pick in (10, 20, 30, 40)]
    assert probabilities == sorted(probabilities, reverse=True)
    assert closed_form_probability(20.0, 5.0, 20) == pytest.approx(0.5, abs=0.01)
    assert closed_form_probability(None, 5.0, 20) is None
