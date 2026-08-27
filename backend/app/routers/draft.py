"""Draft session endpoints: create, sync from Sleeper, record picks, read state."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.data.registry import PlayerRegistry
from app.engine import draft_state
from app.models.draft import DraftSession
from app.models.league import LeagueSettings
from app.models.responses import PickCreate, SessionCreate, SessionResponse
from app.routers.deps import registry_dep, resolve_player_id, session_dep

router = APIRouter(prefix="/draft", tags=["draft"])


def _summary(session: DraftSession) -> SessionResponse:
    return SessionResponse(
        session_id=session.session_id,
        league=session.league,
        sleeper_draft_id=session.sleeper_draft_id,
        current_pick=session.current_pick,
        current_round=session.current_round,
        is_my_pick=session.is_my_pick(),
        picks_made=len(session.picks),
    )


@router.post("/sessions", response_model=SessionResponse, summary="Start a draft session")
def create_session(payload: SessionCreate) -> SessionResponse:
    """Settings come from ``league``, a saved ``league_id``, or the Sleeper draft."""
    league: LeagueSettings | None = payload.league

    if league is None and payload.league_id:
        stored = db.get_league(payload.league_id)
        if stored is None:
            raise HTTPException(status_code=404, detail=f"no league {payload.league_id}")
        league = LeagueSettings.model_validate(stored)

    if league is None and payload.sleeper_draft_id:
        try:
            league = draft_state.league_from_sleeper(
                payload.sleeper_draft_id, payload.sleeper_user_id
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Sleeper lookup failed: {exc}")

    if league is None:
        raise HTTPException(
            status_code=422,
            detail="provide league, league_id, or sleeper_draft_id",
        )

    session = draft_state.create_session(
        league, payload.sleeper_draft_id, payload.league_id
    )
    return _summary(session)


@router.get("/sessions", summary="List draft sessions")
def list_sessions() -> dict:
    return {"sessions": draft_state.list_sessions()}


@router.get("/state", summary="Full draft state: picks, rosters, who is on the clock")
def get_state(session: DraftSession = Depends(session_dep),
              registry: PlayerRegistry = Depends(registry_dep)) -> dict:
    rosters = session.rosters()
    return {
        "session_id": session.session_id,
        "current_pick": session.current_pick,
        "current_round": session.current_round,
        "on_the_clock_slot": session.league.slot_on_the_clock(session.current_pick),
        "is_my_pick": session.is_my_pick(),
        "my_draft_slot": session.league.my_draft_slot,
        "my_next_pick": session.my_next_pick(),
        "my_following_pick": session.my_following_pick(),
        "my_remaining_picks": [
            p for p in session.league.my_picks() if p >= session.current_pick
        ],
        "picks": [p.model_dump(mode="json") for p in session.picks],
        "rosters": {
            slot: {
                "players": [
                    registry.get(pid).name for pid in roster.player_ids if registry.get(pid)
                ],
                "positions": roster.positions,
                "needs": {k: v for k, v in roster.needs(session.league).items() if v > 0},
            }
            for slot, roster in rosters.items()
        },
    }


@router.post("/picks", response_model=SessionResponse, summary="Record a pick")
def record_pick(payload: PickCreate,
                session: DraftSession = Depends(session_dep),
                registry: PlayerRegistry = Depends(registry_dep)) -> SessionResponse:
    player_id = resolve_player_id(
        registry, payload.player_id, payload.player_name, payload.position, payload.team
    )
    try:
        draft_state.record_pick(session, player_id, registry)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _summary(session)


@router.delete("/picks/last", response_model=SessionResponse, summary="Undo the last pick")
def undo_pick(session: DraftSession = Depends(session_dep)) -> SessionResponse:
    try:
        draft_state.undo_pick(session)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _summary(session)


@router.post("/sync", summary="Pull picks from the linked Sleeper draft")
def sync(session: DraftSession = Depends(session_dep),
         registry: PlayerRegistry = Depends(registry_dep)) -> dict:
    try:
        return draft_state.sync_from_sleeper(session, registry)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Sleeper sync failed: {exc}")


@router.delete("/sessions", summary="Delete a draft session")
def delete_session(session: DraftSession = Depends(session_dep)) -> dict:
    draft_state.delete_session(session.session_id)
    return {"deleted": session.session_id}
