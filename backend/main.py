"""
FLOODSHIFT FastAPI Server
Person 3 owns this file.

Provides API endpoints for:
- World state (GET /world)
- Actions (POST /action)
- Suggestions (POST /plan/suggest)
- WebSocket for real-time updates (WS /ws)
- Health check (GET /health)

Run with: uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations
import asyncio
import os
import uuid
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path

# Load environment variables from .env
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parents[1] / '.env'
    load_dotenv(env_path)
except ImportError:
    pass  # dotenv not installed, use system env vars

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.contracts import (
    WorldSnapshot, WorldAction, ActionResult, ActionType, TokenState,
    WorldMetrics, GhostSuggestion, EdgeState, Phase, TokenType, VisionSource,
    HealthResponse, SuggestRequest, NarrateRequest, NarrateResponse,
    BranchSaveRequest, BranchLoadRequest, WSEvent, RiskZone, RiskLevel
)

REPO_ROOT = Path(__file__).resolve().parents[1]
# Which P4 scenario bundle the live server runs. HOT-derived real map by default;
# nepal_rasuwa_v1 = schematic (prevention mode data), nepal_rasuwa_reasoning_v1 = flood routing.
SCENARIO_ID = os.environ.get("FLOODSHIFT_SCENARIO", "nepal_rasuwa_hot_v1")
# Optional durable SQLite session (parent directory must exist); empty = in-memory.
SESSION_PATH = os.environ.get("FLOODSHIFT_SESSION", "")

# Import real WorldService from P4, fallback to mock
USE_MOCK = os.environ.get("FLOODSHIFT_USE_MOCK", "false").lower() == "true"

if USE_MOCK:
    from backend.api.mock_world import MockWorldService as WorldService
else:
    try:
        from backend.world.service import WorldService
    except ImportError:
        print("WARNING: P4's WorldService not available, using mock")
        from backend.api.mock_world import MockWorldService as WorldService
        USE_MOCK = True


# =============================================================================
# GLOBAL STATE
# =============================================================================

# WebSocket clients for broadcasting
ws_clients: set[WebSocket] = set()
ws_seq: int = 0

# World service (P4's real implementation or mock)
world_service: WorldService | None = None

# Lock for world mutations
world_lock = asyncio.Lock()


# =============================================================================
# ADAPTER FUNCTIONS: Convert P4's dicts to Pydantic models
# =============================================================================

def _risk_zones(data: dict) -> list[RiskZone]:
    """Prevention risk circles, only for bundles whose node ids match the terrain data."""
    try:
        from backend.planning.prevention import get_risk_zones_for_snapshot
        bundle = world_service.scenario() if world_service and hasattr(world_service, 'scenario') else {}
        state = {'tokens': data.get('tokens', []), 'phase': data.get('phase')}
        return [RiskZone(
            zone_id=z.get('zone_id', ''), node_id=z.get('node_id', ''),
            board_uv_center=tuple(z.get('board_uv_center', (0.5, 0.5))),
            radius_uv=z.get('radius_uv', 0.08), risk_level=RiskLevel(z.get('risk_level', 'medium')),
            flood_probability=z.get('flood_probability', 0.5),
            base_probability=z.get('base_probability', 0.5),
            population_exposed=z.get('population_exposed', 0), elevation_m=z.get('elevation_m'),
            color=z.get('color', '#FFCC00'), is_protected=z.get('is_protected', False))
            for z in get_risk_zones_for_snapshot(bundle, state, mode='relief')]
    except Exception as e:
        print(f"Warning: Could not calculate risk zones: {e}")
        return []


def _dict_to_world_snapshot(data: dict) -> WorldSnapshot:
    """Validate P4's snapshot dict against the shared schema without dropping fields.

    Every field P4 computes (facilities, demand, service routes, ghost, narration
    event, routing decision) passes through; only keys unknown to the schema drop.
    """
    payload = dict(data)
    if payload.get('phase') not in {p.value for p in Phase}:
        payload['phase'] = Phase.READY.value
    payload['risk_zones'] = _risk_zones(data)
    return WorldSnapshot.model_validate(payload)


def _snapshot_model() -> WorldSnapshot:
    raw = world_service.snapshot()
    return _dict_to_world_snapshot(raw) if isinstance(raw, dict) else raw


def _world_version() -> int:
    raw = world_service.snapshot()
    return raw.get('world_version', 0) if isinstance(raw, dict) else raw.world_version


def _require_real_world(method: str):
    if not world_service:
        raise HTTPException(status_code=503, detail="World service not initialized")
    if not hasattr(world_service, method):
        raise HTTPException(status_code=501, detail=f"{type(world_service).__name__} does not support {method}")


def _action_result_from_dict(data: dict, action_id: str) -> ActionResult:
    """Convert P4's apply result dict to ActionResult Pydantic model."""
    return ActionResult(
        accepted=data.get('accepted', False),
        action_id=action_id,
        world_version=data.get('world_version', 0),
        rejection_reason=data.get('reason')
    )


