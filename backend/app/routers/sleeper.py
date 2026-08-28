"""Sleeper account lookup, so setup can ask for a username.

The old flow asked for a Sleeper *user id* - an opaque 19-digit number nobody
knows - and silently defaulted the draft slot to 1 when it could not resolve
one. A drafter sitting at slot 12 then got a board computed for slot 1.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.data import sleeper

log = logging.getLogger(__name__)

router = APIRouter(prefix="/sleeper", tags=["sleeper"])


@router.get("/lookup", summary="Find a Sleeper account and its drafts by username")
def lookup(
    username: str = Query(..., min_length=1),
    season: int | None = Query(default=None),
) -> dict:
    season = season or get_settings().season
    user = sleeper.user_by_username(username)
    if user is None:
        raise HTTPException(status_code=404, detail=f"no Sleeper user '{username}'")

    user_id = str(user["user_id"])
    try:
        drafts = sleeper.drafts_for_user(user_id, season)
        leagues = {
            str(league.get("league_id")): league
            for league in sleeper.leagues_for_user(user_id, season)
        }
    except Exception as exc:  # noqa: BLE001 - surfaced, not fatal
        raise HTTPException(status_code=502, detail=f"Sleeper lookup failed: {exc}")

    rows = []
    for draft in drafts:
        settings = draft.get("settings") or {}
        metadata = draft.get("metadata") or {}
        league = leagues.get(str(draft.get("league_id"))) or {}
        order = draft.get("draft_order") or {}
        rows.append({
            "draft_id": str(draft.get("draft_id")),
            "name": metadata.get("name") or league.get("name") or "Untitled",
            "status": draft.get("status"),
            "type": draft.get("type"),
            "scoring": metadata.get("scoring_type"),
            "teams": settings.get("teams"),
            "rounds": settings.get("rounds"),
            # Pre-resolved so the client can show the slot rather than ask.
            "your_slot": int(order[user_id]) if order.get(user_id) else None,
        })

    return {
        "user": {
            "user_id": user_id,
            "username": user.get("username"),
            "display_name": user.get("display_name"),
        },
        "season": season,
        "drafts": rows,
        "note": (
            "Mock drafts are not returned by Sleeper here - paste the draft id "
            "for those."
        ),
    }


@router.get("/draft/{draft_id}", summary="Preview a draft id, including your slot")
def draft_preview(draft_id: str, user_id: str | None = Query(default=None)) -> dict:
    """Used for mock drafts, which never appear in the account listing."""
    try:
        draft = sleeper.get_draft(draft_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"Sleeper: {exc}")

    settings = draft.get("settings") or {}
    metadata = draft.get("metadata") or {}
    return {
        "draft_id": draft_id,
        "name": metadata.get("name") or "Untitled",
        "status": draft.get("status"),
        "scoring": metadata.get("scoring_type"),
        "teams": settings.get("teams"),
        "rounds": settings.get("rounds"),
        "your_slot": sleeper.my_slot_from_draft(draft, user_id),
    }
