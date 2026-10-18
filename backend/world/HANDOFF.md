# Person 4 — World/data handoff

Owner for this workspace: **Person 4 only**, per `FLOODSHIFT_MASTER_BUILD_SPEC_V2.md`.
Work on Git branch **eashan**; pull before every push; never push to main.
Simulation `branch_id="main"` is an in-memory counterfactual label, unrelated to Git.

After merging P3's API foundation, `contracts/fixture_mock_world.json` preserves
the mock API's ready-state reset fixture. `contracts/fixture_world.json` remains
P4's authoritative staged demo. The API still selects MockWorldService until P3
wires the real service; merging code does not itself complete that integration.

## Run without hardware or servers

From repository root, Python 3.11+:

```sh
python -m pip install -r backend/world/requirements.txt
python -m pytest tests/test_world_*.py
python -m backend.world.demo
```

`python -m backend.world.demo --write-fixtures` regenerates the authoritative
`contracts/fixture_world.json`, `data/fixture_after_bridge.json`, and
`data/demo_actions.json` under `scenarios/nepal_rasuwa_v1/`.
The fixture is version 5, with START, east demand and three west services staged.
The sixth action deploys the bridge. These numbers are computed from the bundle.

## Person 3 integration

```python
from backend.world import WorldService

world = WorldService.from_bundle("scenarios/nepal_rasuwa_v1")
snapshot = world.snapshot()
result = world.apply({
    "action_id": "start-1", "type": "place_token", "source": "manual",
    "token_id": "start-token", "token_type": "disaster_start",
    "site_id": "start_pad", "board_uv": [0.08, 0.9],
    "expected_world_version": snapshot["world_version"],
})
assert result["accepted"]
```

- `snapshot() -> dict`: detached schema-v2 snapshot, including graph edges, routes,
  inventory, budget, computed facilities/demand/metrics and current ghost suggestion.
- `apply(dict | Pydantic model) -> dict`: `{accepted, reason, world_version, snapshot}`.
  Rejection is atomic and carries an explicit machine-readable reason. Version
  increments once for accepted mutations. Duplicate committed action IDs remain
  rejected across reset, preventing delayed camera events from replaying.
- `suggest(goal="needs_served") -> dict | None`: goals `needs_served`, `food`,
  `medical`, `refuge`. Read-only; no version increment or resource spend.
- `compare([branch_a, branch_b, ...]) -> dict`: stored branch metrics and deltas
  relative to the first branch. Unknown IDs raise `ValueError`.
- `scenario() -> dict`: detached bundle, including approved site geometry.
- `get_route_status(source_id, destination_id)`, `get_eligible_interventions()`
  and `event_log()` return detached, read-only data.

P3 retains ownership of API routes, Pydantic schemas, observation fusion and sockets.
Pass only confirmed perception actions as `source="physical_perceptron"`; the world
checks game constraints, not the authenticity of that source label. Manual fallback
is `manual`; recorded replay is `replay`. Physical/replay placements require
`token_id`; manual placement may omit it, yielding `manual:<site_id>`.
P3 should broadcast the returned snapshot after accepted mutations. The service
serializes commits with a lock, but gateway broadcast ordering is P3's responsibility.

## UI-facing additions (v2.2)

- The API server loads `scenarios/nepal_rasuwa_hot_v1` (override `FLOODSHIFT_SCENARIO`;
  durable session with `FLOODSHIFT_SESSION=/path/outside/repo/session.sqlite3`).
- `ghost_suggestion` is `None` until `request_suggestion(goal)` (POST `/plan/suggest`)
  records a versioned `suggest` event; placing a bridge or reset clears it. `suggest()`
  stays read-only. Suggestions include `preview_edge_ids` (restored route via the crossing).
- `save_branch(name)` / `load_branch(name)` are immutable bookmarks (logged actions, so they
  survive session replay); `compare([a, b])` prefers bookmarks and lists placed pieces.
- Snapshots add `service_routes` (nearest reachable service per need; when cut, the path
  that would work with closures open) and per-node `unmet_food|medical|refuge`.
- `scenario_geometry()` serves `GET /scenario`: roads (ids = edge ids), sites with labels
  and tolerances, rivers, settlement labels, flood footprints, `aspect_ratio`.

## Camera path (v2.4)

- `reduce_action` resolves `site_id` from `board_uv` when the action has none: nearest
  approved pad of the piece's kind within that pad's `tolerance_uv`, else `outside_site`.
- `POST /perception/observe` (gateway) accepts an `ObjectObservation`, broadcasts it as
  `vision.status`, builds the `WorldAction` with the current version under the lock, and
  broadcasts the snapshot. `class_source` maps to action source: `perceptron` →
  `physical_perceptron`, `local_cv` → `physical_local_cv` (token `vision_source` keeps it).
- `scripts/run_live_demo.py` watches only the board (`backend/perception/board_watcher.py`):
  after ArUco calibration it captures a reference of the empty board; candidates are
  bridge-rule hits inside the board quad plus area-bounded change against the reference.
  Each piece is classified once. Press R after a lighting change, C to recalibrate.
