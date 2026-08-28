"""Draft session store, and the Sleeper bridge that feeds it.

Sessions live in SQLite so they survive a restart, with an in-process cache in
front so the hot path during a live draft is not a disk read.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app import db
from app.data import sleeper
from app.data.registry import PlayerRegistry, get_registry
from app.models.draft import DraftSession
from app.models.league import LeagueSettings

log = logging.getLogger(__name__)

_CACHE: dict[str, DraftSession] = {}


class DraftNotFound(KeyError):
    pass


class SlotUnresolved(ValueError):
    """Sleeper did not say which slot belongs to this user, so the caller must."""


# --- lifecycle ------------------------------------------------------------

def create_session(league: LeagueSettings, sleeper_draft_id: str | None = None,
                   league_id: str | None = None) -> DraftSession:
    session = DraftSession(
        session_id=uuid.uuid4().hex[:12],
        league=league,
        sleeper_draft_id=sleeper_draft_id,
    )
    _persist(session, league_id)
    return session


def get_session(session_id: str) -> DraftSession:
    if session_id in _CACHE:
        return _CACHE[session_id]
    payload = db.get_session(session_id)
    if payload is None:
        raise DraftNotFound(session_id)
    session = DraftSession.model_validate(payload)
    _CACHE[session_id] = session
    return session


def save_session(session: DraftSession, league_id: str | None = None) -> None:
    _persist(session, league_id)


def delete_session(session_id: str) -> bool:
    _CACHE.pop(session_id, None)
    return db.delete_session(session_id)


def list_sessions() -> list[dict[str, Any]]:
    return db.list_sessions()


def _persist(session: DraftSession, league_id: str | None = None) -> None:
    _CACHE[session.session_id] = session
    db.save_session(
        session.session_id,
        league_id,
        session.sleeper_draft_id,
        session.model_dump(mode="json"),
    )


# --- manual picks ---------------------------------------------------------

def record_pick(session: DraftSession, player_id: str,
                registry: PlayerRegistry | None = None) -> DraftSession:
    """Record a pick by canonical player id.

    Refuses unknown ids and duplicates — a draft board that lets you draft the
    same player twice is worse than useless.
    """
    registry = registry or get_registry()
    player = registry.get(player_id)
    if player is None:
        raise KeyError(f"{player_id} is not a current player")
    if player_id in session.drafted_ids:
        raise ValueError(f"{player.name} has already been drafted")

    session.add_pick(player_id, player.name, player.position, source="manual")
    _persist(session)
    return session


def undo_pick(session: DraftSession) -> DraftSession:
    if not session.picks:
        raise ValueError("no picks to undo")
    session.picks.pop()
    _persist(session)
    return session


def resolve_player(name: str, registry: PlayerRegistry | None = None,
                   position: str | None = None, team: str | None = None):
    registry = registry or get_registry()
    return registry.resolve(name, position, team)


# --- Sleeper sync ---------------------------------------------------------

def sync_from_sleeper(session: DraftSession,
                      registry: PlayerRegistry | None = None) -> dict[str, Any]:
    """Pull picks from Sleeper and replay any we have not seen.

    Sleeper is treated as the source of truth for the pick list: it is replayed
    from the start rather than appended to, so an out-of-order poll or a
    corrected pick converges instead of drifting.
    """
    if not session.sleeper_draft_id:
        raise ValueError("this session is not linked to a Sleeper draft")

    registry = registry or get_registry()
    remote = sleeper.get_draft_picks(session.sleeper_draft_id)

    replayed: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    session.picks.clear()

    for pick in remote:
        sleeper_id = pick.get("player_id")
        metadata = pick.get("metadata") or {}
        player = registry.by_sleeper_id(sleeper_id)
        if player is None:
            name = " ".join(
                filter(None, [metadata.get("first_name"), metadata.get("last_name")])
            )
            player = registry.resolve(
                name, metadata.get("position"), metadata.get("team")
            )
        if player is None:
            unmatched.append(
                {
                    "pick_no": pick.get("pick_no"),
                    "sleeper_player_id": sleeper_id,
                    "name": " ".join(
                        filter(None, [metadata.get("first_name"), metadata.get("last_name")])
                    ) or None,
                }
            )
            continue
        if player.player_id in session.drafted_ids:
            continue
        recorded = session.add_pick(
            player.player_id, player.name, player.position, source="sleeper"
        )
        replayed.append({"pick_no": recorded.overall, "player": player.name})

    _persist(session)

    if unmatched:
        log.warning("%d Sleeper picks did not match the registry", len(unmatched))

    return {
        "synced_picks": len(replayed),
        "total_remote_picks": len(remote),
        "unmatched": unmatched,
        "current_pick": session.current_pick,
        "on_the_clock_slot": session.league.slot_on_the_clock(session.current_pick),
        "is_my_pick": session.is_my_pick(),
    }


def league_from_sleeper(draft_id: str, user_id: str | None = None,
                        my_draft_slot: int | None = None) -> LeagueSettings:
    """Build league settings from a Sleeper draft, so the user types one id."""
    draft = sleeper.get_draft(draft_id)
    fields = sleeper.league_settings_from_draft(draft)
    if my_draft_slot:
        fields["my_draft_slot"] = my_draft_slot
    slot = None if my_draft_slot else sleeper.my_slot_from_draft(draft, user_id)
    if slot:
        fields["my_draft_slot"] = slot
    elif "my_draft_slot" not in fields:
        # Deliberately not defaulting. Guessing slot 1 for a drafter sitting at
        # 12 silently poisons replacement level, availability and every
        # recommendation downstream - far worse than making the caller ask.
        raise SlotUnresolved(
            "could not work out which draft slot is yours from this draft"
        )
    return LeagueSettings(**fields)
