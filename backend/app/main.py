"""Apollo — fantasy football draft assistant backend.

A deterministic engine ranks players and answers wait-vs-take and what-if
questions; Claude audits those answers as a second layer. Every player named
anywhere comes from a registry of current-season NFL rosters.

Run with: ``uvicorn app.main:app --reload`` and open http://localhost:8000/docs
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import get_settings
from app.data.registry import get_registry
from app.llm import client as llm_client
from app.routers import advice, chat, draft, events, league, players, sleeper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("apollo")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    db.init_db()
    log.info(
        "starting Apollo for season %s (FantasyPros key: %s, Anthropic key: %s)",
        settings.season,
        "set" if settings.fantasypros_enabled else "absent",
        "set" if settings.llm_enabled else "absent",
    )
    # Build the registry up front: it is the guardrail every other module
    # depends on, and a cold build on the first request would stall a draft.
    try:
        registry = get_registry()
        log.info("player registry ready with %d current players", len(registry))
    except Exception:  # noqa: BLE001 - keep the app up so /health can explain
        log.exception("registry build failed; player endpoints will error")
    yield


app = FastAPI(
    title="Apollo Draft Assistant",
    description=__doc__,
    version="0.1.0",
    lifespan=lifespan,
)

# Wide open by design: a UI will be added later and served from elsewhere.
# Tighten `allow_origins` before this is exposed beyond localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(league.router)
app.include_router(draft.router)
app.include_router(events.router)
app.include_router(sleeper.router)
app.include_router(players.router)
app.include_router(advice.router)
app.include_router(chat.router)


@app.get("/health", tags=["meta"], summary="Service and data-source status")
def health() -> dict:
    settings = get_settings()
    try:
        registry = get_registry()
        registry_status = {"ready": True, "players": len(registry), "season": registry.season}
    except Exception as exc:  # noqa: BLE001
        registry_status = {"ready": False, "error": str(exc)}

    return {
        "status": "ok" if registry_status.get("ready") else "degraded",
        "season": settings.season,
        "registry": registry_status,
        "sources": {
            "fantasypros": {
                "configured": settings.fantasypros_enabled,
                "role": "primary consensus source when keyed",
            },
            "nflverse": {
                "configured": True,
                "role": "stats, injuries, schedules, and the FantasyPros mirror",
            },
            "sleeper": {"configured": True, "role": "draft sync and active players"},
        },
        "validation": {
            "configured": llm_client.is_enabled(),
            "model": settings.model if llm_client.is_enabled() else None,
            "note": (
                "Recommendations are computed deterministically; Claude audits "
                "them. Without a key every endpoint still works and validation "
                "reports 'unavailable'."
            ),
        },
    }


@app.get("/", tags=["meta"], include_in_schema=False)
def root() -> dict:
    return {"service": "apollo", "docs": "/docs", "health": "/health"}
