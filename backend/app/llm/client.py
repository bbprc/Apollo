"""Anthropic client wrapper.

Two rules shape this module:

* **The draft board never goes down because a model call failed.** Every entry
  point returns a result object with a status rather than raising, so callers
  can degrade to the deterministic answer.
* **The system prompt is cached.** A draft makes dozens of validation calls
  with an identical prefix, so it carries a ``cache_control`` breakpoint and
  everything volatile goes after it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterator, Type

from pydantic import BaseModel

from app.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class LLMResult:
    """Outcome of a model call, successful or not."""

    status: str                      # "ok" | "unavailable" | "error" | "invalid"
    parsed: Any = None
    text: str | None = None
    detail: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.detail:
            payload["detail"] = self.detail
        if self.usage:
            payload["usage"] = self.usage
        return payload


def is_enabled() -> bool:
    return get_settings().llm_enabled


_CLIENT = None


def get_client():
    """Lazily construct the SDK client so an unset key is not an import error."""
    global _CLIENT
    if _CLIENT is None:
        import anthropic

        settings = get_settings()
        _CLIENT = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.llm_timeout_seconds,
        )
    return _CLIENT


def reset_client() -> None:
    global _CLIENT
    _CLIENT = None


def _usage(response) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    return {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
    }


def _cached_system(system_prompt: str) -> list[dict[str, Any]]:
    """System block with a cache breakpoint at the end.

    Everything before this point is identical on every call within a league, so
    it is served from cache after the first request.
    """
    return [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _handle(exc: Exception) -> LLMResult:
    """Map SDK exceptions onto a status, most specific first."""
    import anthropic

    if isinstance(exc, anthropic.NotFoundError):
        return LLMResult(status="error", detail=f"model or endpoint not found: {exc}")
    if isinstance(exc, anthropic.AuthenticationError):
        return LLMResult(status="unavailable", detail="ANTHROPIC_API_KEY is invalid")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return LLMResult(status="unavailable", detail="API key lacks access to this model")
    if isinstance(exc, anthropic.RateLimitError):
        retry_after = exc.response.headers.get("retry-after", "60") if exc.response else "60"
        return LLMResult(status="error", detail=f"rate limited; retry after {retry_after}s")
    if isinstance(exc, anthropic.APIStatusError):
        return LLMResult(status="error", detail=f"API error {exc.status_code}: {exc.message}")
    if isinstance(exc, anthropic.APIConnectionError):
        return LLMResult(status="error", detail="could not reach the Anthropic API")
    log.exception("unexpected error calling Claude")
    return LLMResult(status="error", detail=f"{type(exc).__name__}: {exc}")


def parse(
    system_prompt: str,
    user_content: str,
    schema: Type[BaseModel],
    max_tokens: int | None = None,
) -> LLMResult:
    """Ask for a structured answer validated against ``schema``."""
    if not is_enabled():
        return LLMResult(status="unavailable", detail="ANTHROPIC_API_KEY is not set")

    settings = get_settings()
    try:
        response = get_client().messages.parse(
            model=settings.model,
            max_tokens=max_tokens or settings.llm_max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": settings.llm_effort},
            system=_cached_system(system_prompt),
            messages=[{"role": "user", "content": user_content}],
            output_format=schema,
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a status by _handle
        return _handle(exc)

    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        return LLMResult(
            status="error",
            detail=f"model declined ({getattr(details, 'category', 'unspecified')})",
            usage=_usage(response),
        )

    parsed = getattr(response, "parsed_output", None)
    if parsed is None:
        return LLMResult(
            status="invalid",
            detail="response did not validate against the schema",
            usage=_usage(response),
        )
    return LLMResult(status="ok", parsed=parsed, usage=_usage(response))


def complete(
    system_prompt: str,
    messages: list[dict[str, Any]],
    max_tokens: int | None = None,
) -> LLMResult:
    """Plain text answer for a multi-turn conversation."""
    if not is_enabled():
        return LLMResult(status="unavailable", detail="ANTHROPIC_API_KEY is not set")

    settings = get_settings()
    try:
        response = get_client().messages.create(
            model=settings.model,
            max_tokens=max_tokens or settings.llm_max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": settings.llm_effort},
            system=_cached_system(system_prompt),
            messages=messages,
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)

    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        return LLMResult(
            status="error",
            detail=f"model declined ({getattr(details, 'category', 'unspecified')})",
            usage=_usage(response),
        )

    text = "".join(block.text for block in response.content if block.type == "text")
    return LLMResult(status="ok", text=text, usage=_usage(response))


def stream(
    system_prompt: str,
    messages: list[dict[str, Any]],
    max_tokens: int | None = None,
) -> Iterator[str]:
    """Yield text deltas. Errors surface as a final message, never an exception."""
    if not is_enabled():
        yield "[chat unavailable: ANTHROPIC_API_KEY is not set]"
        return

    settings = get_settings()
    try:
        with get_client().messages.stream(
            model=settings.model,
            max_tokens=max_tokens or settings.llm_max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": settings.llm_effort},
            system=_cached_system(system_prompt),
            messages=messages,
        ) as streamed:
            for text in streamed.text_stream:
                yield text
    except Exception as exc:  # noqa: BLE001
        result = _handle(exc)
        yield f"\n\n[chat interrupted: {result.detail}]"
