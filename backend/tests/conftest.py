"""Shared fixtures.

Tests are split in two: pure unit tests that touch no network, and integration
tests marked ``@pytest.mark.integration`` that read live nflverse and Sleeper
data (cached to disk after the first run).
"""

from __future__ import annotations

import pytest

from app.models.league import LeagueSettings
from app.models.player import Player


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: exercises live upstream data (cached after first run)"
    )


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    """Give every test its own database and pool cache."""
    from app.config import get_settings
    from app.scoring.board import clear_pools

    monkeypatch.setenv("APOLLO_DB_PATH", str(tmp_path / "test.db"))
    get_settings.cache_clear()
    clear_pools()
    yield
    get_settings.cache_clear()
    clear_pools()


@pytest.fixture
def league() -> LeagueSettings:
    return LeagueSettings(name="Test", scoring="ppr", teams=12, my_draft_slot=3)


@pytest.fixture
def fake_players() -> list[Player]:
    """A small synthetic roster, so registry tests need no network."""
    return [
        Player(player_id="p1", name="Ja'Marr Chase", position="WR", team="CIN",
               gsis_id="g1", sleeper_id="s1", fantasypros_id="1", age=26.5),
        Player(player_id="p2", name="Bijan Robinson", position="RB", team="ATL",
               gsis_id="g2", sleeper_id="s2", fantasypros_id="2", age=24.6),
        Player(player_id="p3", name="Marvin Harrison Jr.", position="WR", team="ARI",
               gsis_id="g3", sleeper_id="s3", fantasypros_id="3", age=24.0),
        Player(player_id="p4", name="Patrick Mahomes", position="QB", team="KC",
               gsis_id="g4", sleeper_id="s4", fantasypros_id="4", age=31.0),
        Player(player_id="dst:KC", name="KC Defense", position="DST", team="KC"),
    ]


@pytest.fixture
def fake_registry(fake_players):
    from app.data.registry import PlayerRegistry

    return PlayerRegistry(fake_players, season=2026)