# =============================================================================
# LIFESPAN
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup."""
    global world_service
    if USE_MOCK:
        world_service = WorldService()
        service_type = "MockWorldService"
    else:
        bundle_path = REPO_ROOT / "scenarios" / SCENARIO_ID
        if SESSION_PATH:
            # Corrupt/incompatible sessions raise SessionError: fix or choose a new path.
            world_service = WorldService.open_session(SESSION_PATH, bundle_path)
        else:
            world_service = WorldService.from_bundle(bundle_path)
        service_type = f"WorldService({SCENARIO_ID}{', session ' + SESSION_PATH if SESSION_PATH else ''})"
    print(f"FLOODSHIFT API started with {service_type}")

    # Get initial version - handle both dict and Pydantic responses
    snapshot = world_service.snapshot()
    if isinstance(snapshot, dict):
        print(f"Initial world version: {snapshot.get('world_version', 1)}")
    else:
        print(f"Initial world version: {snapshot.world_version}")
    yield
    print("FLOODSHIFT API shutting down")


# =============================================================================
# APP SETUP
# =============================================================================

app = FastAPI(
    title="FLOODSHIFT API",
    description="Physical AI disaster response simulation",
    version="0.1.0",
    lifespan=lifespan
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# WEBSOCKET BROADCAST
# =============================================================================

async def broadcast_snapshot():
    """Broadcast current world state to all connected clients."""
    global ws_seq
    if not world_service:
        return

    snapshot = _snapshot_model()
    ws_seq += 1

    event = WSEvent(
        type="world.snapshot",
        seq=ws_seq,
        sent_at=datetime.utcnow(),
        payload=snapshot.model_dump()
    )

    disconnected = []
    for ws in ws_clients:
        try:
            await ws.send_json(event.model_dump(mode="json"))
        except Exception:
            disconnected.append(ws)

    for ws in disconnected:
        ws_clients.discard(ws)


async def broadcast_event(event_type: str, payload: dict):
    """Broadcast arbitrary event to all clients."""
    global ws_seq
    ws_seq += 1

    event = WSEvent(
        type=event_type,  # type: ignore
        seq=ws_seq,
        sent_at=datetime.utcnow(),
        payload=payload
    )

    disconnected = []
    for ws in ws_clients:
        try:
            await ws.send_json(event.model_dump(mode="json"))
        except Exception:
            disconnected.append(ws)

    for ws in disconnected:
        ws_clients.discard(ws)


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    version = None
    if world_service:
        raw_snapshot = world_service.snapshot()
        version = raw_snapshot.get('world_version', 1) if isinstance(raw_snapshot, dict) else raw_snapshot.world_version

    # Gemini narration (P4 adapter): configured = key + SDK present; LIVE is per answer.
    gemini_status = "not_configured"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        try:
            import google.genai  # noqa: F401
            gemini_status = "configured"
        except ImportError:
            gemini_status = "sdk_unavailable"

    return HealthResponse(
        status="ok",
        world_version=version,
        # The camera pipeline is not started by this server; actions arrive manually.
        vision_mode="mock" if USE_MOCK else "manual",
        perceptron_status="not_connected",
        gemini_status=gemini_status
    )


@app.get("/world", response_model=WorldSnapshot)
async def get_world():
    """Get current world state."""
    if not world_service:
        raise HTTPException(status_code=503, detail="World service not initialized")
    return _snapshot_model()


@app.get("/scenario")
async def get_scenario():
    """Static board geometry (roads, rivers, pads, flood footprints) in board UV."""
    _require_real_world("scenario_geometry")
    return world_service.scenario_geometry()


@app.post("/action", response_model=ActionResult)
async def post_action(action: WorldAction):
    """
    Apply an action to the world.
    P2 sends manual actions, P3 sends physical observations.
    P4's reducer processes them.
    """
    if not world_service:
        raise HTTPException(status_code=503, detail="World service not initialized")

    async with world_lock:
        # P4's apply accepts Pydantic models or dicts
        raw_result = world_service.apply(action)

    # Convert to ActionResult if P4 returned a dict
    if isinstance(raw_result, dict):
        result = _action_result_from_dict(raw_result, action.action_id)
    else:
        result = raw_result

    # Broadcast updated state if action was accepted
    if result.accepted:
        await broadcast_snapshot()

    return result


@app.post("/plan/suggest")
async def suggest_action(request: SuggestRequest):
    """
    Get AI suggestion for next placement.
    Returns ghost bridge location or other recommendations.
    """
    if not world_service:
        raise HTTPException(status_code=503, detail="World service not initialized")

    goal = request.goal_id or 'needs_served'
    if not hasattr(world_service, 'request_suggestion'):  # mock world
        suggestion = world_service.suggest(goal)
        data = suggestion if isinstance(suggestion, dict) or suggestion is None else suggestion.model_dump()
        return {"has_suggestion": data is not None, "suggestion": data, "world_version": _world_version()}

    async with world_lock:
        result = world_service.request_suggestion(goal)
    if result['accepted']:
        # The ghost is now part of the authoritative snapshot; every screen shows it.
        await broadcast_snapshot()
    elif result['reason'] == 'unsupported_goal':
        raise HTTPException(status_code=400, detail="goal_id must be needs_served, food, medical or refuge")
    return {"has_suggestion": result['accepted'], "suggestion": result.get('suggestion'),
            "world_version": result['world_version'], "rejection_reason": result['reason']}


@app.post("/reset")
async def reset_world():
    """Reset world to initial state."""
    if not world_service:
        raise HTTPException(status_code=503, detail="World service not initialized")

    async with world_lock:
        raw_snapshot = world_service.snapshot()
        current_version = raw_snapshot.get('world_version', 1) if isinstance(raw_snapshot, dict) else raw_snapshot.world_version

        action = WorldAction(
            action_id=f"reset-{uuid.uuid4().hex[:8]}",
            type=ActionType.RESET,
            source="manual",
            expected_world_version=current_version
        )
        result = world_service.apply(action)
    accepted = result['accepted'] if isinstance(result, dict) else result.accepted

    if accepted:
        await broadcast_snapshot()
    return {"reset": accepted, "world_version": _world_version()}


@app.post("/branch/save")
async def branch_save(request: BranchSaveRequest):
    """Bookmark the current world under a name (e.g. A, B, baseline)."""
    _require_real_world("save_branch")
    async with world_lock:
        result = world_service.save_branch(request.name)
    if not result['accepted']:
        raise HTTPException(status_code=400, detail=result['reason'])
    await broadcast_snapshot()
    return {"branch_id": request.name, "world_version": result['world_version']}


@app.post("/branch/load", response_model=WorldSnapshot)
async def branch_load(request: BranchLoadRequest):
    """Continue from a saved bookmark (the bookmark itself is not modified)."""
    _require_real_world("load_branch")
    async with world_lock:
        result = world_service.load_branch(request.branch_id)
    if not result['accepted']:
        raise HTTPException(status_code=404 if result['reason'] == 'unknown_branch' else 400,
                            detail=result['reason'])
    await broadcast_snapshot()
    return _snapshot_model()


@app.get("/branch/compare")
async def branch_compare(a: str, b: str):
    """Model metrics of two saved branches, computed by the reducer, not the UI."""
    _require_real_world("compare")
    try:
        comparison = world_service.compare([a, b])
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))
    return {
        "baseline_snapshot_id": "baseline" if world_service.has_branch("baseline") else None,
        "branches": [{"id": r["id"], "action": ", ".join(r["placed"]) or "no pieces",
                      **r["metrics"]} for r in comparison["branches"]],
        "delta_from_first": comparison["delta_from_first"],
        "metric_provenance": comparison["metric_provenance"],
    }


@app.post("/narrate", response_model=NarrateResponse)
async def narrate(request: NarrateRequest):
    """
    Get AI narration for current state using Gemini.
    Answers are grounded in actual simulation data.
    """
    if not world_service:
        raise HTTPException(status_code=503, detail="World service not initialized")

    if not hasattr(world_service, 'frozen_copy'):  # mock world: state-derived text only
        snapshot = _snapshot_model()
        answer = (f"The scenario is in '{snapshot.phase.value}' phase with "
                  f"{snapshot.metrics.blocked_roads} blocked road(s) in this model.")
        if "bridge" in request.question.lower():
            suggestion = world_service.suggest('needs_served')
            answer += (f" The planner suggests a temporary bridge at {suggestion.site_id}." if suggestion
                       else " No bridge placement currently improves model access.")
        return NarrateResponse(answer=answer, grounded_in_version=snapshot.world_version)

    # P4's read-only tool-calling narrator; never blocks the event loop, never mutates.
    from backend.narration.gemini_adapter import GeminiNarrator
    result = await asyncio.to_thread(GeminiNarrator().answer, world_service, request.question)
    await broadcast_event("narration", {"text": result['text'],
                                        "source": "gemini" if result['mode'] == 'LIVE' else "template",
                                        "world_version": result['world_version']})
    return NarrateResponse(answer=result['text'], grounded_in_version=result['world_version'],
                           mode=result['mode'], reason=result['reason'])


# =============================================================================
# WEBSOCKET
# =============================================================================

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    WebSocket for real-time world state updates.
    Broadcasts WorldSnapshot on every state change.
    """
    await ws.accept()
    ws_clients.add(ws)

    try:
        # Send initial hello
        global ws_seq
        ws_seq += 1
        hello = WSEvent(
            type="server.hello",
            seq=ws_seq,
            sent_at=datetime.utcnow(),
            payload={"status": "connected", "clients": len(ws_clients)}
        )
        await ws.send_json(hello.model_dump(mode="json"))

        # Send current state
        if world_service:
            snapshot = _snapshot_model()
            ws_seq += 1
            event = WSEvent(
                type="world.snapshot",
                seq=ws_seq,
                sent_at=datetime.utcnow(),
                payload=snapshot.model_dump()
            )
            await ws.send_json(event.model_dump(mode="json"))

        # Keep connection alive, handle incoming messages
        while True:
            data = await ws.receive_text()
            # Client can send heartbeats or requests
            if data == "ping":
                await ws.send_text("pong")

    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)


