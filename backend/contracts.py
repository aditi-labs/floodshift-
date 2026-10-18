"""
FLOODSHIFT Shared Contracts - Schema Version 2
Frozen at T+20min per spec. Changes require P2/P3/P4 agreement.

Person 3 owns this file. P4 consumes for WorldService, P2 mirrors to TypeScript.
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


# =============================================================================
# TOKEN TYPES - Six required pieces
# =============================================================================

class TokenType(str, Enum):
    HOSPITAL = "hospital"
    SHELTER = "shelter"
    FOOD_SHELTER = "food_shelter"
    BRIDGE = "bridge"
    DISASTER_START = "disaster_start"
    PERSON = "person"
    # Optional legacy pieces (P1/P2)
    TRUCK = "truck"
    HELICOPTER = "helicopter"
    TIME_DIAL = "time_dial"


class SiteKind(str, Enum):
    MEDICAL_SITE = "medical_site"
    SHELTER_SITE = "shelter_site"
    FOOD_SITE = "food_site"
    BRIDGE_CROSSING = "bridge_crossing"
    CONTROL_START_PAD = "control_start_pad"
    POPULATION_NODE = "population_node"


class Phase(str, Enum):
    PREVENTION = "prevention"  # Pre-disaster planning mode
    READY = "ready"
    DISASTER_ACTIVE = "disaster_active"


class VisionStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


class VisionSource(str, Enum):
    PERCEPTRON = "perceptron"
    MANUAL = "manual"
    REPLAY = "replay"


# =============================================================================
# OBJECT OBSERVATION - Person 3 produces, P4 reducer consumes
# =============================================================================

class ObjectObservation(BaseModel):
    """
    Emitted by Person 3's perception pipeline when a token is stably detected.
    Combines Perceptron semantic classification with OpenCV marker pose.
    """
    event_type: Literal["object_observed"] = "object_observed"
    event_id: str
    frame_id: int
    token_id: str  # e.g. "fiducial-31" - instance identity from ArUco
    object_type: TokenType  # semantic type from Perceptron
    class_source: VisionSource
    perceptron_box_1000: list[int] | None = None  # [x1, y1, x2, y2] in 0-1000 coords
    board_uv: tuple[float, float]  # normalized (0,0) top-left to (1,1) bottom-right
    rotation_deg: float = 0.0
    stable_ms: int  # how long the object has been stationary
    vision_status: VisionStatus
    frame_provenance: str  # e.g. "local:fixtures/frame224.png"


# =============================================================================
# WORLD ACTION - P3 gateway / P2 manual controls -> P4 reducer
# =============================================================================

class ActionType(str, Enum):
    PLACE_TOKEN = "place_token"
    MOVE_TOKEN = "move_token"
    REMOVE_TOKEN = "remove_token"
    ADVANCE_STAGE = "advance_stage"
    RESET = "reset"
    SUGGEST = "suggest"
    BRANCH = "branch"
    COMPARE = "compare"


class WorldAction(BaseModel):
    """
    Sent to POST /action. P3 validates and forwards to P4's reducer.
    """
    action_id: str
    type: ActionType
    source: Literal["physical_perceptron", "manual", "replay"]
    token_id: str | None = None
    token_type: TokenType | None = None
    site_id: str | None = None
    board_uv: tuple[float, float] | None = None
    expected_world_version: int
    timestamp_utc: datetime = Field(default_factory=datetime.utcnow)


class ActionResult(BaseModel):
    """Response from POST /action"""
    accepted: bool
    action_id: str
    world_version: int
    rejection_reason: str | None = None


# =============================================================================
# WORLD SNAPSHOT - P4 produces, P3 serves via API, P2 renders
# =============================================================================

class TokenState(BaseModel):
    """State of a placed token on the board"""
    id: str
    type: TokenType
    board_uv: tuple[float, float]
    site_id: str | None = None
    vision_source: VisionSource
    status: Literal["accepted", "pending", "rejected"]


class FacilityState(BaseModel):
    """State of an active service facility"""
    id: str
    type: TokenType
    capacity_model: int
    used_capacity_model: int
    reachable: bool


class PopulationDemand(BaseModel):
    """Demand at a population node"""
    id: str
    households_model: int
    people_model: int
    need_food: int
    need_medical: int
    need_refuge: int


class EdgeState(BaseModel):
    """State of a road/bridge edge"""
    id: str
    blocked: bool
    reason: str | None = None


class WorldMetrics(BaseModel):
    """Computed metrics for the current world state"""
    people_reachable_for_medical: int = 0
    people_reachable_for_food: int = 0
    people_reachable_for_shelter: int = 0
    unmet_food_model: int = 0
    unmet_medical_model: int = 0
    unmet_refuge_model: int = 0
    blocked_roads: int = 0


class GhostSuggestion(BaseModel):
    """AI-recommended placement for ghost overlay"""
    token_type: TokenType
    site_id: str
    board_uv: tuple[float, float]
    reason_code: str


class NarrationEvent(BaseModel):
    """Event for Gemini/narrator"""
    event_type: str
    model_only: bool = True


class WorldSnapshot(BaseModel):
    """
    Single source of truth for world state.
    P4 produces, P3 broadcasts via WebSocket, P2 renders.
    """
    schema_version: int = 2
    world_version: int
    scenario_id: str
    phase: Phase
    simulation_stage: int = 0
    branch_id: str = "main"

    token_inventory: dict[str, int]  # available tokens to place
    tokens: list[TokenState]  # placed tokens
    facilities: list[FacilityState]
    population_demand: list[PopulationDemand]
    edges: list[EdgeState]
    metrics: WorldMetrics

    ghost_suggestion: GhostSuggestion | None = None
    narration_event: NarrationEvent | None = None
    provenance_label: str = "Historical map data; intervention outcomes are illustrative"

    # Prevention mode fields
    mode: Literal["prevention", "relief"] = "relief"
    risk_zones: list["RiskZone"] = []
    prevention_metrics: "PreventionMetrics | None" = None
    prevention_comparison: "PreventionComparison | None" = None


# =============================================================================
# PREVENTION MODE - Disaster prevention planning
# =============================================================================

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskZone(BaseModel):
    """Risk overlay zone for projection"""
    zone_id: str
    board_uv_center: tuple[float, float]
    radius_uv: float
    risk_level: RiskLevel
    flood_probability: float  # 0-1
    population_exposed: int
    elevation_m: float | None = None


class PreventionMetrics(BaseModel):
    """Metrics for prevention planning mode"""
    vulnerability_score: float = 0.0  # 0=resilient, 1=fragile
    lives_at_risk: int = 0
    lives_protected: int = 0
    evacuation_time_minutes: int = 0
    infrastructure_survival_rate: float = 0.0  # 0-1
    prevention_cost_model: int = 0
    cost_per_life_protected: float = 0.0


class ScenarioOutcome(BaseModel):
    """Outcome of a simulated disaster scenario"""
    scenario_id: str
    severity: Literal["category_1", "category_2", "category_3"]
    casualties_model: int
    infrastructure_damaged: int
    evacuation_time_minutes: int
    recovery_cost_model: int


class PreventionComparison(BaseModel):
    """Side-by-side comparison of outcomes"""
    scenario_id: str
    without_prevention: ScenarioOutcome
    with_prevention: ScenarioOutcome
    lives_saved: int
    cost_avoided: int
    prevention_investment: int
    roi_ratio: float  # (cost_avoided - investment) / investment


class PreventionSuggestion(BaseModel):
    """AI-recommended prevention placement"""
    token_type: TokenType
    site_id: str
    board_uv: tuple[float, float]
    reason_code: str
    effectiveness: float  # 0-1, how much risk is reduced
    lives_protected: int
    cost_model: int


# =============================================================================
# API SCHEMAS
# =============================================================================

class HealthResponse(BaseModel):
    status: str
    world_version: int | None = None
    vision_mode: str = "mock"
    perceptron_status: str = "not_connected"
    gemini_status: str = "not_connected"


class SuggestRequest(BaseModel):
    goal_id: str | None = None


class BranchSaveRequest(BaseModel):
    name: str


class BranchLoadRequest(BaseModel):
    branch_id: str


class NarrateRequest(BaseModel):
    question: str


class NarrateResponse(BaseModel):
    answer: str
    grounded_in_version: int


# =============================================================================
# WEBSOCKET EVENT ENVELOPE
# =============================================================================

class WSEvent(BaseModel):
    """WebSocket message envelope"""
    type: Literal["world.snapshot", "vision.status", "narration", "warning", "server.hello"]
    seq: int
    sent_at: datetime = Field(default_factory=datetime.utcnow)
    payload: dict


# =============================================================================
# CALIBRATION - Person 3 internal
# =============================================================================

class MarkerObservation(BaseModel):
    """Raw ArUco marker detection"""
    marker_id: int
    corners_px: list[tuple[float, float]]  # 4 corners in camera pixels
    center_px: tuple[float, float]


class BoardCalibration(BaseModel):
    """Camera-to-board homography result"""
    valid: bool
    corner_markers_found: list[int]
    homography_matrix: list[list[float]] | None = None  # 3x3 flattened
    error_mm: float | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
