"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import HTTPException, Query

from app.data.registry import PlayerRegistry, get_registry
from app.engine.draft_state import DraftNotFound, get_session
from app.models.draft import DraftSession
from app.scoring.board import PlayerPool, get_pool


def registry_dep() -> PlayerRegistry:
    return get_registry()


def session_dep(
    session_id: str = Query(..., description="Draft session id from POST /draft/sessions")
) -> DraftSession:
    try:
        return get_session(session_id)
    except DraftNotFound:
        raise HTTPException(status_code=404, detail=f"no draft session {session_id}")


def pool_for(session: DraftSession) -> PlayerPool:
    return get_pool(session.league)


def resolve_player_id(
    registry: PlayerRegistry,
    player_id: str | None,
    player_name: str | None,
    position: str | None = None,
    team: str | None = None,
) -> str:
    """Accept either a canonical id or a name, and fail loudly on neither."""
    if player_id:
        if registry.get(player_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"{player_id} is not a current player",
            )
        return player_id
    if player_name:
        player = registry.resolve(player_name, position, team)
        if player is None:
            suggestions = [p.name for p in registry.search(player_name, limit=5)]
            raise HTTPException(
                status_code=404,
                detail={
                    "message": f"'{player_name}' is not a current player",
                    "did_you_mean": suggestions,
                },
            )
        return player.player_id
    raise HTTPException(status_code=422, detail="provide player_id or player_name")