# =============================================================================
# PERCEPTION ENDPOINTS (P3 internal, for debugging)
# =============================================================================

@app.post("/perception/scan")
async def trigger_scan():
    """
    Trigger a perception scan (for debugging).
    In production, camera runs continuously.
    """
    return {
        "status": "scan_triggered",
        "mode": "mock",
        "message": "Camera not connected. Use mock observations."
    }


@app.get("/perception/status")
async def perception_status():
    """Get current perception system status."""
    return {
        "camera": "not_connected",
        "perceptron": "not_connected",
        "calibration": "not_calibrated",
        "mode": "mock"
    }


# =============================================================================
# PREVENTION MODE ENDPOINTS
# =============================================================================

# Lazy load prevention module (optional feature)
_prevention_module = None
_risk_data = None


def _get_prevention():
    """Lazy load prevention planning module."""
    global _prevention_module
    if _prevention_module is None:
        try:
            from backend.planning import prevention as prev_mod
            _prevention_module = prev_mod
        except ImportError:
            _prevention_module = False
    if not _prevention_module:
        return False, None
    # Risk data belongs to the loaded scenario bundle (measured for the HOT map).
    bundle = world_service.scenario() if world_service and hasattr(world_service, 'scenario') else None
    return _prevention_module, _prevention_module.load_risk_data(bundle)


