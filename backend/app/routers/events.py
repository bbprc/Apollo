"""Server-sent events for a live draft.

Polling from the browser cannot be made reliable: Chrome throttles timers in
hidden tabs to roughly once a minute, and Apollo is *always* the hidden tab
while the user drafts in Sleeper. Pushing from the server sidesteps that —
network events are not timer-throttled, so a pick reaches the board in about
two seconds whether the tab is focused, backgrounded, or behind a window.

One poller serves every subscriber to a session, so extra tabs are free.
``POST /draft/sync`` is untouched and remains the manual fallback.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.data.registry import get_registry
from app.engine import draft_state
from app.models.draft import DraftSession
from app.routers.deps import session_dep

log = logging.getLogger(__name__)

router = APIRouter(prefix="/draft", tags=["draft"])

#: How often the server asks Sleeper for picks. Sleeper's documented ceiling is
#: far above this, and one poller is shared by every tab on the session.
POLL_SECONDS = 2.0
#: Comment frames keep proxies and the browser from closing an idle stream.
HEARTBEAT_SECONDS = 15.0
#: Bounded so a stalled reader cannot grow a queue without limit.
QUEUE_SIZE = 32


def _frame(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


class _DraftFeed:
    """A single Sleeper poller, fanned out to every listener on one session."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.subscribers: set[asyncio.Queue[str]] = set()
        self.task: asyncio.Task[None] | None = None
        self.last_pick: int | None = None

    # -- fan-out ----------------------------------------------------------

    def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self.subscribers.discard(queue)

    def _publish(self, event: str, payload: dict[str, Any]) -> None:
        frame = _frame(event, payload)
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                # A reader this far behind will be resynced by the next event;
                # dropping a frame beats stalling the poller for everyone.
                log.debug("dropping frame for a slow subscriber on %s", self.session_id)

    # -- the poll ---------------------------------------------------------

    def _sync_blocking(self) -> dict[str, Any]:
        """Runs on a worker thread: draft_state uses blocking httpx."""
        session = draft_state.get_session(self.session_id)
        return draft_state.sync_from_sleeper(session, get_registry())

    async def _run(self) -> None:
        failures = 0
        while True:
            try:
                result = await asyncio.to_thread(self._sync_blocking)
                failures = 0
                current = result.get("current_pick")
                if current != self.last_pick:
                    # First tick publishes too: a client joining a draft already
                    # in progress must not sit on a stale board.
                    self.last_pick = current
                    self._publish("picks", {
                        "current_pick": current,
                        "picks_made": result.get("synced_picks"),
                        "on_the_clock_slot": result.get("on_the_clock_slot"),
                        "is_my_pick": result.get("is_my_pick"),
                        "unmatched": len(result.get("unmatched") or []),
                    })
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a bad poll must not end the stream
                failures += 1
                if failures <= 3 or failures % 30 == 0:
                    log.warning("sleeper poll failed for %s: %s", self.session_id, exc)
                self._publish("sync_error", {"detail": str(exc), "consecutive": failures})
            await asyncio.sleep(POLL_SECONDS)

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = None


_FEEDS: dict[str, _DraftFeed] = {}
_LOCK = asyncio.Lock()


async def _acquire(session_id: str) -> _DraftFeed:
    async with _LOCK:
        feed = _FEEDS.get(session_id)
        if feed is None:
            feed = _FEEDS[session_id] = _DraftFeed(session_id)
        feed.start()
        return feed


async def _release(feed: _DraftFeed, queue: asyncio.Queue[str]) -> None:
    async with _LOCK:
        feed.unsubscribe(queue)
        if not feed.subscribers:
            feed.stop()
            _FEEDS.pop(feed.session_id, None)


@router.get("/events", summary="Live pick stream (SSE) for a Sleeper-linked draft")
async def events(request: Request, session: DraftSession = Depends(session_dep)):
    """Stream pick changes as they land.

    Sessions with no Sleeper link get a single ``idle`` frame rather than an
    error: a manual draft has nothing to poll, and the client should not treat
    that as a failure.
    """
    if not session.sleeper_draft_id:
        async def idle() -> AsyncIterator[str]:
            yield _frame("idle", {"detail": "session is not linked to a Sleeper draft"})

        return StreamingResponse(idle(), media_type="text/event-stream")

    feed = await _acquire(session.session_id)
    queue = feed.subscribe()

    async def stream() -> AsyncIterator[str]:
        try:
            yield _frame("open", {
                "session_id": session.session_id,
                "poll_seconds": POLL_SECONDS,
            })
            while True:
                if await request.is_disconnected():
                    break
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            await _release(feed, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Nginx and friends buffer streamed bodies by default, which would
            # reintroduce exactly the latency this endpoint exists to remove.
            "X-Accel-Buffering": "no",
        },
    )
