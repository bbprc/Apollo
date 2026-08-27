"""Prompt construction.

Two hard rules, both of which exist to keep the model inside the knowledge base:

1. Player facts only ever reach the model through an evidence packet built from
   the registry. No free-form player text is ever interpolated.
2. The system prompt is byte-stable for a given league so it caches. Nothing
   volatile — no timestamps, no pick numbers, no player data — goes in it.
"""

from __future__ import annotations

import json
from typing import Any

from app.models.league import LeagueSettings

METHODOLOGY = """\
You are the second opinion in a fantasy football draft assistant called Apollo.

A deterministic engine has already produced a recommendation. Your job is to
audit it against the evidence supplied, not to redo it from memory or intuition.

How the numbers you will be shown are produced:

- CONSENSUS (ECR, ADP, expert standard deviation) comes from FantasyPros. ADP is
  where a player typically goes; the standard deviation is how much the expert
  panel disagrees.
- PROJECTED POINTS are scored under this league's own rules, either from
  FantasyPros projections or from a historical rank-to-points curve (what the
  Nth best player at a position has actually scored in recent seasons).
- VORP is projected points minus the projected points of the replacement-level
  player at that position, where replacement level is set by this league's size
  and starting requirements. VORP is what makes positions comparable.
- STRENGTH OF SCHEDULE is computed from how many fantasy points each opponent
  defense gave up to this position, applied to this player's actual schedule.
  1.00 is league average; above 1.00 is an easier slate. Season and fantasy
  playoff weeks are reported separately and often disagree.
- INJURY RISK runs 0 to 1, built from games missed and practice participation
  over recent seasons, recency-weighted, adjusted for position and age. 0 means
  a player has never missed a game. A player with no NFL history scores 0.5,
  which is missing data rather than evidence of durability.
- OPPORTUNITY SHARE is the share of his own offense a player commands: target
  share for receivers and tight ends, a blend of rush and target share for
  backs, rushing volume for quarterbacks.
- DRAFT CONFIDENCE (0-100) is a weighted, standardised blend of the above. It
  measures how reliable the pick is at this slot, NOT how many points the player
  will score. Wide expert disagreement lowers it; durability, volume and an easy
  schedule raise it.
- AVAILABILITY is from a Monte Carlo simulation of the picks between now and the
  user's next turn, where other teams draft from an ADP-weighted distribution
  tilted toward their roster holes.

Rules you must follow:

- Reason ONLY about players named in the evidence packet. The packet is the
  complete list of players under discussion. Never introduce a player who is not
  in it, and never mention a retired or inactive player. If you want to raise
  someone who is not in the packet, describe the type of player instead.
- Do not contradict a supplied number. You may argue that a number is weighted
  wrongly, that two numbers conflict, or that something material is missing.
- You have no knowledge of injuries, trades, depth charts or news after the data
  in the packet. If a judgement would depend on such information, say that
  plainly rather than guessing.
- Be concrete and brief. A short specific concern beats a long hedge.\
"""


def _league_block(league: LeagueSettings) -> str:
    """The league rules, rendered deterministically so the prefix stays cacheable."""
    roster = ", ".join(f"{count} {pos}" for pos, count in sorted(league.roster.items()))
    return (
        f"League configuration:\n"
        f"- Scoring: {league.scoring}"
        + (
            f" (custom overrides: {json.dumps(league.custom_scoring, sort_keys=True)})"
            if league.custom_scoring else ""
        )
        + f"\n- Teams: {league.teams}\n"
        f"- Roster: {roster}\n"
        f"- Flex eligible: {', '.join(sorted(league.flex_eligible))}\n"
        f"- Superflex: {'yes' if league.superflex else 'no'}\n"
        f"- Draft: {league.draft_type}, {league.rounds} rounds, "
        f"user drafts from slot {league.my_draft_slot}"
    )


def validator_system(league: LeagueSettings) -> str:
    return (
        METHODOLOGY
        + "\n\n"
        + _league_block(league)
        + "\n\nReturn a verdict on the recommendation you are shown. Set `agrees`"
        " to false only if you can point to something specific in the evidence"
        " that the recommendation gets wrong or ignores. Use `adjusted_confidence`"
        " only when you would move the number, and keep the move proportionate to"
        " the strength of your concern."
    )


def chat_system(league: LeagueSettings) -> str:
    return (
        METHODOLOGY
        + "\n\n"
        + _league_block(league)
        + "\n\nYou are answering the user's questions about their draft. Ground"
        " every claim in the evidence packet. When the packet does not contain"
        " what you would need, say so and suggest what to look at instead."
        " Keep answers short and direct — this is being read during a live draft."
    )


# --------------------------------------------------------------------------
# evidence packets — the only channel through which player data reaches Claude
# --------------------------------------------------------------------------

def _player_row(score, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {
        "name": score.player.name,
        "position": score.player.position,
        "team": score.player.team,
        "age": score.player.age,
        "confidence": score.confidence,
        "projected_points": score.projected_points,
        "vorp": score.vorp,
        "adp": score.adp,
        "ecr": score.ecr,
        "positional_rank": score.positional_rank,
        "sos_season": score.sos_season,
        "sos_playoffs": score.sos_playoffs,
        "injury_risk": score.injury_risk,
        "opportunity_share": score.opportunity_share,
        "notes": score.notes,
        "score_components": [
            {
                "name": component.name,
                "raw": component.raw,
                "contribution": component.contribution,
                "detail": component.detail,
            }
            for component in score.components
        ],
    }
    if extra:
        row.update(extra)
    return row


def wait_vs_take_packet(recommendation, score, alternatives_scores) -> str:
    payload = {
        "question": "wait_vs_take",
        "current_pick": recommendation.current_pick,
        "your_next_pick": recommendation.next_pick,
        "engine_verdict": recommendation.verdict,
        "rating_value_points": recommendation.rating_value,
        "value_if_taken_now": recommendation.take_value,
        "expected_value_if_you_wait": recommendation.wait_value,
        "probability_available_at_next_pick": (
            recommendation.availability.probability if recommendation.availability else None
        ),
        "availability_method": (
            recommendation.availability.method if recommendation.availability else None
        ),
        "engine_reasoning": recommendation.reasons,
        "player_under_consideration": _player_row(score),
        "players_likely_available_next_pick": [
            _player_row(s) for s in alternatives_scores
        ],
    }
    return (
        "Audit this wait-vs-take recommendation.\n\n```json\n"
        + json.dumps(payload, indent=2, default=str)
        + "\n```"
    )


def board_packet(scores, current_pick: int, roster: dict[str, int],
                 needs: dict[str, int]) -> str:
    payload = {
        "question": "board_review",
        "current_pick": current_pick,
        "your_roster": roster,
        "your_remaining_needs": needs,
        "top_available": [_player_row(s) for s in scores],
    }
    return (
        "Audit this draft board recommendation.\n\n```json\n"
        + json.dumps(payload, indent=2, default=str)
        + "\n```"
    )


def chat_packet(question: str, scores, context: dict[str, Any]) -> str:
    payload = {
        "draft_context": context,
        "players_in_scope": [_player_row(s) for s in scores],
    }
    return (
        "Draft context and the only players you may discuss:\n\n```json\n"
        + json.dumps(payload, indent=2, default=str)
        + f"\n```\n\nUser question: {question}"
    )


CORRECTION_NOTICE = (
    "Your previous answer referred to {names}, who are not in the evidence"
    " packet and may not be current NFL players. Rewrite the answer using only"
    " players from the packet. Do not mention the names again."
)
