"""Chat about players and the current draft, grounded in the registry."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.llm import chat as chat_engine
from app.models.draft import DraftSession
from app.models.responses import ChatRequest, ChatResponse
from app.routers.deps import pool_for, session_dep

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", summary="Ask a question about your draft")
def ask(payload: ChatRequest, session: DraftSession = Depends(session_dep)):
    pool = pool_for(session)

    if payload.stream:
        return StreamingResponse(
            chat_engine.ask_stream(pool, session, payload.question, payload.history),
            media_type="text/plain; charset=utf-8",
        )

    result = chat_engine.ask(pool, session, payload.question, payload.history)
    return ChatResponse(**{k: v for k, v in result.items() if k in ChatResponse.model_fields})