@app.get("/prevention/risk-map")
async def get_risk_map():
    """
    Get risk overlay data for projection.
    Returns risk zones with flood probability and population exposure.
    """
    if not world_service:
        raise HTTPException(status_code=503, detail="World service not initialized")

    prevention, risk_data = _get_prevention()
    if not prevention or not risk_data or (
            hasattr(world_service, 'scenario') and not prevention.supports_bundle(world_service.scenario())):
        return {"available": False, "risk_zones": [],
                "message": f"No prevention terrain data matches {SCENARIO_ID}"}

    # Get bundle (scenario data)
    if hasattr(world_service, 'scenario'):
        bundle = world_service.scenario()
    elif hasattr(world_service, '_bundle'):
        bundle = world_service._bundle
    else:
        bundle = {}

    zones = prevention.get_risk_zones(bundle, risk_data)

    return {
        "available": True,
        "risk_zones": zones,
        "scenarios": list(prevention.flood_scenarios(bundle).keys()),
        "provenance": prevention.provenance(bundle),
    }


@app.post("/prevention/analyze")
async def analyze_prevention(scenario: str = "category_2"):
    """
    Run what-if scenario analysis.
    Shows vulnerability and effectiveness of current prevention measures.
    """
    if not world_service:
        raise HTTPException(status_code=503, detail="World service not initialized")

    prevention, risk_data = _get_prevention()
    if not prevention:
        raise HTTPException(status_code=501, detail="Prevention mode not available")
    if not risk_data or (hasattr(world_service, 'scenario') and not prevention.supports_bundle(world_service.scenario())):
        raise HTTPException(status_code=409, detail=f"No prevention terrain data matches {SCENARIO_ID}")

    # Get bundle (scenario data) - handle both mock and real services
    if hasattr(world_service, 'scenario'):
        bundle = world_service.scenario()
    elif hasattr(world_service, '_bundle'):
        bundle = world_service._bundle
    else:
        bundle = risk_data  # Fallback to risk data structure

    # Get current state
    raw_snapshot = world_service.snapshot()
    if isinstance(raw_snapshot, dict):
        state = {'tokens': {t.get('id', str(i)): t for i, t in enumerate(raw_snapshot.get('tokens', []))}}
    else:
        state = {'tokens': {}}

    vulnerability = prevention.calculate_vulnerability_score(bundle, state, risk_data)
    lives_at_risk = prevention.calculate_lives_at_risk(bundle, risk_data, scenario)
    effectiveness = prevention.calculate_prevention_effectiveness(bundle, state, risk_data, scenario)

    return {
        "scenario": scenario,
        "vulnerability_score": round(vulnerability, 2),
        "lives_at_risk": lives_at_risk,
        "lives_protected": effectiveness['lives_protected'],
        "evacuation_routes_secured": effectiveness.get('evacuation_routes_secured', 0),
        "shelters_ready": effectiveness.get('shelters_ready', 0),
        "effectiveness_score": effectiveness['effectiveness_score']
    }


