"""The advice endpoints.

All three return the same envelope: the deterministic ``recommendation``, the
``evidence`` behind it, and Claude's ``validation`` kept separate so the user
can see where the two differ.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.data.registry import PlayerRegistry
from app.engine import wait_vs_take, what_if
from app.engine.simulator import DraftSimulator
from app.llm import validator
from app.models.draft import DraftSession
from app.models.responses import Envelope, WhatIfRequest
from app.scoring import draft_strategy
from app.routers.deps import pool_for, registry_dep, resolve_player_id, session_dep

router = APIRouter(prefix="/advice", tags=["advice"])

#: Below this much expected gain, ranking by gain stops discriminating and the
#: board switches to best-available-that-fits.
ENDGAME_GAIN_THRESHOLD = 1.0


def _startability(
    position: str, league, roster_positions: dict[str, int]
) -> float:
    """How much a player at this position can actually add to the lineup.

    VONA on its own is pure positional scarcity: it says "quarterback gets
    worse by your next pick" and happily recommends a second quarterback to
    someone who already has one and can only start one. Scarcity at a position
    you cannot start is not value, so it is discounted here rather than
    hidden — a backup still has a price, just not a starter's price.
    """
    required = league.starters_at(position)
    have = roster_positions.get(position, 0)
    if have < required:
        return 1.0

    eligible = list(league.flex_eligible)
    if league.superflex and "QB" not in eligible:
        eligible.append("QB")
    flex_open = league.flex_slots() - sum(
        max(0, roster_positions.get(p, 0) - league.starters_at(p)) for p in eligible
    )
    if position in eligible and flex_open > 0:
        return 1.0

    # Single-slot positions: a second one rides the bench all season.
    if position in ("QB", "K", "DST"):
        return 0.15
    # Depth at a position you start several of still has real value.
    return 0.5


#: How deep to look for the alternative angles. Beyond this a "best value" pick
#: stops being a pick you would actually make at this slot.
CONTENTION = 25


#: An axis will not headline a player the timing rules are actively holding
#: back. Being two rounds early is a stretch; four is a different strategy.
AXIS_TIMING_FLOOR = 0.5


def _options(scores, entry, startability, timing) -> list[dict[str, Any]]:
    """Two or three genuinely different ways to use this pick.

    A single recommendation reads as an instruction, and a drafter wants a
    choice with the trade-off named. These are the three axes a human actually
    weighs - is he cheap, is he safe, is he going to win me the week - and they
    are drawn only from players you can start, so none of them is advice you
    cannot take.
    """
    field = [
        s for s in scores[:CONTENTION]
        if startability(s.player.position) >= 1.0 and timing(s) >= AXIS_TIMING_FLOOR
    ]
    if not field:
        return []

    picks: list[tuple[str, str, Any]] = []
    claimed: set[str] = set()

    def unclaimed(rows):
        """Prefer someone no other axis has taken, but never return nothing."""
        fresh = [r for r in rows if r.player.player_id not in claimed]
        return fresh or rows

    # Cheapest relative to what his usage has actually produced.
    #
    # Value is about price, not about lineup slot, so this looks wider than the
    # other two axes: a receiver who would start on the bench but is badly
    # underpriced is a real option, while a backup kicker never is. Anything
    # scored below 0.5 is a pure backup at a one-slot position.
    priced = [
        s for s in scores[:CONTENTION]
        if s.edge_z is not None
        and startability(s.player.position) >= 0.5
        and timing(s) >= AXIS_TIMING_FLOOR
    ]
    if priced:
        best = max(unclaimed(priced), key=lambda s: s.edge_z)
        if best.edge_z > 0.5:
            claimed.add(best.player.player_id)
            picks.append((
                "value",
                f"The market has him {best.player.position}{best.positional_rank}, "
                f"but last season's usage produced "
                f"{best.player.position}{best.usage_rank} value "
                f"({best.edge_ppg:+.1f} pts/game).",
                best,
            ))

    # Fewest ways to go wrong.
    def safety(s) -> float:
        return s.confidence - 40.0 * (s.injury_risk or 0.0)

    safest = max(unclaimed(field), key=safety)
    claimed.add(safest.player.player_id)
    picks.append((
        "safe",
        f"Confidence {safest.confidence:.0f}"
        + (
            f", and he has barely missed a game."
            if (safest.injury_risk or 1) <= 0.05
            else f", with the steadiest profile of anyone here."
        ),
        safest,
    ))

    # Most production per game *above what the position gives you anyway*.
    #
    # Ranking on raw points per game put a quarterback here every time: they
    # outscore everyone, and QB12 also outscores everyone, so the raw number
    # says nothing about what the pick buys you.
    producing = [s for s in field if s.expected_above_replacement is not None]
    if producing:
        top = max(unclaimed(producing), key=lambda s: s.expected_above_replacement)
        claimed.add(top.player.player_id)
        picks.append((
            "upside",
            f"{top.expected_above_replacement:+.1f} expected points a game above "
            f"a replacement {top.player.position} — the biggest edge on the board "
            f"({top.expected_ppg:.1f} a game outright).",
            top,
        ))

    merged: dict[str, dict[str, Any]] = {}
    for axis, reason, score in picks:
        key = score.player.player_id
        if key in merged:
            # The same player winning two axes is honest, but it costs the user
            # a choice. Only collapse them when there is genuinely no one else.
            merged[key]["axes"].append(axis)
            continue
        row = entry(score)
        row.update({"axes": [axis], "reason": reason})
        merged[key] = row
    return list(merged.values())


#: Below this, "take him second" is not advice, it is a way to lose him.
PAIR_SURVIVAL = 0.6


def _pair(session: DraftSession, scores, simulation, startability) -> dict[str, Any] | None:
    """On the wheel, the question is which two - and in which order.

    Only meaningful when the very next pick is also yours. At slot 12 that is
    true at pick 12 (you also hold 13) and false at pick 13 (your next is 36) -
    getting this wrong produced advice to "take Chase Brown first, you'll get
    both" about a player with a 0% chance of surviving.
    """
    if simulation is None:
        return None
    mine = set(session.league.my_picks())
    if session.current_pick + 1 not in mine:
        return None

    field = [s for s in scores[:CONTENTION] if startability(s.player.position) >= 1.0]
    if len(field) < 2:
        return None

    first, second = field[0], field[1]
    survives = simulation.survival.get(second.player.player_id)
    if survives is None:
        return None

    if survives >= PAIR_SURVIVAL:
        note = (
            f"{second.player.name} lasts one more pick {survives:.0%} of the time, "
            f"so taking {first.player.name} now is likely to get you both."
        )
    else:
        note = (
            f"You are unlikely to get both: {second.player.name} only lasts one "
            f"more pick {survives:.0%} of the time. Take whichever of them you "
            f"want more."
        )
    return {
        "now": {"player_id": first.player.player_id, "name": first.player.name,
                "position": first.player.position},
        "then": {"player_id": second.player.player_id, "name": second.player.name,
                 "position": second.player.position,
                 "probability_available": round(survives, 3)},
        "both_likely": survives >= PAIR_SURVIVAL,
        "note": note,
    }


def _next_turn_after_run(session: DraftSession) -> int | None:
    """The next pick that is genuinely a *later* turn.

    On the wheel this is the whole point. At slot 12 the picks are 12, 13, 36,
    37 - so standing on 12, the pick after is 13, one slot later, where
    everything is still on the board. Measuring against 13 makes every
    candidate look equally urgent and collapses the ranking. What a drafter
    actually weighs is "these two picks now, or wait until 36", so consecutive
    picks are treated as one turn and the horizon jumps past them.
    """
    upcoming = [p for p in session.league.my_picks() if p >= session.current_pick]
    if not upcoming:
        return None
    if not session.is_my_pick():
        return upcoming[0]

    end = upcoming[0]
    index = 1
    while index < len(upcoming) and upcoming[index] == end + 1:
        end = upcoming[index]
        index += 1
    return upcoming[index] if index < len(upcoming) else None


def _expected_vorp_at_next_pick(
    pool, session: DraftSession
) -> tuple[dict[str, float], int | None, Any]:
    """Expected best VORP per position by the time we pick again.

    One simulation serves the whole board. The horizon matches the one
    ``wait_vs_take`` uses, which matters on the turn: at slot 12 holding picks
    12 and 13, the question is what survives to 36, not to 13.
    """
    horizon = _next_turn_after_run(session)
    if horizon is None or horizon <= session.current_pick:
        return {}, horizon, None

    simulator = DraftSimulator(pool, session.league)
    simulation = simulator.run(
        current_pick=session.current_pick,
        target_pick=horizon,
        drafted=session.drafted_ids,
        roster_positions={
            slot: dict(r.positions) for slot, r in session.rosters().items()
        },
    )
    return dict(simulation.expected_vorp_by_position), horizon, simulation


@router.get("/board", response_model=Envelope, summary="Top recommendations at the current pick")
def board(
    session: DraftSession = Depends(session_dep),
    # Deep enough to serve the whole available list, not just a top-N panel:
    # the UI renders one list from this response so the recommendation and the
    # pool cannot drift apart.
    limit: int = Query(default=10, ge=1, le=500),
    position: list[str] | None = Query(default=None),
    validate_with_claude: bool = Query(default=True),
    depth: str = Query(default="deep", pattern="^(quick|deep)$"),
    strategy: str = Query(default=draft_strategy.DEFAULT_PROFILE),
) -> Envelope:
    pool = pool_for(session)
    # Score a deeper slice than we return: the ranking below re-sorts by VONA,
    # and a player outside the top `limit` by VORP can be inside it by VONA.
    scores = pool.board(
        current_pick=session.current_pick,
        drafted=session.drafted_ids,
        positions=position,
        limit=max(limit * 4, 40),
    )
    roster = session.my_roster()
    needs = {k: v for k, v in roster.needs(session.league).items() if v > 0}

    expected_next, horizon, simulation = _expected_vorp_at_next_pick(pool, session)

    roster_positions = dict(roster.positions)

    def timing(score) -> float:
        return draft_strategy.timing_multiplier(
            score.player.position,
            session.current_round,
            score.positional_rank,
            session.league,
            strategy,
            roster_positions,
        )

    def vona(score) -> float:
        """What this pick actually adds to your starting lineup.

        VORP asks "how much better than replacement"; VONA asks "how much do I
        gain by spending *this* pick here rather than at my next turn". Two
        corrections keep that honest:

        Value below replacement is clamped to zero on both sides. Without it a
        replacement-level receiver scores well purely because the receivers
        left at your next pick are worse still - the position degrading does
        not make a player who contributes nothing worth taking.

        The result is then scaled by whether you can start him at all, so a
        second quarterback stops outranking a running back you actually need.
        """
        base = max(0.0, score.vorp if score.vorp is not None else 0.0)
        later = max(0.0, expected_next.get(score.player.position, 0.0))
        gain = base - later
        startable = _startability(
            score.player.position, session.league, roster_positions
        )
        return round(gain * startable * timing(score), 2)

    scores.sort(key=lambda s: (vona(s), s.vorp or 0.0), reverse=True)

    # Late in a draft the gain ranking stops discriminating: every tight end
    # left is below replacement, so each one scores zero, while a backup kicker
    # with a positive number floats to the top. But an empty starting slot
    # scores nothing all season, so filling it beats any bench player. Once you
    # have only as many picks left as you have holes, every pick has to fill
    # one, and the question becomes "best player who fits" rather than
    # "biggest gain".
    picks_left = len([p for p in session.league.my_picks() if p >= session.current_pick])
    holes = sum(
        max(0, session.league.starters_at(position) - roster_positions.get(position, 0))
        for position in ("QB", "RB", "WR", "TE", "K", "DST")
    )
    best_gain = vona(scores[0]) if scores else 0.0
    mode = (
        "best_available"
        if (holes > 0 and picks_left <= holes) or best_gain < ENDGAME_GAIN_THRESHOLD
        else "gain"
    )
    if mode == "best_available":
        scores.sort(
            key=lambda s: (
                _startability(s.player.position, session.league, roster_positions),
                s.vorp or -1e9,
            ),
            reverse=True,
        )

    scores = scores[:limit]

    def entry(s) -> dict:
        return {
            "player_id": s.player.player_id,
            "name": s.player.name,
            "position": s.player.position,
            "team": s.player.team,
            "vorp": s.vorp,
            "vona": vona(s),
            "confidence": s.confidence,
            "adp": s.adp,
            # adp - current_pick. NEGATIVE means he has fallen past his ADP
            # and is a value here; POSITIVE means taking him now is a reach.
            "adp_delta": (
                round(s.adp - session.current_pick, 1) if s.adp is not None else None
            ),
            "tier": s.tier,
            "projected_points": s.projected_points,
            "fills_a_need": s.player.position in needs,
            # < 1.0 means he cannot crack your starting lineup as it stands.
            "startability": _startability(
                s.player.position, session.league, roster_positions
            ),
            # < 1.0 means the position is being considered earlier than the
            # draft community would; the UI explains rather than hides it.
            "timing": timing(s),
            "off_window": timing(s) < 1.0,
        }

    recommendation = {
        "current_pick": session.current_pick,
        "current_round": session.current_round,
        "is_my_pick": session.is_my_pick(),
        "ranked_by": "vona" if mode == "gain" else "startable_value",
        "mode": mode,
        "open_starting_slots": holes,
        "your_picks_left": picks_left,
        "horizon_pick": horizon,
        "strategy": strategy,
        "strategy_notes": [
            note for note in (
                draft_strategy.note_for(
                    position, session.current_round, session.league, strategy,
                    dict(roster.positions),
                )
                for position in ("QB", "TE", "DST", "K")
            ) if note
        ],
        "options": _options(
            scores,
            entry,
            lambda position: _startability(position, session.league, roster_positions),
            timing,
        ),
        "pair": (
            _pair(
                session,
                scores,
                simulation,
                lambda position: _startability(
                    position, session.league, roster_positions
                ),
            )
            if session.is_my_pick() else None
        ),
        "top_pick": (
            {
                "player_id": scores[0].player.player_id,
                "name": scores[0].player.name,
                "position": scores[0].player.position,
                "vorp": scores[0].vorp,
                "vona": vona(scores[0]),
                "confidence": scores[0].confidence,
                "why": scores[0].explain(),
            }
            if scores else None
        ),
        "ranked": [entry(s) for s in scores],
    }

    evidence = {
        "your_roster": dict(roster.positions),
        "your_remaining_needs": needs,
        "consensus_source": pool.consensus_source,
        "replacement_ranks": pool.replacement_ranks,
        "expected_vorp_at_next_pick": expected_next,
        "players": [s.model_dump(mode="json") for s in scores],
    }

    validation = (
        validator.validate_board(
            session.league, scores, session.current_pick,
            dict(roster.positions), needs, depth=depth,
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
    depth: str = Query(default="deep", pattern="^(quick|deep)$"),
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
            session.league, result, score, alternative_scores, registry, depth=depth,
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
