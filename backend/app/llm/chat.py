"""Grounded chat about players and the draft.

Retrieval is deliberately narrow: whichever current players the question names,
plus the top of the board and the user's roster for context. That keeps the
prompt small and, more importantly, means the model is never handed a player it
should not be talking about.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterator

from app.data.registry import PlayerRegistry
from app.llm import client as llm_client
from app.llm import prompts
from app.models.draft import DraftSession
from app.models.player import PlayerScore
from app.scoring.board import PlayerPool

log = logging.getLogger(__name__)

#: How many board players to include when the question names nobody specific.
DEFAULT_BOARD_CONTEXT = 12
#: Cap on total players in a packet, to keep the prompt small during a draft.
MAX_CONTEXT_PLAYERS = 30


def mentioned_players(question: str, registry: PlayerRegistry) -> list[str]:
    """Current players named in a question, as canonical ids.

    Matches multi-word names first so "Chase Brown" is not read as "Chase".
    """
    found: list[str] = []
    seen: set[str] = set()
    words = re.findall(r"[A-Za-z][A-Za-z'’.\-]*", question or "")

    for size in (3, 2, 1):
        for index in range(len(words) - size + 1):
            phrase = " ".join(words[index:index + size])
            if size == 1 and len(phrase) < 4:
                continue
            player = registry.resolve(phrase)
            if player and player.player_id not in seen:
                # A single-word match is only trusted if it is unambiguous.
                if size == 1 and len(registry.search(phrase, limit=3)) > 1:
                    continue
                seen.add(player.player_id)
                found.append(player.player_id)
    return found


def build_context(
    pool: PlayerPool,
    session: DraftSession,
    question: str,
    registry: PlayerRegistry | None = None,
) -> tuple[list[PlayerScore], dict[str, Any]]:
    """Assemble the players and draft state the answer may draw on."""
    registry = registry or pool.registry
    current_pick = session.current_pick
    drafted = session.drafted_ids

    board = pool.board(current_pick=current_pick, drafted=drafted)
    by_id = {score.player.player_id: score for score in board}

    named = [by_id[pid] for pid in mentioned_players(question, registry) if pid in by_id]

    # Anyone named who is already off the board still deserves an answer.
    drafted_named = [
        pid for pid in mentioned_players(question, registry)
        if pid in drafted and pid not in by_id
    ]

    scores = list(named)
    for score in board[:DEFAULT_BOARD_CONTEXT]:
        if len(scores) >= MAX_CONTEXT_PLAYERS:
            break
        if score.player.player_id not in {s.player.player_id for s in scores}:
            scores.append(score)

    roster = session.my_roster()
    context = {
        "current_pick": current_pick,
        "current_round": session.current_round,
        "on_the_clock": session.league.slot_on_the_clock(current_pick),
        "is_your_pick": session.is_my_pick(),
        "your_next_pick": session.my_next_pick(),
        "your_roster": dict(roster.positions),
        "your_players": [
            registry.get(pid).name for pid in roster.player_ids if registry.get(pid)
        ],
        "your_remaining_needs": {
            position: count
            for position, count in roster.needs(session.league).items() if count > 0
        },
        "players_already_drafted": len(drafted),
        "consensus_source": pool.consensus_source,
        "already_drafted_players_you_asked_about": [
            registry.get(pid).name for pid in drafted_named if registry.get(pid)
        ],
    }
    return scores, context


def ask(
    pool: PlayerPool,
    session: DraftSession,
    question: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Answer a question, verified against the registry before returning."""
    if not llm_client.is_enabled():
        return {
            "status": "unavailable",
            "detail": "ANTHROPIC_API_KEY is not set",
            "answer": None,
        }

    registry = pool.registry
    scores, context = build_context(pool, session, question, registry)
    packet = prompts.chat_packet(question, scores, context)
    system = prompts.chat_system(session.league)

    messages = [*(history or []), {"role": "user", "content": packet}]
    result = llm_client.complete(system, messages)
    if not result.ok:
        return {**result.to_dict(), "answer": None}

    answer = result.text or ""
    unknown = registry.unknown_names(answer)

    if unknown:
        log.warning("chat named unknown players %s; retrying once", unknown)
        correction = prompts.CORRECTION_NOTICE.format(names=", ".join(unknown))
        retry = llm_client.complete(
            system,
            [*messages, {"role": "assistant", "content": answer},
             {"role": "user", "content": correction}],
        )
        if retry.ok:
            answer = retry.text or answer
            result = retry
            unknown = registry.unknown_names(answer)

    payload = {
        "status": "ok",
        "answer": answer,
        "players_in_context": [s.player.name for s in scores],
        "usage": result.usage,
    }
    if unknown:
        payload.update(
            {
                "status": "filtered",
                "answer": (
                    "That answer referenced players outside the current-season "
                    "knowledge base, so it was withheld. Try naming the players "
                    "you want compared."
                ),
                "filtered_names": unknown,
            }
        )
    return payload


def ask_stream(
    pool: PlayerPool,
    session: DraftSession,
    question: str,
    history: list[dict[str, str]] | None = None,
) -> Iterator[str]:
    """Stream an answer.

    Streaming and the registry check pull against each other: the check needs
    the whole answer. Rather than buffer and defeat the point, deltas stream
    through and a warning is appended if anything failed the check — the UI can
    show that inline.
    """
    if not llm_client.is_enabled():
        yield "[chat unavailable: ANTHROPIC_API_KEY is not set]"
        return

    registry = pool.registry
    scores, context = build_context(pool, session, question, registry)
    packet = prompts.chat_packet(question, scores, context)
    system = prompts.chat_system(session.league)
    messages = [*(history or []), {"role": "user", "content": packet}]

    chunks: list[str] = []
    for delta in llm_client.stream(system, messages):
        chunks.append(delta)
        yield delta

    unknown = registry.unknown_names("".join(chunks))
    if unknown:
        yield (
            "\n\n[warning: this answer mentioned "
            + ", ".join(unknown)
            + ", who are not in the current-season knowledge base. Treat those "
            "references as unverified.]"
        )
