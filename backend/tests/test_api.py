"""End-to-end tests over the HTTP layer.

Marked ``integration`` because they read live nflverse and Sleeper data. That
data is cached to disk, so only the first run is slow.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def drafting(client):
    """A session two picks in, with the user on the clock at pick 3."""
    league = client.post(
        "/league",
        json={"league": {"name": "Test", "scoring": "ppr", "teams": 12, "my_draft_slot": 3}},
    ).json()
    session_id = client.post(
        "/draft/sessions", json={"league_id": league["league_id"]}
    ).json()["session_id"]
    for name in ("Ja'Marr Chase", "Jahmyr Gibbs"):
        client.post("/draft/picks", params={"session_id": session_id},
                    json={"player_name": name})
    return session_id


def test_health_reports_the_registry_and_which_sources_are_configured(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["registry"]["ready"] and body["registry"]["players"] > 500
    assert set(body["sources"]) == {"fantasypros", "nflverse", "sleeper"}
    assert "configured" in body["validation"]


def test_a_missing_session_is_a_404(client):
    assert client.get("/players", params={"session_id": "nope"}).status_code == 404


def test_board_is_ranked_by_vorp_and_carries_its_reasoning(client, drafting):
    body = client.get("/players", params={"session_id": drafting, "limit": 20}).json()
    players = body["players"]
    assert len(players) == 20
    assert body["consensus_source"] in ("nflverse", "fantasypros")

    vorps = [p["vorp"] for p in players]
    assert vorps == sorted(vorps, reverse=True)

    for player in players:
        assert 0 <= player["confidence"] <= 100
        assert {c["name"] for c in player["components"]} == {
            "adp_value", "strength_of_schedule", "injury_risk",
            "opportunity_share", "consensus_uncertainty",
        }


def test_drafted_players_leave_the_board(client, drafting):
    names = {
        p["player"]["name"]
        for p in client.get(
            "/players", params={"session_id": drafting, "limit": 100}
        ).json()["players"]
    }
    assert "Ja'Marr Chase" not in names
    assert "Jahmyr Gibbs" not in names


def test_position_filter(client, drafting):
    body = client.get(
        "/players", params={"session_id": drafting, "position": "RB", "limit": 10}
    ).json()
    assert {p["player"]["position"] for p in body["players"]} == {"RB"}


def test_scoring_changes_reorder_the_board(client):
    """A different scoring preset must produce a different ranking."""
    boards = {}
    for scoring in ("ppr", "standard"):
        league = client.post(
            "/league",
            json={"league": {"scoring": scoring, "teams": 12, "my_draft_slot": 1}},
        ).json()
        session_id = client.post(
            "/draft/sessions", json={"league_id": league["league_id"]}
        ).json()["session_id"]
        boards[scoring] = [
            p["player"]["name"]
            for p in client.get(
                "/players", params={"session_id": session_id, "limit": 40}
            ).json()["players"]
        ]
    assert boards["ppr"] != boards["standard"]


def test_picks_can_be_recorded_by_name_and_undone(client, drafting):
    before = client.get("/draft/state", params={"session_id": drafting}).json()
    response = client.post(
        "/draft/picks", params={"session_id": drafting}, json={"player_name": "Puka Nacua"}
    )
    assert response.status_code == 200
    assert response.json()["current_pick"] == before["current_pick"] + 1

    undone = client.request(
        "DELETE", "/draft/picks/last", params={"session_id": drafting}
    )
    assert undone.json()["current_pick"] == before["current_pick"]


def test_a_duplicate_pick_is_rejected(client, drafting):
    response = client.post(
        "/draft/picks", params={"session_id": drafting}, json={"player_name": "Ja'Marr Chase"}
    )
    assert response.status_code == 409
    assert "already been drafted" in response.json()["detail"]


def test_a_retired_player_cannot_be_drafted_or_looked_up(client, drafting):
    response = client.post(
        "/draft/picks", params={"session_id": drafting}, json={"player_name": "Tom Brady"}
    )
    assert response.status_code == 404
    assert "not a current player" in response.json()["detail"]["message"]

    assert client.get(
        "/players/nfl-nobody", params={"session_id": drafting}
    ).status_code == 404


def test_wait_vs_take_returns_a_verdict_a_value_and_a_probability(client, drafting):
    body = client.get(
        "/advice/wait-vs-take",
        params={"session_id": drafting, "player_name": "Bijan Robinson",
                "validate_with_claude": False},
    ).json()

    recommendation = body["recommendation"]
    assert recommendation["verdict"] in ("TAKE", "WAIT", "EITHER")
    assert isinstance(recommendation["rating_value"], float)
    assert 0.0 <= recommendation["probability_available_next_pick"] <= 1.0
    assert recommendation["next_pick"] == 22
    assert len(recommendation["reasons"]) >= 3
    assert body["validation"]["status"] == "skipped"
    assert body["evidence"]["player"]["player"]["name"] == "Bijan Robinson"


def test_an_elite_player_far_from_your_next_pick_is_a_take(client, drafting):
    body = client.get(
        "/advice/wait-vs-take",
        params={"session_id": drafting, "player_name": "Puka Nacua",
                "validate_with_claude": False},
    ).json()["recommendation"]
    # Nineteen picks away, a top-five player will not last.
    assert body["probability_available_next_pick"] < 0.2
    assert body["verdict"] == "TAKE"
    assert body["rating_value"] > 0


def test_what_if_projects_the_next_rounds_without_mutating_the_draft(client, drafting):
    before = client.get("/draft/state", params={"session_id": drafting}).json()
    body = client.post(
        "/advice/what-if", params={"session_id": drafting},
        json={"player_name": "Bijan Robinson", "validate_with_claude": False},
    ).json()

    recommendation = body["recommendation"]
    assert recommendation["roster_after"] == {"RB": 1}
    assert recommendation["remaining_needs"]["WR"] == 4
    assert len(recommendation["outlook"]) == 2
    assert recommendation["outlook"][0]["pick"] == 22
    assert recommendation["summary"]

    after = client.get("/draft/state", params={"session_id": drafting}).json()
    assert after["picks"] == before["picks"], "a hypothetical must not change the draft"


def test_what_if_reflects_the_position_taken(client, drafting):
    """Taking a back and taking a receiver should leave different holes."""
    def needs(name):
        return client.post(
            "/advice/what-if", params={"session_id": drafting},
            json={"player_name": name, "validate_with_claude": False},
        ).json()["recommendation"]["remaining_needs"]

    assert needs("Bijan Robinson")["RB"] < needs("Puka Nacua")["RB"]
    assert needs("Puka Nacua")["WR"] < needs("Bijan Robinson")["WR"]


def test_board_advice_carries_the_envelope(client, drafting):
    body = client.get(
        "/advice/board",
        params={"session_id": drafting, "limit": 5, "validate_with_claude": False},
    ).json()
    assert set(body) == {"recommendation", "evidence", "validation"}
    assert body["recommendation"]["top_pick"]["name"]
    assert "confidence" in body["recommendation"]["top_pick"]["why"]
    assert body["evidence"]["your_remaining_needs"]["WR"] == 4


def test_validation_degrades_when_no_api_key_is_set(client, drafting):
    """Without a key the advice still comes back; only validation is absent."""
    body = client.get(
        "/advice/board",
        params={"session_id": drafting, "limit": 3, "validate_with_claude": True},
    ).json()
    assert body["recommendation"]["ranked"]
    assert body["validation"]["status"] == "unavailable"


def test_chat_reports_unavailable_without_a_key(client, drafting):
    body = client.post(
        "/chat", params={"session_id": drafting}, json={"question": "Who should I take?"}
    ).json()
    assert body["status"] == "unavailable"


def test_player_detail_exposes_the_full_breakdown(client, drafting):
    top = client.get(
        "/players", params={"session_id": drafting, "limit": 1}
    ).json()["players"][0]
    body = client.get(
        f"/players/{top['player']['player_id']}", params={"session_id": drafting}
    ).json()

    assert body["replacement_rank"] > 0
    assert body["replacement_points"] is not None
    assert body["availability"]["target_pick"] == 22
    assert body["availability"]["method"] == "monte_carlo"


def test_compare_orders_candidates_by_rating_value(client, drafting):
    ids = [
        p["player"]["player_id"]
        for p in client.get(
            "/players", params={"session_id": drafting, "limit": 3}
        ).json()["players"]
    ]
    body = client.get(
        "/advice/compare", params=[("session_id", drafting), *(("player_ids", i) for i in ids)]
    ).json()
    values = [c["rating_value"] for c in body["recommendation"]["ordered_by_rating_value"]]
    assert values == sorted(values, reverse=True)
