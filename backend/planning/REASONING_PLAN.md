# Reasoning branch — implemented design and handoff

Owner: Person 4. Branch: `reasoning`. The current `main` prevention-mode changes
were merged on 2026-10-17; this feature does not change their API or frontend.

## Accepted user choices

- Each person piece represents a large group with **no specified headcount**.
- Groups may split across routes; results are fractions/percentages of a group.
- Pieces can move anywhere near mapped roads; the reducer snaps to the actual
  road polyline within 0.015 board UV (36 model metres in this 2.4 km frame).
- Show the preferred open route and alternatives, including food/medical stops
  where an open path can be found. Avoid modeled flood closures.
- Save the decision facts and an explanation for a future ElevenLabs integration.

## Implemented

1. Stable group identity through placement, movement and removal. Multiple groups
   can share an origin. The demo permits four pieces; inventory is configurable
   up to six. A token off the road tolerance is rejected atomically.
2. Exact polyline snapping and virtual graph vertices. Subdivided edges preserve
   road bends and proportional travel cost. All parts share the original road's
   capacity; splitting an edge does not manufacture extra capacity.
3. Candidate routes via NetworkX and joint fractional linear programming via
   SciPy/HiGHS. The lexicographic objective is:
   - maximize assigned group fractions;
   - maximize the minimum assigned share among reachable groups;
   - minimize peak road/junction/shelter utilization;
   - minimize modeled group-weighted travel time.
4. At most 16 shortest simple paths per shelter in the supplied scenario. The
   report says when candidates are truncated. Optimality is **among candidates**,
   not a claim of the best route over every possible network walk.
5. Shared road capacity covers both directions. Node and shelter capacities are
   also enforced. These are conservative planning-wave reservations, not a
   pedestrian dynamics or departure-time simulation. Unassigned groups stay
   explicit; their real waiting conditions are unknown.
6. A shortest open route ignoring other groups is returned separately from the
   joint allocation. Food/medical alternatives identify the stop and available
   residual route capacity. They do not promise treatment or supplies. The
   bounded search may omit a feasible service detour, especially one requiring
   revisiting a road; it does not claim that no such walk exists.
7. Every accepted action stores its decision with its event. The decision has a
   content-derived ID, world version, branch, algorithm version, bundle fingerprint,
   closure IDs, capacities/loads, routes, alternatives and explanation. SQLite
   commit precedes acceptance; replay and restart validate the same decisions.
8. `speech_payload(decision)` returns text plus factual evidence tied to that
   decision ID. ElevenLabs is **not connected**. Gemini has the additional read-only
   `get_population_routing` tool; the optimizer does not depend on Gemini.

## Flood source and accuracy

The opt-in `nepal_rasuwa_reasoning_v1` bundle retains exactly the HOT-derived
road geometry. Small Copernicus CEMS-GloFAS v2.1.2 windows supply RP10/RP100 modeled
river-flood footprints at approximately 90 m resolution. The clipped files,
checksums, CRS, transform, source URLs, license and quality mask are committed.

**82 of 90 wet pixels in the downloaded window are quality-flagged for potentially
spurious depths.** These footprints are an explicitly unvalidated educational
hazard scenario, not verified local flood depths or an evacuation safety map.
No-data is not proof of dry ground. Return periods are alternative statistical
scenarios, not time steps of an observed flood; both happen to close the same
13 of 18 compacted edges here. Any positive-depth intersection conservatively
closes the whole compacted edge. Bridge tokens cannot override flood closures.
Exposed facility sites are rejected/excluded.

Road, junction and shelter capacities remain authored group-equivalent assumptions.
No population counts, pedestrian widths, calibrated crowd behavior, historical
casualties or real lives saved are inferred. Optimization is tested software;
no ML training or physical safety certification is claimed.

## Use the module

```sh
python -m pip install -r backend/world/requirements.txt
python -m backend.world.reasoning_demo \
  --session /tmp/reasoning-demo.sqlite3 --output /tmp/reasoning-report.json
python -m backend.world.reasoning_demo \
  --session /tmp/reasoning-demo.sqlite3 --output /tmp/reasoning-recovered.json
python -m pytest tests/test_world_reasoning.py
```

Use a new session path after intentionally changing the scenario or algorithm;
old incompatible sessions fail explicitly instead of silently resetting.

```python
from backend.world import WorldService
from backend.narration.decision_narration import speech_payload

world = WorldService.open_session(
    '/tmp/reasoning-session.sqlite3', 'scenarios/nepal_rasuwa_reasoning_v1')
# START and shelter actions first, using the scenario's fixed service sites.
result = world.apply({
    'action_id': 'population-1', 'type': 'place_token', 'token_type': 'person',
    'token_id': 'group-one', 'source': 'manual',
    'board_uv': [0.28046914, 0.49744044],
    'expected_world_version': world.snapshot()['world_version'],
})
plan = world.snapshot()['routing_decision']
history = world.decision_log()
voice_request = speech_payload(plan)
```

No site ID is required for a reasoning-mode person action. Fixed service pieces
still use approved sites. Rejected actions produce no decision-history entry.

## P3/P2 integration required (outside this lane)

- P3 must explicitly select this bundle. `WorldService()` stays schematic.
- Preserve `routing_decision`, `routing_nodes`, `population_unit` and token
  `road_snap` in the API/WebSocket schemas and serializer. The existing converter
  currently drops these fields. Do not call it a finished physical UI integration.
- P3's observation adapter must pass stable person token IDs and board UV directly
  for free-road snapping instead of requiring a population-pad match.
- P2 renders each group's allocated route polylines and percentages, preferred
  route, optional service alternatives, remaining unassigned fraction and warnings.
- Reasoning-mode `population_demand.headcount_known` is false. Legacy numeric
  people/need fields are compatibility placeholders, **not measured zeros**; do
  not display them as population outcomes. Use the group-routing fields.
- Serve the reasoning bundle's flood footprint and transform, not the separate
  schematic prevention `risk.json` circles or population/lives-saved estimates.
  The new prevention/Gemini code from main remains unchanged and separately owned.
- P1/P3 must confirm distinct piece IDs and detector count for four population
  tokens; P1/P2/P3 still verify physical registration and movement latency.

## Reproduce data and inspect evidence

```sh
python -m pip install -r scripts/geodata/requirements.txt
python -m scripts.geodata.download_flood --output /tmp/floodshift-flood
python -m scripts.geodata.build_reasoning_scenario
python -m scripts.geodata.import_flood --raw /tmp/floodshift-flood
python -m scripts.geodata.build_reasoning_scenario
python -m scripts.geodata.render_reasoning \
  /tmp/reasoning-report.json scenarios/nepal_rasuwa_reasoning_v1/data/reasoning_preview.png
```

`data/decision_example.json` is a saved representative decision. The preview shows
three routed groups, one isolated group, and a 50/50 split between shelters.
The measured local demo's accepted actions took about 16–79 ms before the latest
main merge; camera, network and projection latency are not included.

Tests cover analytic capacity cuts, group conservation/fair sharing, route splits,
road/node/shelter limits, exposed sites, curved snapping, movement, removal,
read-only narration, disk failure, branch rewind, immutable history and restart.
The original source graph's 440 topology comparisons remain in the full suite.

Sources: [Copernicus dataset README](https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard/README.txt),
[license](https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard/copyright.txt),
[SciPy linear programming](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html).
