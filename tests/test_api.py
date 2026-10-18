"""
API Tests for FLOODSHIFT against the real WorldService (HOT-derived bundle).
Person 3 owns these tests.

Run with: pytest tests/test_api.py -v
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app

START_UV = [0.92, 0.92]
EAST_CROSSING_UV = [0.50042078, 0.440123655]


@pytest.fixture
def client():
    """Create test client (a fresh lifespan loads a fresh world)."""
    with TestClient(app) as c:
        c.post("/reset")
        yield c


def start(client, action_id="test-start"):
    world = client.get("/world").json()
    return client.post("/action", json={
        "action_id": action_id, "type": "place_token", "source": "manual",
        "token_type": "disaster_start", "token_id": "disaster_start", "site_id": "start_pad",
        "board_uv": START_UV, "expected_world_version": world["world_version"]}).json()


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        data = client.get("/health").json()
        assert data["status"] == "ok"
        assert "world_version" in data

    def test_health_reports_manual_mode_not_mock(self, client):
        data = client.get("/health").json()
        assert data["vision_mode"] == "manual"
        assert data["perceptron_status"] == "not_connected"


class TestWorldEndpoint:
    def test_get_world_returns_real_snapshot(self, client):
        data = client.get("/world").json()
        assert data["schema_version"] == 2
        assert data["scenario_id"] == "nepal_rasuwa_hot_v1"
        assert data["phase"] == "ready"
        assert data["game"]["status"] == "not_started"
        assert {"tokens", "metrics", "edges", "token_inventory"} <= set(data)

    def test_world_has_inventory_for_every_core_token(self, client):
        inv = client.get("/world").json()["token_inventory"]
        for token in ("hospital", "shelter", "food_shelter", "bridge", "person", "disaster_start"):
            assert inv[token] >= 1


class TestActionEndpoint:
    def test_disaster_start_activates_phase(self, client):
        assert start(client)["accepted"] is True
        world = client.get("/world").json()
        assert world["phase"] == "disaster_active" and world["simulation_stage"] == 1

    def test_duplicate_action_rejected(self, client):
        assert start(client, "dup-1")["accepted"]
        result = start(client, "dup-1")
        assert result["accepted"] is False and result["rejection_reason"] == "duplicate"

    def test_stale_version_rejected(self, client):
        result = client.post("/action", json={
            "action_id": "test-stale", "type": "place_token", "source": "manual",
            "token_type": "disaster_start", "site_id": "start_pad", "board_uv": START_UV,
            "expected_world_version": 999}).json()
        assert result["accepted"] is False and result["rejection_reason"] == "stale_version"

    def test_place_token_before_start_rejected(self, client):
        world = client.get("/world").json()
        result = client.post("/action", json={
            "action_id": "test-early", "type": "place_token", "source": "manual",
            "token_type": "bridge", "site_id": "crossing_east", "board_uv": EAST_CROSSING_UV,
            "expected_world_version": world["world_version"]}).json()
        assert result["accepted"] is False and result["rejection_reason"] == "start_first"

    def test_bridge_unblocks_crossing(self, client):
        start(client)
        world = client.get("/world").json()
        edge = next(e for e in world["edges"] if e["id"] == "crossing_east_road")
        assert edge["blocked"] is True
        result = client.post("/action", json={
            "action_id": "test-bridge", "type": "place_token", "source": "physical_perceptron",
            "token_type": "bridge", "token_id": "bridge-1", "site_id": "crossing_east",
            "board_uv": EAST_CROSSING_UV, "expected_world_version": world["world_version"]}).json()
        assert result["accepted"] is True
        edge = next(e for e in client.get("/world").json()["edges"] if e["id"] == "crossing_east_road")
        assert edge["blocked"] is False


class TestSuggestEndpoint:
    def test_no_suggestion_before_any_need_exists(self, client):
        # Nothing is measured before the flood starts, so nothing can be suggested.
        assert client.post("/plan/suggest", json={}).json()["has_suggestion"] is False


class TestResetEndpoint:
    def test_reset_restores_initial_state(self, client):
        start(client)
        assert client.post("/reset").json()["reset"] is True
        world = client.get("/world").json()
        assert world["phase"] == "ready" and world["tokens"] == []
        assert all(not e["blocked"] for e in world["edges"])


class TestNarrateEndpoint:
    def test_narrate_responds_with_labelled_text(self, client, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        data = client.post("/narrate", json={"question": "Why is the village cut off?"}).json()
        assert data["answer"] and data["mode"] == "TEXT"


class TestWebSocket:
    def test_websocket_connects_and_receives_hello(self, client):
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["type"] == "server.hello"
            assert data["payload"]["status"] == "connected"

    def test_websocket_receives_initial_snapshot(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            data = ws.receive_json()
            assert data["type"] == "world.snapshot"
            assert data["payload"]["scenario_id"] == "nepal_rasuwa_hot_v1"
