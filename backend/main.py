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

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.contracts import (
    WorldSnapshot, WorldAction, ActionResult, ActionType, TokenState,
    WorldMetrics, GhostSuggestion, EdgeState, Phase, TokenType, VisionSource,
    HealthResponse, SuggestRequest, NarrateRequest, NarrateResponse,
    BranchSaveRequest, BranchLoadRequest, WSEvent
)

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

def _dict_to_world_snapshot(data: dict) -> WorldSnapshot:
    """Convert P4's snapshot dict to WorldSnapshot Pydantic model."""
    # Convert tokens list
    tokens = []
    for t in data.get('tokens', []):
        tokens.append(TokenState(
            id=t.get('id', ''),
            type=TokenType(t.get('type', 'bridge')) if t.get('type') else TokenType.BRIDGE,
            board_uv=tuple(t.get('board_uv', (0.5, 0.5))),
            site_id=t.get('site_id'),
            vision_source=VisionSource(t.get('vision_source', 'manual')) if t.get('vision_source') else VisionSource.MANUAL,
            status=t.get('status', 'accepted')
        ))

    # Convert metrics
    metrics_data = data.get('metrics', {})
    metrics = WorldMetrics(
        people_reachable_for_medical=metrics_data.get('people_reachable_for_medical', 0),
        people_reachable_for_food=metrics_data.get('people_reachable_for_food', 0),
        people_reachable_for_shelter=metrics_data.get('people_reachable_for_shelter', 0),
        unmet_food_model=metrics_data.get('unmet_food_model', 0),
        unmet_medical_model=metrics_data.get('unmet_medical_model', 0),
        unmet_refuge_model=metrics_data.get('unmet_refuge_model', 0),
        blocked_roads=metrics_data.get('blocked_roads', 0)
    )

    # Convert edges
    edges = []
    for e in data.get('edges', []):
        edges.append(EdgeState(
            id=e.get('id', ''),
            blocked=e.get('blocked', False),
            reason=e.get('reason')
        ))

    # Convert ghost suggestion
    ghost = None
    ghost_data = data.get('ghost_suggestion')
    if ghost_data and isinstance(ghost_data, dict):
        ghost = GhostSuggestion(
            token_type=TokenType(ghost_data.get('token_type', 'bridge')),
            site_id=ghost_data.get('site_id', ''),
            board_uv=tuple(ghost_data.get('board_uv', (0.5, 0.5))),
            reason_code=ghost_data.get('reason_code', 'suggested')
        )

    # Convert phase - handle string or enum
    phase_val = data.get('phase', 'ready')
    if isinstance(phase_val, str):
        phase = Phase(phase_val) if phase_val in [p.value for p in Phase] else Phase.READY
    else:
        phase = phase_val

    return WorldSnapshot(
        schema_version=data.get('schema_version', 2),
        world_version=data.get('world_version', 1),
        scenario_id=data.get('scenario_id', 'default'),
        phase=phase,
        simulation_stage=data.get('simulation_stage', 0),
        branch_id=data.get('branch_id', 'main'),
        token_inventory=data.get('token_inventory', {}),
        tokens=tokens,
        facilities=[],  # P4 may compute these differently
        population_demand=[],  # P4 may compute these differently
        edges=edges,
        metrics=metrics,
        ghost_suggestion=ghost,
        narration_event=None,
        provenance_label=data.get('provenance_label', 'Educational scenario')
    )


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
    world_service = WorldService()
    service_type = "MockWorldService" if USE_MOCK else "WorldService"
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

    raw_snapshot = world_service.snapshot()
    ws_seq += 1

    # Convert to Pydantic if needed
    if isinstance(raw_snapshot, dict):
        snapshot = _dict_to_world_snapshot(raw_snapshot)
    else:
        snapshot = raw_snapshot

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
    return HealthResponse(
        status="ok",
        world_version=version,
        vision_mode="mock" if USE_MOCK else "live",
        perceptron_status="not_connected",
        gemini_status="not_connected"
    )


@app.get("/world", response_model=WorldSnapshot)
async def get_world():
    """Get current world state."""
    if not world_service:
        raise HTTPException(status_code=503, detail="World service not initialized")
    raw_snapshot = world_service.snapshot()
    if isinstance(raw_snapshot, dict):
        return _dict_to_world_snapshot(raw_snapshot)
    return raw_snapshot


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

    # P4's suggest takes goal parameter (default 'needs_served')
    goal = request.goal_id or 'needs_served'
    suggestion = world_service.suggest(goal)

    raw_snapshot = world_service.snapshot()
    world_version = raw_snapshot.get('world_version', 1) if isinstance(raw_snapshot, dict) else raw_snapshot.world_version

    if suggestion:
        # P4 returns dict, convert if needed
        suggestion_data = suggestion if isinstance(suggestion, dict) else suggestion.model_dump()
        return {
            "has_suggestion": True,
            "suggestion": suggestion_data,
            "world_version": world_version
        }
    else:
        return {
            "has_suggestion": False,
            "suggestion": None,
            "world_version": world_version
        }


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
        world_service.apply(action)

    await broadcast_snapshot()

    raw_snapshot = world_service.snapshot()
    new_version = raw_snapshot.get('world_version', 1) if isinstance(raw_snapshot, dict) else raw_snapshot.world_version
    return {"reset": True, "world_version": new_version}


@app.post("/narrate", response_model=NarrateResponse)
async def narrate(request: NarrateRequest):
    """
    Get AI narration for current state.
    Uses Gemini with read-only world tools (P4 implements tools).
    For now returns mock response.
    """
    if not world_service:
        raise HTTPException(status_code=503, detail="World service not initialized")

    raw_snapshot = world_service.snapshot()
    if isinstance(raw_snapshot, dict):
        snapshot = _dict_to_world_snapshot(raw_snapshot)
    else:
        snapshot = raw_snapshot

    # Mock narration - P4 will implement real Gemini integration
    blocked_count = snapshot.metrics.blocked_roads
    phase = snapshot.phase

    if "cut off" in request.question.lower() or "reach" in request.question.lower():
        if blocked_count > 0:
            answer = "The eastern village is currently cut off due to a damaged bridge crossing. A temporary bridge could restore access for food, medical, and shelter services."
        else:
            answer = "All communities are currently accessible via the road network."
    elif "bridge" in request.question.lower():
        suggestion = world_service.suggest('needs_served')
        site_id = suggestion.get('site_id') if isinstance(suggestion, dict) else (suggestion.site_id if suggestion else None)
        if site_id:
            answer = f"I recommend placing a temporary bridge at {site_id}. This would restore multi-service access to isolated communities."
        else:
            answer = "No bridge placement is currently needed - all crossings are operational."
    else:
        answer = f"The scenario is in '{phase.value}' phase with {blocked_count} blocked road(s). This is an educational simulation based on HOT Nepal 2026 mapping data."

    return NarrateResponse(
        answer=answer,
        grounded_in_version=snapshot.world_version
    )


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
            raw_snapshot = world_service.snapshot()
            if isinstance(raw_snapshot, dict):
                snapshot = _dict_to_world_snapshot(raw_snapshot)
            else:
                snapshot = raw_snapshot
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
