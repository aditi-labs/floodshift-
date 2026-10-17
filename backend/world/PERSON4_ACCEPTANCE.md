# Person 4 acceptance and integration boundary

## Implemented and locally verified

- HOT/HDX source inventory, licensing, dates, hashes and coordinate transform:
  `scenarios/nepal_rasuwa_hot_v1/data/source_manifest.json`.
- Source-derived Nepal world: 16 nodes, 18 edges, three mapped crossings, nine
  approved game pads. All 440 compact/full-graph comparisons pass.
- Shared schematic fixture plus real-map before/after fixtures; documented
  `snapshot()`, `apply(action)`, `suggest(goal)`, `compare(branches)` interfaces.
- Six token rules, explicit rejection reasons, bounded inventory/capacity and
  independent food/medical/refuge demand ledgers.
- Read-only ghost planner and narration tools; deterministic branch rewind,
  comparison, reset and durable SQLite recovery.
- Paired reference SVG exports under the real scenario's `data/` directory;
  same viewBox, physical dimensions, geometry, numbered pads and tolerances.
  Export with `python -m scripts.geodata.export_board`.
- Optional Gemini connector with bounded function calling, sanitized diagnostics,
  state-derived fallback and a separate live acceptance runner. See
  `backend/narration/GEMINI_SETUP.md` for the current live verification record.

## Board handoff

`data/map_print.svg` and `data/map_projection.svg` are reference exports, not
camera-calibrated final artwork. P1/P2 can adopt them in their `visual_assets/`
folder without changing the transform. Both use `viewBox="0 0 1000 1000"` and
`x=1000*u`, `y=1000*v`, top-left origin. Do not crop or stretch independently.
420 × 420 mm remains provisional. Pad radius is 0.025 UV (10.5 mm at that size);
physical footprint, token centre detection and registration must be checked.
The opaque lower-right START panel deliberately masks geographical context.
No ArUco IDs or camera geometry are invented by this exporter.

Judges choose among the legal numbered pads, including three crossing options
and two household positions. They cannot place pieces at arbitrary map locations
and expect the reducer to accept them. Household demand and service sites are
hypothetical game presets. A restored crossing serves model needs; it is not an
engineering claim about a real bridge or a claim of actual lives saved.

## Team integration still required

- **P3:** select the HOT bundle, agree shared Pydantic schemas with these fixtures,
  expose the service/narration endpoints, fuse observations and broadcast snapshots.
- **P2:** render the chosen scenario's authoritative snapshot/route polylines and
  Gemini LIVE/TEXT mode; verify projection against the same UV frame.
- **P1/P2/P3:** finalize board size, print scale, token footprints, fiducials and
  camera/projector registration, then rehearse physical placements and reset.
- **P4 after integration:** fix any simulation/tolerance issues demonstrated by
  those tests. No physical end-to-end pass is claimed by unit or SDK tests.

The default `WorldService()` remains schematic for compatibility; the integrated
server must explicitly choose `scenarios/nepal_rasuwa_hot_v1`. The shared schema
handoff is proposed/documented, not claimed agreed without P3 confirmation.
Tiger Data, live voice, physical time dial and additional maps remain optional,
behind the master document's core physical-demo gate. Local persistence is ready.
