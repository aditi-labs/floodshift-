import type {
  ActionType,
  EdgeState,
  ObjectObservation,
  ServiceRoute,
  TokenType,
  WorldSnapshot,
} from "../types/contracts";
import { MOCK_SCENARIO } from "./scenario";

// Scripted three-minute playthrough. Every snapshot below is a hand-authored
// FIXTURE standing in for P4's reducer output; the UI renders them exactly as it
// will render live snapshots. All numbers are invented test quantities, not
// Nepal disaster statistics.

export interface ScriptStep {
  /** Action that advances the script into this step (null for the initial state). */
  expect: { type: ActionType; token_type?: TokenType; site_id?: string } | null;
  label: string;
  snapshot: WorldSnapshot;
  narration: string;
  observation?: Omit<ObjectObservation, "event_id" | "frame_id">;
}

const ALL_EDGES = MOCK_SCENARIO.roads.map((r) => r.id);
const DISASTER_BLOCKS: Record<string, string> = {
  crossing_east_road: "damaged_crossing_model",
  crossing_north_road: "damaged_crossing_model",
  crossing_south_road: "damaged_crossing_model",
  r_esbank_ehub: "illustrative_landslide_mask",
};

function edges(blocks: Record<string, string>): EdgeState[] {
  return ALL_EDGES.map((id) => ({ id, blocked: id in blocks, reason: blocks[id] ?? null }));
}

const { crossing_east_road: _repaired, ...AFTER_BRIDGE_BLOCKS } = DISASTER_BLOCKS;

const EAST_TO_WEST = ["r_ehub_village", "r_ebank_ehub", "crossing_east_road", "r_whub_wbank"];

function routes(reachable: boolean, services: Array<"medical" | "food" | "refuge">): ServiceRoute[] {
  const tail: Record<string, { facility: string; edges: string[] }> = {
    medical: { facility: "field_hospital_1", edges: ["r_whub_med"] },
    food: { facility: "food_station_1", edges: ["r_depot_whub", "r_depot_food"] },
    refuge: { facility: "overnight_shelter_1", edges: ["r_whub_shelter"] },
  };
  return services.map((s) => ({
    population_id: "people_east",
    service: s,
    facility_id: tail[s].facility,
    reachable,
    edge_ids: [...EAST_TO_WEST, ...tail[s].edges],
  }));
}

const ZERO_METRICS = {
  people_reachable_for_medical: 0,
  people_reachable_for_food: 0,
  people_reachable_for_shelter: 0,
  unmet_food_model: 0,
  unmet_medical_model: 0,
  unmet_refuge_model: 0,
  blocked_roads: 0,
};

const BASE: WorldSnapshot = {
  schema_version: 2,
  world_version: 0,
  scenario_id: "nepal_rasuwa_v1",
  phase: "ready",
  simulation_stage: 0,
  branch_id: "main",
  token_inventory: { disaster_start: 1, person: 2, hospital: 1, shelter: 1, food_shelter: 1, bridge: 1 },
  tokens: [],
  facilities: [],
  population_demand: [],
  edges: edges({}),
  metrics: ZERO_METRICS,
  ghost_suggestion: null,
  narration_event: null,
  provenance_label: "Historical map data; intervention outcomes are illustrative",
  service_routes: [],
};

const PERSON = { id: "people_east", households_model: 1, people_model: 8, need_food: 8, need_medical: 2, need_refuge: 8 };

const s0 = BASE;

const s1: WorldSnapshot = {
  ...s0,
  world_version: 1,
  phase: "disaster_active",
  simulation_stage: 1,
  token_inventory: { ...s0.token_inventory, disaster_start: 0 },
  tokens: [{ id: "fiducial-30", type: "disaster_start", board_uv: [0.09, 0.86], site_id: "control_start_pad", vision_source: "replay", status: "accepted" }],
  edges: edges(DISASTER_BLOCKS),
  metrics: { ...ZERO_METRICS, blocked_roads: 4 },
  narration_event: { event_type: "disaster_started", model_only: true },
};

const s2: WorldSnapshot = {
  ...s1,
  world_version: 2,
  token_inventory: { ...s1.token_inventory, person: 1 },
  tokens: [...s1.tokens, { id: "fiducial-31", type: "person", board_uv: [0.84, 0.42], site_id: "people_east", vision_source: "replay", status: "accepted" }],
  population_demand: [PERSON],
  metrics: { ...s1.metrics, unmet_food_model: 8, unmet_medical_model: 2, unmet_refuge_model: 8 },
  narration_event: { event_type: "people_placed", model_only: true },
};

const s3: WorldSnapshot = {
  ...s2,
  world_version: 3,
  token_inventory: { ...s2.token_inventory, hospital: 0 },
  tokens: [...s2.tokens, { id: "fiducial-32", type: "hospital", board_uv: [0.2, 0.58], site_id: "medical_site_west", vision_source: "replay", status: "accepted" }],
  facilities: [{ id: "field_hospital_1", type: "hospital", capacity_model: 12, used_capacity_model: 0, reachable: false, site_id: "medical_site_west" }],
  service_routes: routes(false, ["medical"]),
  narration_event: { event_type: "facility_unreachable", model_only: true },
};

const s4: WorldSnapshot = {
  ...s3,
  world_version: 4,
  token_inventory: { ...s3.token_inventory, food_shelter: 0 },
  tokens: [...s3.tokens, { id: "fiducial-33", type: "food_shelter", board_uv: [0.24, 0.31], site_id: "food_site_west", vision_source: "replay", status: "accepted" }],
  facilities: [...s3.facilities, { id: "food_station_1", type: "food_shelter", capacity_model: 20, used_capacity_model: 0, reachable: false, site_id: "food_site_west" }],
  service_routes: routes(false, ["medical", "food"]),
  narration_event: { event_type: "facility_unreachable", model_only: true },
};