@app.get("/prevention/suggestions")
async def get_prevention_suggestions(scenario: str = "category_2"):
    """
    Get prevention placement recommendations.
    Returns optimal next prevention action based on risk analysis.
    """
    if not world_service:
        raise HTTPException(status_code=503, detail="World service not initialized")

    prevention, risk_data = _get_prevention()
    if not prevention:
        raise HTTPException(status_code=501, detail="Prevention mode not available")
    if not risk_data or (hasattr(world_service, 'scenario') and not prevention.supports_bundle(world_service.scenario())):
        raise HTTPException(status_code=409, detail=f"No prevention terrain data matches {SCENARIO_ID}")

    # Get bundle and state
    if hasattr(world_service, 'scenario'):
        bundle = world_service.scenario()
    elif hasattr(world_service, '_bundle'):
        bundle = world_service._bundle
    else:
        bundle = risk_data

    raw_snapshot = world_service.snapshot()
    if isinstance(raw_snapshot, dict):
        state = {'tokens': {t.get('id', str(i)): t for i, t in enumerate(raw_snapshot.get('tokens', []))}}
    else:
        state = {'tokens': {}}

    suggestion = prevention.best_prevention_suggestion(bundle, state, risk_data, scenario)

    if suggestion:
        return {
            "has_suggestion": True,
            "suggestion": suggestion,
            "scenario": scenario
        }
    else:
        return {
            "has_suggestion": False,
            "suggestion": None,
            "message": "All prevention measures already in place or no high-impact options available"
        }


@app.post("/prevention/compare")
async def compare_prevention_outcomes(scenario: str = "default"):
    """
    Compare prevention vs no-prevention outcomes.
    Uses Gemini for intelligent analysis when available.
    """
    if not world_service:
        raise HTTPException(status_code=503, detail="World service not initialized")

    prevention, risk_data = _get_prevention()
    if not prevention:
        raise HTTPException(status_code=501, detail="Prevention mode not available")
    if not risk_data or (hasattr(world_service, 'scenario') and not prevention.supports_bundle(world_service.scenario())):
        raise HTTPException(status_code=409, detail=f"No prevention terrain data matches {SCENARIO_ID}")

    # Get bundle and state
    if hasattr(world_service, 'scenario'):
        bundle = world_service.scenario()
    elif hasattr(world_service, '_bundle'):
        bundle = world_service._bundle
    else:
        bundle = risk_data

    raw_snapshot = world_service.snapshot()
    if isinstance(raw_snapshot, dict):
        state = {'tokens': {t.get('id', str(i)): t for i, t in enumerate(raw_snapshot.get('tokens', []))}}
    else:
        state = {'tokens': {}}

    comparison = prevention.compare_outcomes(bundle, state, risk_data, scenario)

    # Numbers come from the model above; Gemini (if configured) only explains them.
    from backend.ai.gemini_adapter import get_gemini
    comparison['ai_analysis'] = await asyncio.to_thread(
        get_gemini().compare_outcomes, comparison['without_prevention'],
        comparison['with_prevention'], comparison.get('prevention_investment', 0))

    return comparison