- Colour filter (default on, `COLOR_FILTER=off` in `.env` disables): change candidates must lie
  inside the yellow mask from `bridge_profile.json`, so shadows, hands and the projected overlay
  never become tracks or Perceptron calls. Pieces printed in another colour are ignored while it is
  on. Y toggles it live, V shows the filtered feed (non-yellow dimmed) in the debug window.
- Printed-bridge recognition: `scripts/run_live_demo.py` uses
  `PerceptronAdapter.classify_frame`, which calls Perceptron when `PERCEPTRON_API_KEY` and
  the `perceptron` SDK exist, cross-checks bridge boxes with
  `backend/perception/bridge_detector.py`, and otherwise classifies **only the bridge** with
  that local colour+shape rule (shown as `LOCAL_CV`). Re-fit after new photos:
  `python scripts/calibrate_bridge_detector.py hardware/tokens/bridge/photo_top.jpg new1.jpg ...`

## Person 2 integration

Use `contracts/fixture_world.json` and `data/fixture_after_bridge.json` to show before/
after. Render authoritative metrics; do not calculate world outcomes in the browser.
`data/roads.json` supplies normalized road geometry, `data/sites.json` supplies pad
positions/tolerances. All board UV coordinates use the upper-left origin.
The default data badge must be **SCHEMATIC**. No projection or UI files are changed
by Person 4. The additive `routes`, `budget_remaining_model`, `snapshot_id` and
`data_mode` fields are proposed for P3's schema integration; schema v2's named
fields and token vocabulary are preserved.

## Rules and deliberate choices

- START latches the scenario at stage 1; moving/removing START is rejected. Reset
  is the only way to restart. Reset advances world_version instead of reusing it.
- People use fixed illustrative per-site needs. One token per site. Services have
  finite independent capacities. Deterministic allocation processes population
  sites by ID, then reachable services by route cost and facility ID.
- `people_reachable_for_*` counts geographic access before capacity limits;
  `unmet_*_model` is the capacity-bounded ledger. Do not equate these metrics.
- Food requires a route from the depot at placement; if a later stage cuts supply,
  it stays placed but inactive. Shelter and medical sites reject hazard exposure.
- Bridges restore only their approved edge. Planner score = 10 × selected unmet
  need reduction − cost; zero-gain candidates are listed but never recommended.
- Moving/removing a resource refunds its deployment cost and inventory in this
  educational sandbox. Removal of a bridge reinstates the current stage's block.
  This explicit reversible policy avoids stranded inventory during physical play.
- `advance_stage` follows preset disruption lists; it is not hydrological prediction.
- `branch` action accepts `branch_id` and optional `from_snapshot_id` (default
  current snapshot), creates a new branch and switches to it. Old branch heads
  remain immutable; rewind by creating a new branch from a saved snapshot ID.
  All actions still use a global increasing world version to reject stale input.
- The default service keeps events/snapshots in memory. `WorldService.open_session`
  adds durable SQLite checkpoints and verified restart recovery; see
  [SESSION_HANDOFF.md](SESSION_HANDOFF.md). Export `event_log()` for deterministic replay.

## Read-only narration

`backend.narration.tools.WorldTools(world)` provides the seven read-only tools in
the specification, with an explicit dispatch allowlist. `narration_fallback.narrate`
uses one current snapshot and labels outcomes illustrative. The optional
`GeminiNarrator` adapter is now implemented with read-only function calling and
TEXT fallback; see [SESSION_HANDOFF.md](SESSION_HANDOFF.md). Live API tools have been verified across runs; the latest complete smoke run
was quota-limited. See `backend/narration/LIVE_VERIFICATION.md`. No key or cloud SDK is needed for offline mode.

## Data status and reproduction

The default runtime graph is deliberately synthetic. Its sites are **not** aligned
to the real HOT context export and must never be overlaid on it as approved sites.

The public HDX API supplied the real **NPL_CORRIDOR** resource inventory after the
HDX webpage failed. Download and preprocessing are offline operations:

```sh
python -m pip install -r scripts/geodata/requirements.txt
python scripts/geodata/download_hot.py --output /tmp/floodshift-hot
python scripts/geodata/import_hot.py --raw /tmp/floodshift-hot \
  --output scenarios/nepal_rasuwa_v1/data/hot_context \
  --settlement-id node/14127413536
```

The selected anchor is an actual Rasuwa settlement record (`स्याफ्रु बेसी`), with a
1,200 m radius square in its estimated UTM CRS. Exported context contains roads,
bridges, waterways and settlements in one UV frame; the manifest records source
URLs, SHA-256 hashes, licenses, resource dates, fields, geometry counts and bounds.
Raw downloads stay outside Git. Retain `© OpenStreetMap contributors` attribution
and the recorded ODbL source license when displaying or redistributing this data.

**HOT milestone now available:** `scenarios/nepal_rasuwa_hot_v1` is an explicit
opt-in bundle with source-matched crossings, compacted mapped roads and passing
causal tests. See [HOT_HANDOFF.md](HOT_HANDOFF.md) for the exact load path, fixtures,
board frame, validation evidence and remaining integration work. The schematic
default and shared fixture remain stable for P2/P3's existing work.
Source mapped status never establishes route safety,
facility operability, local demand or damage prediction. Live Gemini and optional
Tiger Data remain behind core integration. P1 owns print artwork/attribution docs;
P2 owns rendering; P3 owns the integrated server. No work in those lanes is included.
