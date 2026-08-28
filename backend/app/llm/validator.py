"""The second-layer validation pass.

The deterministic engine decides; Claude audits. A disagreement never overrides
the numbers — it is attached to the response so the user sees both, and an
adjusted confidence is reported alongside the computed one rather than
replacing it.

Every response is checked back against the registry before it is returned, so a
player who is not in the knowledge base cannot reach the user.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.data.registry import PlayerRegistry, get_registry
from app.llm import client as llm_client
from app.llm import prompts
from app.models.league import LeagueSettings

log = logging.getLogger(__name__)


class Verdict(BaseModel):
    """What the auditor returns. Kept small so the schema is easy to satisfy."""

    agrees: bool = Field(description="Whether the recommendation holds up against the evidence")
    adjusted_confidence: int | None = Field(
        default=None, ge=0, le=100,
        description="Only set this if you would move the confidence score",
    )
    concerns: list[str] = Field(
        default_factory=list,
        description="Specific problems with the recommendation, each grounded in the evidence",
    )
    supporting: list[str] = Field(
        default_factory=list,
        description="Evidence that most supports the recommendation",
    )
    reasoning: str = Field(description="Two or three sentences explaining the verdict")


def _scrub(result_text_fields: list[str], registry: PlayerRegistry) -> list[str]:
    """Names mentioned in the verdict that are not current players."""
    unknown: list[str] = []
    for text in result_text_fields:
        for name in registry.unknown_names(text or ""):
            if name not in unknown:
                unknown.append(name)
    return unknown


def _verdict_text(verdict: Verdict) -> list[str]:
    return [verdict.reasoning, *verdict.concerns, *verdict.supporting]


def validate(
    league: LeagueSettings,
    user_content: str,
    registry: PlayerRegistry | None = None,
    depth: str = "deep",
) -> dict[str, Any]:
    """Run the audit, retrying once if the answer strays outside the registry.

    Returns a dict suitable for the ``validation`` slot of an API response. It
    always has a ``status``; callers must not assume more than that.
    """
    registry = registry or get_registry()
    system = prompts.validator_system(league)

    result = llm_client.parse(system, user_content, Verdict, depth=depth)
    if not result.ok:
        return result.to_dict()

    verdict: Verdict = result.parsed
    unknown = _scrub(_verdict_text(verdict), registry)

    if unknown:
        log.warning("validator named unknown players %s; retrying once", unknown)
        correction = prompts.CORRECTION_NOTICE.format(names=", ".join(unknown))
        retry = llm_client.parse(
            system, f"{user_content}\n\n{correction}", Verdict, depth=depth
        )
        if retry.ok:
            verdict = retry.parsed
            result = retry
            unknown = _scrub(_verdict_text(verdict), registry)

    payload: dict[str, Any] = {
        "status": "ok",
        "agrees": verdict.agrees,
        "adjusted_confidence": verdict.adjusted_confidence,
        "concerns": verdict.concerns,
        "supporting": verdict.supporting,
        "reasoning": verdict.reasoning,
        "usage": result.usage,
    }

    if unknown:
        # Still outside the knowledge base after a correction: strip the prose
        # rather than pass along a claim about somebody we cannot vouch for.
        payload.update(
            {
                "status": "filtered",
                "concerns": [],
                "supporting": [],
                "reasoning": (
                    "The reviewer referenced players outside the current-season "
                    "knowledge base, so its commentary was withheld."
                ),
                "filtered_names": unknown,
            }
        )
    return payload


def validate_wait_vs_take(league, recommendation, score, alternatives,
                          registry: PlayerRegistry | None = None,
                          depth: str = "deep") -> dict[str, Any]:
    if not llm_client.is_enabled():
        return {"status": "unavailable", "detail": "ANTHROPIC_API_KEY is not set"}
    return validate(
        league,
        prompts.wait_vs_take_packet(recommendation, score, alternatives),
        registry,
        depth=depth,
    )


def validate_board(league, scores, current_pick: int, roster: dict[str, int],
                   needs: dict[str, int],
                   registry: PlayerRegistry | None = None,
                   depth: str = "deep") -> dict[str, Any]:
    if not llm_client.is_enabled():
        return {"status": "unavailable", "detail": "ANTHROPIC_API_KEY is not set"}
    return validate(
        league,
        prompts.board_packet(scores, current_pick, roster, needs),
        registry,
        depth=depth,
    )
