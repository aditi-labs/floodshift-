"""
Prevention Mode Tests
Person 3 owns these tests.

Run with: pytest tests/test_prevention.py -v
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client():
    """Test client for API."""
    with TestClient(app) as c:
        yield c


class TestPreventionRiskMap:
    """Tests for /prevention/risk-map endpoint."""

    def test_risk_map_available(self, client):
        response = client.get("/prevention/risk-map")
        assert response.status_code == 200
        data = response.json()
        assert data["available"] is True

    def test_risk_map_has_zones(self, client):
        response = client.get("/prevention/risk-map")
        data = response.json()
        assert "risk_zones" in data
        assert isinstance(data["risk_zones"], list)

    def test_risk_zone_structure(self, client):
        response = client.get("/prevention/risk-map")
        data = response.json()
        if data["risk_zones"]:
            zone = data["risk_zones"][0]
            assert "zone_id" in zone
            assert "board_uv_center" in zone
            assert "risk_level" in zone
            assert zone["risk_level"] in ["low", "medium", "high", "critical", "safe"]


class TestPreventionAnalyze:
    """Tests for /prevention/analyze endpoint."""

    def test_analyze_returns_vulnerability(self, client):
        response = client.post("/prevention/analyze?scenario=default")
        assert response.status_code == 200
        data = response.json()
        assert "vulnerability_score" in data

    def test_analyze_vulnerability_in_range(self, client):
        response = client.post("/prevention/analyze?scenario=default")
        data = response.json()
        assert 0 <= data["vulnerability_score"] <= 1

    def test_analyze_has_lives_at_risk(self, client):
        response = client.post("/prevention/analyze?scenario=default")
        data = response.json()
        assert "lives_at_risk" in data
        assert data["lives_at_risk"] >= 0


class TestPreventionSuggestions:
    """Tests for /prevention/suggestions endpoint."""

    def test_suggestions_returns_recommendation(self, client):
        response = client.get("/prevention/suggestions?scenario=default")
        assert response.status_code == 200
        data = response.json()
        assert "has_suggestion" in data

    def test_suggestion_has_required_fields(self, client):
        response = client.get("/prevention/suggestions?scenario=default")
        data = response.json()
        if data["has_suggestion"]:
            suggestion = data["suggestion"]
            assert "token_type" in suggestion
            assert "board_uv" in suggestion
            assert "lives_protected" in suggestion

    def test_suggestion_uses_existing_tokens(self, client):
        response = client.get("/prevention/suggestions?scenario=default")
        data = response.json()
        if data["has_suggestion"]:
            # Should only suggest existing token types
            valid_types = ["hospital", "shelter", "food_shelter", "bridge", "person"]
            assert data["suggestion"]["token_type"] in valid_types


class TestPreventionCompare:
    """Tests for /prevention/compare endpoint."""

    def test_compare_returns_outcomes(self, client):
        response = client.post("/prevention/compare?scenario=default")
        assert response.status_code == 200
        data = response.json()
        assert "without_prevention" in data
        assert "with_prevention" in data

    def test_compare_has_lives_saved(self, client):
        response = client.post("/prevention/compare?scenario=default")
        data = response.json()
        assert "lives_saved" in data
        assert "effectiveness_score" in data

    def test_compare_outcome_structure(self, client):
        response = client.post("/prevention/compare?scenario=default")
        data = response.json()
        outcome = data["without_prevention"]
        assert "casualties_model" in outcome
        assert "evacuation_time_minutes" in outcome

    def test_compare_casualties_non_negative(self, client):
        response = client.post("/prevention/compare?scenario=default")
        data = response.json()
        assert data["without_prevention"]["casualties_model"] >= 0
        assert data["with_prevention"]["casualties_model"] >= 0