const s5: WorldSnapshot = {
  ...s4,
  world_version: 5,
  token_inventory: { ...s4.token_inventory, shelter: 0 },
  tokens: [...s4.tokens, { id: "fiducial-34", type: "shelter", board_uv: [0.3, 0.72], site_id: "shelter_site_west", vision_source: "replay", status: "accepted" }],
  facilities: [...s4.facilities, { id: "overnight_shelter_1", type: "shelter", capacity_model: 15, used_capacity_model: 0, reachable: false, site_id: "shelter_site_west" }],
  service_routes: routes(false, ["medical", "food", "refuge"]),
  narration_event: { event_type: "facility_unreachable", model_only: true },
};

const s6: WorldSnapshot = {
  ...s5,
  world_version: 6,
  ghost_suggestion: {
    token_type: "bridge",
    site_id: "crossing_east",
    board_uv: [0.495, 0.525],
    reason_code: "improves_multi_service_access",
    preview_edge_ids: EAST_TO_WEST,
  },
  narration_event: { event_type: "ghost_suggested", model_only: true },
};

const s7: WorldSnapshot = {
  ...s6,
  world_version: 7,
  token_inventory: { ...s6.token_inventory, bridge: 0 },
  tokens: [...s6.tokens, { id: "fiducial-35", type: "bridge", board_uv: [0.495, 0.525], site_id: "crossing_east", vision_source: "replay", status: "accepted", rotation_deg: 5 }],
  facilities: [
    { id: "field_hospital_1", type: "hospital", capacity_model: 12, used_capacity_model: 2, reachable: true, site_id: "medical_site_west" },
    { id: "food_station_1", type: "food_shelter", capacity_model: 20, used_capacity_model: 8, reachable: true, site_id: "food_site_west" },
    { id: "overnight_shelter_1", type: "shelter", capacity_model: 15, used_capacity_model: 8, reachable: true, site_id: "shelter_site_west" },
  ],
  edges: edges(AFTER_BRIDGE_BLOCKS),
  service_routes: routes(true, ["medical", "food", "refuge"]),
  metrics: {
    people_reachable_for_medical: 8,
    people_reachable_for_food: 8,
    people_reachable_for_shelter: 8,
    unmet_food_model: 0,
    unmet_medical_model: 0,
    unmet_refuge_model: 0,
    blocked_roads: 3,
  },
  ghost_suggestion: null,
  narration_event: { event_type: "bridge_reconnected", model_only: true },
};

function obs(token_id: string, object_type: TokenType, board_uv: [number, number]): ScriptStep["observation"] {
  return { event_type: "object_observed", token_id, object_type, class_source: "replay", board_uv, vision_status: "confirmed", stable_ms: 850, frame_provenance: "mock:playthrough" };
}

export const SCRIPT: ScriptStep[] = [
  { expect: null, label: "Ready", snapshot: s0, narration: "Ready. Place the START piece on the margin pad to begin the exercise." },
  {
    expect: { type: "place_token", token_type: "disaster_start", site_id: "control_start_pad" },
    label: "Start disaster",
    snapshot: s1,
    narration: "Scenario started. In this model, 4 road links are disrupted, including all three river crossings. Mapped geography is historical; disruption here is illustrative.",
    observation: obs("fiducial-30", "disaster_start", [0.09, 0.86]),
  },
  {
    expect: { type: "place_token", token_type: "person", site_id: "people_east" },
    label: "Place people (east)",
    snapshot: s2,
    narration: "A model household of 8 people in the East village now needs 8 food units, 2 medical slots and 8 refuge spaces.",
    observation: obs("fiducial-31", "person", [0.84, 0.42]),
  },
  {
    expect: { type: "place_token", token_type: "hospital", site_id: "medical_site_west" },
    label: "Field hospital (west)",
    snapshot: s3,
    narration: "Field care is active on the west bank, but the East village cannot reach it: the east crossing is out in this model.",
    observation: obs("fiducial-32", "hospital", [0.2, 0.58]),
  },
  {
    expect: { type: "place_token", token_type: "food_shelter", site_id: "food_site_west" },
    label: "Food station (west)",
    snapshot: s4,
    narration: "The food and water station is linked to the depot, but 8 food units of need on the east bank remain unmet.",
    observation: obs("fiducial-33", "food_shelter", [0.24, 0.31]),
  },
  {
    expect: { type: "place_token", token_type: "shelter", site_id: "shelter_site_west" },
    label: "Shelter (west)",
    snapshot: s5,
    narration: "Overnight shelter has 15 model spaces, yet none are reachable from the East village. All three services are cut off by the river.",
    observation: obs("fiducial-34", "shelter", [0.3, 0.72]),
  },
  {
    expect: { type: "suggest" },
    label: "Suggest bridge",
    snapshot: s6,
    narration: "The planner tested each eligible crossing on a copy of the world. A temporary bridge at the east crossing reconnects all three services. Place the bridge on the glowing outline.",
  },
  {
    expect: { type: "place_token", token_type: "bridge", site_id: "crossing_east" },
    label: "Deploy bridge",
    snapshot: s7,
    narration: "Bridge accepted. In this model the East village now reaches field care, food and refuge: unmet need drops to zero. This is a counterfactual, not a claim about the real event.",
    observation: obs("fiducial-35", "bridge", [0.495, 0.525]),
  },
];

/** Spec §06 fixture shape, kept as the initial snapshot for live-mode fallback. */
export const INITIAL_SNAPSHOT = s0;
