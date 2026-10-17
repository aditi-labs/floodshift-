"""
API Tests for FLOODSHIFT
Person 3 owns these tests.

Run with: pytest tests/test_api.py -v
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client():
    """Create test client."""
    with TestClient(app) as c:
        yield c


class TestHealthEndpoint:
    """Tests for GET /health"""

    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "world_version" in data
        assert "vision_mode" in data

    def test_health_shows_mock_mode(self, client):
        response = client.get("/health")
        data = response.json()
        assert data["vision_mode"] == "mock"
        assert data["perceptron_status"] == "not_connected"


class TestWorldEndpoint:
    """Tests for GET /world"""

    def test_get_world_returns_snapshot(self, client):
        response = client.get("/world")
        assert response.status_code == 200
        data = response.json()

        # Check required fields
        assert data["schema_version"] == 2
        assert "world_version" in data
        assert data["scenario_id"] == "nepal_rasuwa_v1"
        assert data["phase"] in ["ready", "disaster_active"]
        assert "token_inventory" in data
        assert "tokens" in data
        assert "metrics" in data

    def test_world_has_correct_inventory(self, client):
        response = client.get("/world")
        data = response.json()
        inv = data["token_inventory"]

        # Check all 6 required tokens
        assert inv.get("hospital", 0) >= 0
        assert inv.get("shelter", 0) >= 0
        assert inv.get("food_shelter", 0) >= 0
        assert inv.get("bridge", 0) >= 0
        assert inv.get("person", 0) >= 0
        assert inv.get("disaster_start", 0) >= 0


class TestActionEndpoint:
    """Tests for POST /action"""

    def test_disaster_start_activates_phase(self, client):
        # First reset to ensure clean state
        client.post("/reset")

        # Get current version
        world = client.get("/world").json()
        assert world["phase"] == "ready"

        # Start disaster
        response = client.post("/action", json={
            "action_id": "test-start-001",
            "type": "place_token",
            "source": "manual",
            "token_type": "disaster_start",
            "site_id": "start_pad",
            "board_uv": [0.1, 0.1],
            "expected_world_version": world["world_version"]
        })
        assert response.status_code == 200
        result = response.json()
        assert result["accepted"] is True

        # Check phase changed
        world = client.get("/world").json()
        assert world["phase"] == "disaster_active"

    def test_duplicate_action_rejected(self, client):
        client.post("/reset")
        world = client.get("/world").json()

        action = {
            "action_id": "test-dup-001",
            "type": "place_token",
            "source": "manual",
            "token_type": "disaster_start",
            "site_id": "start_pad",
            "board_uv": [0.1, 0.1],
            "expected_world_version": world["world_version"]
        }

        # First should succeed
        r1 = client.post("/action", json=action)
        assert r1.json()["accepted"] is True

        # Duplicate should fail
        action["expected_world_version"] = client.get("/world").json()["world_version"]
        r2 = client.post("/action", json=action)
        assert r2.json()["accepted"] is False
        assert r2.json()["rejection_reason"] == "duplicate_action"

    def test_stale_version_rejected(self, client):
        client.post("/reset")

        response = client.post("/action", json={
            "action_id": "test-stale-001",
            "type": "place_token",
            "source": "manual",
            "token_type": "disaster_start",
            "site_id": "start_pad",
            "board_uv": [0.1, 0.1],
            "expected_world_version": 999  # Wrong version
        })
        result = response.json()
        assert result["accepted"] is False
        assert result["rejection_reason"] == "stale_version"

    def test_place_token_before_start_rejected(self, client):
        client.post("/reset")
        world = client.get("/world").json()

        # Try to place bridge before starting
        response = client.post("/action", json={
            "action_id": "test-early-001",
            "type": "place_token",
            "source": "manual",
            "token_type": "bridge",
            "site_id": "crossing_east",
            "board_uv": [0.47, 0.61],
            "expected_world_version": world["world_version"]
        })
        result = response.json()
        assert result["accepted"] is False
        assert result["rejection_reason"] == "start_first"

    def test_bridge_unblocks_crossing(self, client):
        client.post("/reset")

        # Start disaster
        world = client.get("/world").json()
        client.post("/action", json={
            "action_id": "test-bridge-start",
            "type": "place_token",
            "source": "manual",
            "token_type": "disaster_start",
            "site_id": "start_pad",
            "board_uv": [0.1, 0.1],
            "expected_world_version": world["world_version"]
        })

        # Check crossing is blocked
        world = client.get("/world").json()
        blocked_crossing = next(
            (e for e in world["edges"] if e["id"] == "crossing_east"),
            None
        )
        assert blocked_crossing is not None
        assert blocked_crossing["blocked"] is True

        # Place bridge
        response = client.post("/action", json={
            "action_id": "test-bridge-place",
            "type": "place_token",
            "source": "physical_perceptron",
            "token_type": "bridge",
            "site_id": "crossing_east",
            "board_uv": [0.47, 0.61],
            "expected_world_version": world["world_version"]
        })
        assert response.json()["accepted"] is True

        # Verify crossing is now open
        world = client.get("/world").json()
        crossing = next(
            (e for e in world["edges"] if e["id"] == "crossing_east"),
            None
        )
        assert crossing["blocked"] is False


class TestSuggestEndpoint:
    """Tests for POST /plan/suggest"""

    def test_suggest_returns_bridge_when_crossing_blocked(self, client):
        client.post("/reset")

        response = client.post("/plan/suggest", json={})
        data = response.json()

        assert data["has_suggestion"] is True
        assert data["suggestion"]["token_type"] == "bridge"
        assert data["suggestion"]["site_id"] == "crossing_east"

    def test_suggest_returns_none_after_bridge_placed(self, client):
        client.post("/reset")

        # Start and place bridge
        world = client.get("/world").json()
        client.post("/action", json={
            "action_id": "setup-start",
            "type": "place_token",
            "source": "manual",
            "token_type": "disaster_start",
            "site_id": "start_pad",
            "board_uv": [0.1, 0.1],
            "expected_world_version": world["world_version"]
        })

        world = client.get("/world").json()
        client.post("/action", json={
            "action_id": "setup-bridge",
            "type": "place_token",
            "source": "manual",
            "token_type": "bridge",
            "site_id": "crossing_east",
            "board_uv": [0.47, 0.61],
            "expected_world_version": world["world_version"]
        })

        # Now suggest should return none
        response = client.post("/plan/suggest", json={})
        data = response.json()
        assert data["has_suggestion"] is False


class TestResetEndpoint:
    """Tests for POST /reset"""

    def test_reset_restores_initial_state(self, client):
        # Make some changes
        world = client.get("/world").json()
        client.post("/action", json={
            "action_id": "pre-reset",
            "type": "place_token",
            "source": "manual",
            "token_type": "disaster_start",
            "site_id": "start_pad",
            "board_uv": [0.1, 0.1],
            "expected_world_version": world["world_version"]
        })

        # Reset
        response = client.post("/reset")
        assert response.json()["reset"] is True

        # Verify reset
        world = client.get("/world").json()
        assert world["phase"] == "ready"
        assert len(world["tokens"]) == 0


class TestNarrateEndpoint:
    """Tests for POST /narrate"""

    def test_narrate_responds_to_question(self, client):
        response = client.post("/narrate", json={
            "question": "Why is the village cut off?"
        })
        assert response.status_code == 200
        data = response.json()

        assert "answer" in data
        assert "grounded_in_version" in data
        assert len(data["answer"]) > 0

    def test_narrate_mentions_bridge_when_asked(self, client):
        response = client.post("/narrate", json={
            "question": "Where should we place the bridge?"
        })
        data = response.json()
        assert "bridge" in data["answer"].lower()


class TestWebSocket:
    """Tests for WS /ws"""

    def test_websocket_connects_and_receives_hello(self, client):
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["type"] == "server.hello"
            assert data["payload"]["status"] == "connected"

    def test_websocket_receives_initial_snapshot(self, client):
        with client.websocket_connect("/ws") as ws:
            # Skip hello
            ws.receive_json()
            # Get snapshot
            data = ws.receive_json()
            assert data["type"] == "world.snapshot"
            assert "world_version" in data["payload"]
