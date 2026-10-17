"""
Mock World Service for development without P4's real WorldService.
Allows P2 and P3 to develop against a working API immediately.

Person 3 owns this file. Replace with P4's real WorldService when ready.
"""
from __future__ import annotations
import json
import copy
from pathlib import Path
from datetime import datetime
from typing import Protocol

from backend.contracts import (
    WorldSnapshot, WorldAction, ActionResult, GhostSuggestion,
    TokenState, Phase, TokenType, VisionSource, ActionType
)


class WorldServiceProtocol(Protocol):
    """Interface that P4's real WorldService must implement."""

    def snapshot(self) -> WorldSnapshot:
        """Return current world state."""
        ...

    def apply(self, action: WorldAction) -> ActionResult:
        """Apply an action and return result."""
        ...

    def suggest(self, goal_id: str | None = None) -> GhostSuggestion | None:
        """Get AI suggestion for next placement."""
        ...

    def reset(self) -> WorldSnapshot:
        """Reset to initial state."""
        ...


class MockWorldService:
    """
    Mock implementation for development.
    Simulates basic state changes without real routing logic.
    """

    def __init__(self, fixture_path: Path | None = None):
        if fixture_path is None:
            # The shared P4 fixture is a staged demo; the mock resets to ready.
            fixture_path = Path(__file__).parent.parent.parent / "contracts" / "fixture_mock_world.json"

        with open(fixture_path) as f:
            self._initial_state = json.load(f)

        self._state = copy.deepcopy(self._initial_state)
        self._applied_action_ids: set[str] = set()

        # Mock sites for validation
        self._sites = {
            "start_pad": {"kind": "control_start_pad", "board_uv": [0.1, 0.1]},
            "people_east": {"kind": "population_node", "board_uv": [0.72, 0.42]},
            "people_west": {"kind": "population_node", "board_uv": [0.28, 0.45]},
            "medical_site_west": {"kind": "medical_site", "board_uv": [0.25, 0.55]},
            "shelter_site_west": {"kind": "shelter_site", "board_uv": [0.22, 0.65]},
            "food_site_west": {"kind": "food_site", "board_uv": [0.30, 0.60]},
            "crossing_east": {"kind": "bridge_crossing", "board_uv": [0.47, 0.61]},
        }

    def snapshot(self) -> WorldSnapshot:
        """Return current world state as Pydantic model."""
        return WorldSnapshot(**self._state)

    def apply(self, action: WorldAction) -> ActionResult:
        """Apply action with basic validation."""
        # Check for duplicate
        if action.action_id in self._applied_action_ids:
            return ActionResult(
                accepted=False,
                action_id=action.action_id,
                world_version=self._state["world_version"],
                rejection_reason="duplicate_action"
            )

        # Check version
        if action.expected_world_version != self._state["world_version"]:
            return ActionResult(
                accepted=False,
                action_id=action.action_id,
                world_version=self._state["world_version"],
                rejection_reason="stale_version"
            )

        # Handle different action types
        if action.type == ActionType.RESET:
            return self._handle_reset(action)
        elif action.type == ActionType.PLACE_TOKEN:
            return self._handle_place_token(action)
        elif action.type == ActionType.SUGGEST:
            # Suggestion doesn't mutate state
            return ActionResult(
                accepted=True,
                action_id=action.action_id,
                world_version=self._state["world_version"]
            )
        else:
            return ActionResult(
                accepted=False,
                action_id=action.action_id,
                world_version=self._state["world_version"],
                rejection_reason=f"action_type_not_implemented: {action.type}"
            )

    def _handle_reset(self, action: WorldAction) -> ActionResult:
        """Reset to initial state."""
        self._state = copy.deepcopy(self._initial_state)
        self._applied_action_ids.clear()
        return ActionResult(
            accepted=True,
            action_id=action.action_id,
            world_version=self._state["world_version"]
        )

    def _handle_place_token(self, action: WorldAction) -> ActionResult:
        """Handle token placement with mock validation."""
        token_type = action.token_type
        site_id = action.site_id

        if token_type is None:
            return self._reject(action, "missing_token_type")

        # Check inventory
        inventory_key = token_type.value if isinstance(token_type, TokenType) else token_type
        if self._state["token_inventory"].get(inventory_key, 0) <= 0:
            return self._reject(action, "resource_exhausted")

        # Handle disaster_start specially
        if token_type == TokenType.DISASTER_START or token_type == "disaster_start":
            if self._state["phase"] != "ready":
                return self._reject(action, "already_started")
            self._state["phase"] = "disaster_active"
            self._state["simulation_stage"] = 1
        elif self._state["phase"] != "disaster_active":
            return self._reject(action, "start_first")

        # Check site validity (mock - just check it exists)
        if site_id and site_id not in self._sites:
            return self._reject(action, "invalid_site")

        # Special handling for bridge - unblock the crossing
        if token_type == TokenType.BRIDGE or token_type == "bridge":
            for edge in self._state["edges"]:
                if edge["id"] == "crossing_east":
                    edge["blocked"] = False
                    edge["reason"] = "counterfactual_temporary_bridge"
            self._state["metrics"]["blocked_roads"] = 0

        # Add token to placed tokens
        token_state = {
            "id": action.token_id or f"token-{token_type}-{len(self._state['tokens'])+1}",
            "type": inventory_key,
            "board_uv": list(action.board_uv) if action.board_uv else [0.5, 0.5],
            "site_id": site_id,
            "vision_source": "perceptron" if action.source == "physical_perceptron" else "manual",
            "status": "accepted"
        }
        self._state["tokens"].append(token_state)

        # Decrement inventory
        self._state["token_inventory"][inventory_key] -= 1

        # Increment version
        self._state["world_version"] += 1
        self._applied_action_ids.add(action.action_id)

        return ActionResult(
            accepted=True,
            action_id=action.action_id,
            world_version=self._state["world_version"]
        )

    def _reject(self, action: WorldAction, reason: str) -> ActionResult:
        return ActionResult(
            accepted=False,
            action_id=action.action_id,
            world_version=self._state["world_version"],
            rejection_reason=reason
        )

    def suggest(self, goal_id: str | None = None) -> GhostSuggestion | None:
        """Return mock ghost suggestion for bridge placement."""
        # Check if bridge is available and crossing is blocked
        if self._state["token_inventory"].get("bridge", 0) <= 0:
            return None

        for edge in self._state["edges"]:
            if edge["id"] == "crossing_east" and edge["blocked"]:
                return GhostSuggestion(
                    token_type=TokenType.BRIDGE,
                    site_id="crossing_east",
                    board_uv=(0.47, 0.61),
                    reason_code="improves_multi_service_access"
                )

        return None

    def reset(self) -> WorldSnapshot:
        """Reset and return new state."""
        self._state = copy.deepcopy(self._initial_state)
        self._applied_action_ids.clear()
        return self.snapshot()
