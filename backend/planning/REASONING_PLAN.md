# Reasoning branch implementation plan

Scope: Person 4 simulation, planning, scenario data and explanation records.
Branch: reasoning, based on main's real-service integration. Do not push main.

## First version (defaults pending operator answers)

- A person token is a stable population group with an integer model size.
- Groups move between approved population pads; observation validation remains P3.
- Authored flood stages close explicit mapped edges; no image-derived flood claim.
- Shelter evacuation is separate from existing food/medical/refuge service metrics.
- A group stays together. Optimize the total number of people assigned, then
  minimize crowding, then modeled person-travel time with deterministic tie breaks.
- Enumerate a bounded set of mapped candidate paths per group and shelter, then
  jointly search group assignments. Report candidate/search limits honestly;
  never claim a global optimum over routes not enumerated.
- Capacity is a conservative simultaneous planning-wave reservation, shared in
  both directions on a road and at junctions. No invented departure schedule or
  physical pedestrian-flow calibration. Unassigned groups remain explicitly listed.
- Road and node capacities are authored assumptions, not measured map attributes.
- An opt-in Nepal reasoning bundle leaves the current demo and API default intact.

## Implementation sequence

1. Add pure deterministic capacity-aware planner and factual explanation records.
2. Add opt-in population sizing/movement semantics and snapshot decision output.
3. Persist accepted decisions atomically with existing versioned world events;
   expose read-only history and speech-ready summaries for future ElevenLabs.
4. Build a reproducible Nepal scenario with multiple pads, capacities and authored
   closures. Preserve source edge IDs, polylines and provenance.
5. Validate bottlenecks, alternate paths, group conservation, node/road/shelter
   limits, state changes, disconnected routes and replay. Compare a tiny problem
   to exhaustive reference search, and report measured demo latency.
6. Document P3/P2 integration fields without editing their endpoints or frontend.

## Accuracy boundary

A routing algorithm is validated against the graph and declared constraints; no
ML training is implied. Geographic continuity can be checked from mapped source
geometry. Real flood extent, structural safety, road widths, walking speeds and
shelter suitability need independent data and validation. The saved explanation
contains decision evidence, alternatives and limitations, not hidden AI reasoning.

## Acceptance

No routed group crosses a closed edge, exceeds any modeled reservation capacity,
or disappears from accounting. Changing group position/size or flood stage
recomputes a deterministic plan. Failed/rejected actions save no decision. Stored
plans survive restart and remain tied to their original branch and world version.
Narration describes those saved facts and cannot mutate the world.
