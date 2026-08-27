"""Request and response schemas for the HTTP layer.

Every advice endpoint returns the same envelope — ``recommendation``,
``evidence``, ``validation`` — so a UI can bind to one shape regardless of which
question it asked, and so the Claude verdict is always visibly separate from the
computed result.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.league import LeagueSettings
from app.models.player import PlayerScore


class Envelope(BaseModel):
    """The uniform advice response."""

    recommendation: dict[str, Any]
    evidence: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(
        default_factory=lambda: {"status": "unavailable"},
        description="Claude's second-layer audit. Never overrides the computed result.",
    )


# --- league ---------------------------------------------------------------

class LeagueCreate(BaseModel):
    league: LeagueSettings
    league_id: str | None = None


class LeagueResponse(BaseModel):
    league_id: str
    league: LeagueSettings


class LeagueFromSleeper(BaseModel):
    sleeper_draft_id: str
    sleeper_user_id: str | None = None


# --- sessions -------------------------------------------------------------

class SessionCreate(BaseModel):
    league_id: str | None = None
    league: LeagueSettings | None = None
    sleeper_draft_id: str | None = Field(
        default=None,
        description="Link to a Sleeper draft. Settings are read from it when no league is given.",
    )
    sleeper_user_id: str | None = Field(
        default=None, description="Used to work out which draft slot is yours."
    )


class SessionResponse(BaseModel):
    session_id: str
    league: LeagueSettings
    sleeper_draft_id: str | None = None
    current_pick: int
    current_round: int
    is_my_pick: bool
    picks_made: int


class PickCreate(BaseModel):
    player_id: str | None = None
    player_name: str | None = Field(
        default=None, description="Alternative to player_id; resolved against the registry."
    )
    position: str | None = None
    team: str | None = None


# --- players --------------------------------------------------------------

class PlayerListResponse(BaseModel):
    count: int
    current_pick: int
    consensus_source: str
    players: list[PlayerScore]


class PlayerDetail(BaseModel):
    score: PlayerScore
    replacement_rank: int | None = None
    replacement_points: float | None = None
    injury_history: list[dict[str, Any]] = Field(default_factory=list)
    usage_trend: str | None = None
    bye_week: int | None = None
    availability: dict[str, Any] | None = None


# --- advice ---------------------------------------------------------------

class WhatIfRequest(BaseModel):
    player_id: str | None = None
    player_name: str | None = None
    horizon: int = Field(default=2, ge=1, le=4)
    validate_with_claude: bool = True


# --- chat -----------------------------------------------------------------

class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list)
    stream: bool = False


class ChatResponse(BaseModel):
    status: str
    answer: str | None = None
    players_in_context: list[str] = Field(default_factory=list)
    filtered_names: list[str] = Field(default_factory=list)
    detail: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
