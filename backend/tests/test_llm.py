"""The Claude layer: structured validation, caching shape, and the registry filter.

No network. The SDK call is replaced so the surrounding contract can be tested:
that failures degrade instead of raising, that the system prompt is stable
enough to cache, and that a response naming an unknown player never reaches the
caller.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.llm import chat as chat_engine
from app.llm import client as llm_client
from app.llm import prompts, validator
from app.models.league import LeagueSettings


class _FakeMessages:
    """Stands in for ``client.messages``, recording what it was called with."""

    def __init__(self, parsed=None, text=None, stop_reason="end_turn", error=None):
        self.parsed = parsed
        self.text = text
        self.stop_reason = stop_reason
        self.error = error
        self.calls: list[dict] = []

    def _respond(self, kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            parsed_output=self.parsed,
            stop_reason=self.stop_reason,
            stop_details=SimpleNamespace(category="cyber", explanation="no"),
            content=[SimpleNamespace(type="text", text=self.text or "")],
            usage=SimpleNamespace(
                input_tokens=100, output_tokens=20,
                cache_read_input_tokens=90, cache_creation_input_tokens=0,
            ),
        )

    def parse(self, **kwargs):
        return self._respond(kwargs)

    def create(self, **kwargs):
        return self._respond(kwargs)


@pytest.fixture
def patched_client(monkeypatch):
    """Install a fake SDK client and pretend a key is configured."""
    def _install(**kwargs):
        fake = _FakeMessages(**kwargs)
        monkeypatch.setattr(llm_client, "get_client", lambda: SimpleNamespace(messages=fake))
        monkeypatch.setattr(llm_client, "is_enabled", lambda: True)
        return fake
    return _install


# --- degradation ----------------------------------------------------------

def test_without_a_key_everything_reports_unavailable_and_never_raises(league):
    assert not llm_client.is_enabled()
    result = llm_client.parse("system", "user", validator.Verdict)
    assert result.status == "unavailable" and not result.ok

    verdict = validator.validate_board(league, [], 1, {}, {})
    assert verdict["status"] == "unavailable"


def test_api_errors_become_a_status_not_an_exception(patched_client, league):
    import anthropic

    patched_client(error=anthropic.APIConnectionError(request=None))
    result = llm_client.parse("system", "user", validator.Verdict)
    assert result.status == "error"
    assert "could not reach" in result.detail


def test_a_refusal_is_reported_rather_than_parsed(patched_client):
    patched_client(parsed=None, stop_reason="refusal")
    result = llm_client.parse("system", "user", validator.Verdict)
    assert result.status == "error" and "declined" in result.detail


# --- request shape --------------------------------------------------------

def test_the_system_prompt_carries_a_cache_breakpoint(patched_client):
    fake = patched_client(parsed=validator.Verdict(agrees=True, reasoning="fine"))
    llm_client.parse("a stable system prompt", "volatile user content", validator.Verdict)

    system = fake.calls[0]["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert system[0]["text"] == "a stable system prompt"
    # Volatile content must sit after the breakpoint, in the message.
    assert fake.calls[0]["messages"][0]["content"] == "volatile user content"


def test_requests_use_adaptive_thinking_and_configured_effort(patched_client):
    fake = patched_client(parsed=validator.Verdict(agrees=True, reasoning="fine"))
    llm_client.parse("system", "user", validator.Verdict)
    call = fake.calls[0]
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"]["effort"] == "high"
    assert call["model"] == "claude-opus-5"
    assert call["output_format"] is validator.Verdict


def test_the_system_prompt_is_byte_stable_so_it_can_cache(league):
    """Anything volatile in the prefix would silently destroy the cache hit."""
    first = prompts.validator_system(league)
    second = prompts.validator_system(league)
    assert first == second

    other = prompts.validator_system(
        LeagueSettings(scoring="half_ppr", teams=10, my_draft_slot=1)
    )
    assert other != first          # league rules do belong in the prefix


def test_usage_reports_cache_reads(patched_client):
    patched_client(parsed=validator.Verdict(agrees=True, reasoning="fine"))
    result = llm_client.parse("system", "user", validator.Verdict)
    assert result.usage["cache_read_input_tokens"] == 90


# --- the registry filter --------------------------------------------------

def test_a_clean_verdict_passes_through(patched_client, league, fake_registry):
    patched_client(
        parsed=validator.Verdict(
            agrees=True,
            concerns=["Bijan Robinson carries a heavy workload."],
            reasoning="Ja'Marr Chase is the stronger pick here.",
        )
    )
    result = validator.validate(league, "packet", fake_registry)
    assert result["status"] == "ok"
    assert result["agrees"] is True


def test_a_verdict_naming_an_unknown_player_is_retried_then_filtered(
    patched_client, league, fake_registry
):
    """Both attempts stray outside the registry, so the commentary is withheld."""
    fake = patched_client(
        parsed=validator.Verdict(
            agrees=False,
            concerns=["Tom Brady is the better value."],
            reasoning="Consider Tom Brady instead.",
        )
    )
    result = validator.validate(league, "packet", fake_registry)

    assert len(fake.calls) == 2, "an out-of-registry answer should be retried once"
    assert "not in the evidence packet" in fake.calls[1]["messages"][0]["content"]
    assert result["status"] == "filtered"
    assert result["filtered_names"] == ["Tom Brady"]
    assert result["concerns"] == []
    assert "outside the current-season knowledge base" in result["reasoning"]


def test_chat_extracts_only_current_players_from_a_question(fake_registry):
    ids = chat_engine.mentioned_players(
        "Should I take Bijan Robinson or Ja'Marr Chase over Tom Brady?", fake_registry
    )
    names = {fake_registry.get(i).name for i in ids}
    assert names == {"Bijan Robinson", "Ja'Marr Chase"}


def test_chat_prefers_the_longer_name_match(fake_registry):
    """'Marvin Harrison Jr.' must not be shortened to a different player."""
    ids = chat_engine.mentioned_players("What about Marvin Harrison Jr.?", fake_registry)
    assert [fake_registry.get(i).name for i in ids] == ["Marvin Harrison Jr."]


# --- prompt content -------------------------------------------------------

def test_the_methodology_states_the_knowledge_base_rule():
    assert "Reason ONLY about players named in the evidence packet" in prompts.METHODOLOGY
    assert "never mention a retired or inactive player" in prompts.METHODOLOGY


def test_league_rules_reach_the_prompt(league):
    system = prompts.validator_system(league)
    assert "Scoring: ppr" in system
    assert "Teams: 12" in system
    assert "slot 3" in system
