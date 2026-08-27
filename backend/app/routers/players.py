"""Player board and per-player detail."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.data.registry import PlayerRegistry
from app.engine.availability import probability_available
from app.engine.simulator import DraftSimulator
from app.models.draft import DraftSession
from app.models.responses import PlayerDetail, PlayerListResponse
from app.routers.deps import pool_for, registry_dep, session_dep

router = APIRouter(prefix="/players", tags=["players"])


@router.get("", response_model=PlayerListResponse, summary="Ranked board of available players")
def list_players(
    session: DraftSession = Depends(session_dep),
    position: list[str] | None = Query(default=None, description="Filter, e.g. RB&position=WR"),
    limit: int = Query(default=50, ge=1, le=500),
    include_drafted: bool = Query(default=False),
) -> PlayerListResponse:
    pool = pool_for(session)
    drafted = set() if include_drafted else session.drafted_ids
    board = pool.board(
        current_pick=session.current_pick,
        drafted=drafted,
        positions=position,
        limit=limit,
    )
    return PlayerListResponse(
        count=len(board),
        current_pick=session.current_pick,
        consensus_source=pool.consensus_source,
        players=board,
    )


@router.get("/search", summary="Find current players by name")
def search(
    q: str = Query(..., min_length=2),
    limit: int = Query(default=10, ge=1, le=50),
    registry: PlayerRegistry = Depends(registry_dep),
) -> dict:
    return {
        "query": q,
        "results": [
            {
                "player_id": p.player_id,
                "name": p.name,
                "position": p.position,
                "team": p.team,
            }
            for p in registry.search(q, limit=limit)
        ],
    }


@router.get("/{player_id}", response_model=PlayerDetail, summary="Full breakdown for one player")
def get_player(
    player_id: str,
    session: DraftSession = Depends(session_dep),
    registry: PlayerRegistry = Depends(registry_dep),
) -> PlayerDetail:
    player = registry.get(player_id)
    if player is None:
        raise HTTPException(status_code=404, detail=f"{player_id} is not a current player")

    pool = pool_for(session)
    board = pool.board(
        current_pick=session.current_pick,
        drafted=session.drafted_ids - {player_id},
    )
    score = next((s for s in board if s.player.player_id == player_id), None)
    if score is None:
        raise HTTPException(
            status_code=404,
            detail=f"{player.name} has no consensus ranking, so he cannot be scored",
        )

    signals = pool.signals(player_id)
    replacement_rank = pool.replacement_ranks.get(player.position)

    # When it is already our turn, the interesting question is whether he
    # survives to the pick *after* this one — the same horizon wait-vs-take uses.
    next_pick = (
        session.my_following_pick() if session.is_my_pick() else session.my_next_pick()
    )
    availability = None
    if next_pick and next_pick > session.current_pick:
        simulator = DraftSimulator(pool, session.league)
        simulation = simulator.run(
            current_pick=session.current_pick,
            target_pick=next_pick,
            drafted=session.drafted_ids,
            roster_positions={
                slot: dict(r.positions) for slot, r in session.rosters().items()
            },
        )
        result = probability_available(pool, player_id, next_pick, simulation)
        availability = {
            "target_pick": result.target_pick,
            "probability": result.probability,
            "method": result.method,
            "detail": result.detail,
        }

    return PlayerDetail(
        score=score,
        replacement_rank=replacement_rank,
        replacement_points=(
            round(score.projected_points - score.vorp, 2)
            if score.projected_points is not None and score.vorp is not None else None
        ),
        injury_history=pool.injury.history(player.gsis_id) if player.gsis_id else [],
        usage_trend=signals.get("usage_trend"),
        bye_week=signals.get("bye_week"),
        availability=availability,
    )
