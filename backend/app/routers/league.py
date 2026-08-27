"""League configuration endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from app import db
from app.engine.draft_state import league_from_sleeper
from app.models.league import SCORING_PRESETS, LeagueSettings
from app.models.responses import LeagueCreate, LeagueFromSleeper, LeagueResponse
from app.scoring.board import clear_pools

router = APIRouter(prefix="/league", tags=["league"])


@router.post("", response_model=LeagueResponse, summary="Create or update a league")
def create_league(payload: LeagueCreate) -> LeagueResponse:
    league_id = payload.league_id or uuid.uuid4().hex[:12]
    db.save_league(league_id, payload.league.name, payload.league.model_dump(mode="json"))
    # Scoring or roster changes invalidate every cached board.
    clear_pools()
    return LeagueResponse(league_id=league_id, league=payload.league)


@router.get("", summary="List saved leagues")
def list_leagues() -> dict:
    return {"leagues": db.list_leagues()}


@router.get("/presets", summary="Scoring presets and their per-stat values")
def presets() -> dict:
    return {
        "scoring": SCORING_PRESETS,
        "default_roster": LeagueSettings().roster,
        "notes": (
            "Stat keys are nflverse column names. Send `scoring: custom` with "
            "`custom_scoring` to override individual values."
        ),
    }


@router.post("/from-sleeper", response_model=LeagueResponse,
             summary="Build a league from a Sleeper draft id")
def from_sleeper(payload: LeagueFromSleeper) -> LeagueResponse:
    try:
        league = league_from_sleeper(payload.sleeper_draft_id, payload.sleeper_user_id)
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller
        raise HTTPException(status_code=502, detail=f"Sleeper lookup failed: {exc}")
    league_id = uuid.uuid4().hex[:12]
    db.save_league(league_id, league.name, league.model_dump(mode="json"))
    clear_pools()
    return LeagueResponse(league_id=league_id, league=league)


@router.get("/{league_id}", response_model=LeagueResponse, summary="Fetch a league")
def get_league(league_id: str) -> LeagueResponse:
    payload = db.get_league(league_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"no league {league_id}")
    return LeagueResponse(league_id=league_id, league=LeagueSettings.model_validate(payload))


@router.patch("/{league_id}", response_model=LeagueResponse, summary="Update a league")
def update_league(league_id: str, league: LeagueSettings) -> LeagueResponse:
    if db.get_league(league_id) is None:
        raise HTTPException(status_code=404, detail=f"no league {league_id}")
    db.save_league(league_id, league.name, league.model_dump(mode="json"))
    clear_pools()
    return LeagueResponse(league_id=league_id, league=league)


@router.delete("/{league_id}", summary="Delete a league")
def delete_league(league_id: str) -> dict:
    if not db.delete_league(league_id):
        raise HTTPException(status_code=404, detail=f"no league {league_id}")
    return {"deleted": league_id}
