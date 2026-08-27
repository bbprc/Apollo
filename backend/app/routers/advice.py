"""The advice endpoints.

All three return the same envelope: the deterministic ``recommendation``, the
``evidence`` behind it, and Claude's ``validation`` kept separate so the user
can see where the two differ.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.data.registry import PlayerRegistry
from app.engine import wait_vs_take, what_if
from app.engine.simulator import DraftSimulator
from app.llm import validator
from app.models.draft import DraftSession
from app.models.responses import Envelope, WhatIfRequest
from app.routers.deps import pool_for, registry_dep, resolve_player_id, session_dep

router = APIRouter(prefix="/advice", tags=["advice"])


@router.get("/board", response_model=Envelope, summary="Top recommendations at the current pick")
def board(
    session: DraftSession = Depends(session_dep),
    limit: int = Query(default=10, ge=1, le=50),
    position: list[str] | None = Query(default=None),
    validate_with_claude: bool = Query(default=True),
) -> Envelope:
    pool = pool_for(session)
    scores = pool.board(
        current_pick=session.current_pick,
        drafted=session.drafted_ids,
        positions=position,
        limit=limit,
    )
    roster = session.my_roster()
    needs = {k: v for k, v in roster.needs(session.league).items() if v > 0}

    recommendation = {
        "current_pick": session.current_pick,
        "current_round": session.current_round,
        "is_my_pick": session.is_my_pick(),
        "top_pick": (
            {
                "player_id": scores[0].player.player_id,
                "name": scores[0].player.name,
                "position": scores[0].player.position,
                "vorp": scores[0].vorp,
                "confidence": scores[0].confidence,
                "why": scores[0].explain(),
            }
            if scores else None
        ),
        "ranked": [
            {
                "player_id": s.player.player_id,
                "name": s.player.name,
                "position": s.player.position,
                "team": s.player.team,
                "vorp": s.vorp,
                "confidence": s.confidence,
                "adp": s.adp,
                "projected_points": s.projected_points,
                "fills_a_need": s.player.position in needs,
            }
            for s in scores
        ],
    }

    evidence = {
        "your_roster": dict(roster.positions),
        "your_remaining_needs": needs,
        "consensus_source": pool.consensus_source,
        "replacement_ranks": pool.replacement_ranks,
        "players": [s.model_dump(mode="json") for s in scores],
    }

    validation = (
        validator.validate_board(
            session.league, scores, session.current_pick, dict(roster.positions), needs
        )
        if validate_with_claude else {"status": "skipped"}
    )
    return Envelope(recommendation=recommendation, evidence=evidence, validation=validation)


@router.get("/wait-vs-take", response_model=Envelope,
            summary="Take him now or wait, with the points it costs either way")
def wait_or_take(
    session: DraftSession = Depends(session_dep),
    player_id: str | None = Query(default=None),
    player_name: str | None = Query(default=None),
    validate_with_claude: bool = Query(default=True),
    registry: PlayerRegistry = Depends(registry_dep),
) -> Envelope:
    resolved = resolve_player_id(registry, player_id, player_name)
    pool = pool_for(session)

    if resolved in session.drafted_ids:
        raise HTTPException(
            status_code=409,
            detail=f"{registry.get(resolved).name} has already been drafted",
        )

    try:
        result = wait_vs_take.evaluate(pool, session, resolved)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    board = pool.board(current_pick=session.current_pick, drafted=session.drafted_ids)
    by_id = {s.player.player_id: s for s in board}
    score = by_id.get(resolved)
    if score is None:
        raise HTTPException(
            status_code=404,
            detail=f"{registry.get(resolved).name} has no consensus ranking, so he cannot be scored",
        )
    alternative_scores = [
        by_id[a["player_id"]] for a in result.alternatives if a["player_id"] in by_id
    ]

    validation = (
        validator.validate_wait_vs_take(
            session.league, result, score, alternative_scores, registry
        )
        if validate_with_claude else {"status": "skipped"}
    )

    return Envelope(
        recommendation=result.to_dict(),
        evidence={
            "player": score.model_dump(mode="json"),
            "alternatives": [s.model_dump(mode="json") for s in alternative_scores],
            "consensus_source": pool.consensus_source,
        },
        validation=validation,
    )


@router.post("/what-if", response_model=Envelope,
             summary="Take this player — how does the next round look?")
def what_if_pick(
    payload: WhatIfRequest,
    session: DraftSession = Depends(session_dep),
    registry: PlayerRegistry = Depends(registry_dep),
) -> Envelope:
    resolved = resolve_player_id(registry, payload.player_id, payload.player_name)
    pool = pool_for(session)
    try:
        result = what_if.simulate_pick(pool, session, resolved, horizon=payload.horizon)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    board = pool.board(current_pick=session.current_pick, drafted=session.drafted_ids)
    score = next((s for s in board if s.player.player_id == resolved), None)

    validation = {"status": "skipped"}
    if payload.validate_with_claude and score is not None:
        roster = session.my_roster()
        validation = validator.validate_board(
            session.league,
            [score],
            session.current_pick,
            dict(roster.positions),
            result.remaining_needs,
        )

    return Envelope(
        recommendation=result.to_dict(),
        evidence={
            "player": score.model_dump(mode="json") if score else None,
            "consensus_source": pool.consensus_source,
        },
        validation=validation,
    )


@router.get("/compare", response_model=Envelope, summary="Compare candidates side by side")
def compare(
    session: DraftSession = Depends(session_dep),
    player_ids: list[str] = Query(..., description="Repeat the parameter per player"),
    horizon: int = Query(default=2, ge=1, le=4),
    registry: PlayerRegistry = Depends(registry_dep),
) -> Envelope:
    for player_id in player_ids:
        if registry.get(player_id) is None:
            raise HTTPException(status_code=404, detail=f"{player_id} is not a current player")

    pool = pool_for(session)
    simulator = DraftSimulator(pool, session.league)
    results = []
    for player_id in player_ids:
        try:
            outcome = what_if.simulate_pick(
                pool, session, player_id, horizon=horizon, simulator=simulator
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        decision = wait_vs_take.evaluate(pool, session, player_id, simulator=simulator)
        results.append({"what_if": outcome.to_dict(), "wait_vs_take": decision.to_dict()})

    results.sort(key=lambda r: r["wait_vs_take"]["rating_value"], reverse=True)
    return Envelope(
        recommendation={
            "current_pick": session.current_pick,
            "ordered_by_rating_value": [
                {
                    "player_name": r["wait_vs_take"]["player_name"],
                    "position": r["wait_vs_take"]["position"],
                    "verdict": r["wait_vs_take"]["verdict"],
                    "rating_value": r["wait_vs_take"]["rating_value"],
                }
                for r in results
            ],
        },
        evidence={"candidates": results},
        validation={"status": "skipped"},
    )
