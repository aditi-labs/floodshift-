# Person 4 — HOT-derived scenario ready for integration

## Use the real-map bundle explicitly

```python
from backend.world import WorldService
world = WorldService.from_bundle("scenarios/nepal_rasuwa_hot_v1")
```

```sh
python -m backend.world.demo --bundle scenarios/nepal_rasuwa_hot_v1
python -m pytest tests/test_world_*.py
```

P3 selects this bundle in the gateway; P2 selects its matching data and fixture.
`WorldService()` and `contracts/fixture_world.json` still use the earlier schematic
bundle, so this branch does not silently relocate another owner's UI or calibration.
No API, perception, calibration, frontend or print-asset files were edited.

## Matching data for P2/P3/P1

Everything below lives in `scenarios/nepal_rasuwa_hot_v1/data/`:

| File | Use |
| --- | --- |
| `fixture_world.json` | Five tokens staged, three crossings closed, bridge suggested |
| `fixture_after_bridge.json` | Sixth token accepted; all three model needs served |
| `demo_actions.json` | Replay through the same service; source is honestly `manual` |
| `roads.json` | 16 nodes, 18 compacted road edges with full mapped polylines |
| `sites.json` | Nine distinct interaction pads, tolerances and source references |
| `roads_board.json`, `waterways_board.json`, `bridges_board.json`, `settlements_board.json` | Mapped visual context in the same board UV frame |
| `source_manifest.json` | Original URLs/hashes/license, coordinate transform, topology proof and modeling assumptions |
| `map_print.svg`, `map_projection.svg` | Paired reference exports; same viewBox and approved numbered pads; physical calibration pending |
| `validation_map.png` | Before/after QA figure; not calibrated projector or print artwork |

Display **DATA=HOT_DERIVED**, with the snapshot's provenance label. The map uses
one **square** UV frame for a 2,400 × 2,400 metre projected AOI in EPSG:32645.
The `420 × 420 mm` board dimensions are provisional. P1/P2/P3 must agree on physical
dimensions and use this square frame together; do not stretch it to the old A3
schematic frame. Padding a square map on rectangular paper is fine if every overlay
and calibration uses the same padding transform. No manual dataset download is needed.

Reserve `board.control_inset_uv=[0.84,0.84,1,1]` as an opaque off-geography control
panel containing START. Mask map context in that rectangle so START is not shown
as a token placed in the real river. All simulation roads and other pads stay outside it.

Board-space files deliberately say `coordinate_space=board_uv`; they are not
WGS84 GeoJSON for GIS ingestion. Source longitude/latitude bounds and the projected
transform remain in the manifest. Restore WGS84 via that transform if needed.

`routes[].board_uv` follows each mapped road bend, including when traveling in
reverse. Do not redraw straight segments from the simplified `path` node IDs.

## Source-derived crossing and game logic

The primary suggestion is `crossing_east`, matched to **OSM way/83925870** by
identical way ID and bridge/road endpoint geometry. It is between the two mapped
Shyaphru settlement areas. The pad is at approximately `[0.500421, 0.440124]`.
The two alternative pads match `way/1017959928` and `way/83925838`.

Source records label these bridges `Destroyed`; this is preserved as mapped
metadata, not asserted as present-day engineering truth. Our educational preset
closes all three selected crossings. One temporary crossing restores service
access; either alternative alone does not. The source network includes roads,
paths and steps and is modeled as undirected mixed ground access. **It is not a
validated motor-vehicle or emergency route network.**

The source settlements are `node/14127413536` (Shyaphru Bensi) and `node/267564991`
(Shyaphru). Demand pads use nearby mapped road vertices; the audited offsets from
the settlement label points are about 6.1 m and 18.5 m. These are explicit game
placement associations, not new road connectors or observations of residents.
All people counts, service capacities, site approvals, closures and model travel
costs remain authored educational assumptions. Facilities are hypothetical field
care, food/water and refuge pads; no claim of existing hospitals or safe sites.

## Validation evidence

- Imported graph: 1,794 vertices and 1,810 source segments; disconnected components
  remain disconnected. No proximity links or planar crossing intersections added.
- All three selected bridges match source geometry and connect source vertices.
- Degree-two chains are compacted while retaining every road bend and segment ID.
- All eight crossing-open/closed combinations match the full imported network
  for all 55 retained terminal pairs: **440 comparisons**, with shortest mapped
  lengths preserved within 1 cm. This validates graph reduction, not real access.
- Interaction tolerance circles do not overlap in the square board frame.
- START → household → care/food/refuge → suggested bridge works in both bundles.
  Unmet model units change from **food 8 / medical 2 / refuge 8** to **0 / 0 / 0**.
- Tests cover capacity limits, replay, alternative crossings, source traceability,
  deterministic rebuilds, curved/reversed route geometry and rejection of a
  mismatched source bridge before scenario export.

## Reproduce offline

```sh
python -m scripts.geodata.build_hot_scenario
python -m backend.world.demo --bundle scenarios/nepal_rasuwa_hot_v1 --write-fixtures
python -m scripts.geodata.render_validation
python -m scripts.geodata.export_board
```

The builder needs NetworkX only; it consumes the committed, audited context under
`scenarios/nepal_rasuwa_v1/data/hot_context`. Re-fetching raw HOT files is optional
and should happen only with an intentional source-version update. The plotting
command additionally needs Matplotlib (`pip install matplotlib`). Raw downloads
remain outside the repository. Retain **© OpenStreetMap contributors · HOT / HDX ·
ODbL** on displayed/printed map derivatives; original resource URLs are recorded
in the source manifest.

## Next integration boundary

P3 can load this service bundle and broadcast returned snapshots; P2 can render
the matching fixture and curved routes; P1 can adopt the paired reference SVGs for square-frame print artwork.
Those remain their owned tasks. Physical token fit and camera/projector alignment
require their hardware measurements. P4 can adjust tolerances when those arrive.
Durable local sessions and the optional Gemini adapter are now implemented; see
[SESSION_HANDOFF.md](SESSION_HANDOFF.md). Live Gemini tools have been verified across runs; the latest full test was
quota-limited (see `backend/narration/LIVE_VERIFICATION.md`). Tiger Data remains optional and unimplemented. Offline world
simulation requires no cloud keys or hardware.

See [PERSON4_ACCEPTANCE.md](PERSON4_ACCEPTANCE.md) for the complete module checklist and remaining integration boundaries.
