// Mirror of the frozen shared contracts in docs/MASTER.md §06 (schema_version 2).
// Authoritative schemas live in backend/contracts.py (P3 + P4). If a field changes
// there, change it here in the same PR and bump SCHEMA_VERSION.
//
// Fields marked `PROPOSED (P2)` are not yet in the master spec's snapshot example;
// they are optional so the UI still renders a snapshot that omits them. See the
// "P2 proposed snapshot extensions" note in the master spec change log.

export const SCHEMA_VERSION = 2;

export type TokenType =
  | "hospital"
  | "shelter"
  | "food_shelter"
  | "bridge"
  | "disaster_start"
  | "person"
  | "truck"
  | "helicopter"
  | "time_dial";

export const CORE_TOKENS = [
  "disaster_start",
  "person",
  "hospital",
  "shelter",
  "food_shelter",
  "bridge",
] as const satisfies readonly TokenType[];

export type SiteKind =
  | "medical_site"
  | "shelter_site"
  | "food_site"
  | "bridge_crossing"
  | "control_start_pad"
  | "population_node";

export type Phase = "ready" | "disaster_active";

export type UV = [number, number];

export type VisionSource = "perceptron" | "replay" | "manual";
export type TokenStatus = "accepted" | "unconfirmed" | "rejected";

export interface PlacedToken {
  id: string;
  type: TokenType;
  board_uv: UV;
  site_id: string | null;
  vision_source: VisionSource;
  status: TokenStatus;
  rotation_deg?: number;
}

export interface Facility {
  id: string;
  type: "hospital" | "food_shelter" | "shelter";
  capacity_model: number;
  used_capacity_model: number;
  reachable: boolean;
  /** PROPOSED (P2): which site the facility sits on, for icon placement. */
  site_id?: string;
}

export interface PopulationDemand {
  id: string;
  households_model: number;
  people_model: number;
  need_food: number;
  need_medical: number;
  need_refuge: number;
}

export interface EdgeState {
  id: string;
  blocked: boolean;
  reason: string | null;
}

export interface Metrics {
  people_reachable_for_medical: number;
  people_reachable_for_food: number;
  people_reachable_for_shelter: number;
  unmet_food_model: number;
  unmet_medical_model: number;
  unmet_refuge_model: number;
  blocked_roads: number;
}

export interface GhostSuggestion {
  token_type: TokenType;
  site_id: string;
  board_uv: UV;
  reason_code: string;
  /** PROPOSED (P2): edge ids of the preview route to draw as a cyan dashed line. */
  preview_edge_ids?: string[];
}

export interface NarrationEvent {
  event_type: string;
  model_only: boolean;
}

export type ServiceKind = "medical" | "food" | "refuge";

/** PROPOSED (P2): backend-computed service route, so React never runs routing. */
export interface ServiceRoute {
  population_id: string;
  service: ServiceKind;
  facility_id: string | null;
  reachable: boolean;
  edge_ids: string[];
}

export interface WorldSnapshot {
  schema_version: number;
  world_version: number;
  scenario_id: string;
  phase: Phase;
  simulation_stage: number;
  branch_id: string;
  token_inventory: Partial<Record<TokenType, number>>;
  tokens: PlacedToken[];
  facilities: Facility[];
  population_demand: PopulationDemand[];
  edges: EdgeState[];
  metrics: Metrics;
  ghost_suggestion: GhostSuggestion | null;
  narration_event: NarrationEvent | null;
  provenance_label: string;
  /** PROPOSED (P2) */
  service_routes?: ServiceRoute[];
}

export type ActionType =
  | "place_token"
  | "move_token"
  | "remove_token"
  | "advance_stage"
  | "reset"
  | "suggest"
  | "branch"
  | "compare";

export type ActionSource = "physical_perceptron" | "manual" | "replay";

export interface WorldAction {
  action_id: string;
  type: ActionType;
  source: ActionSource;
  token_id?: string | null;
  token_type?: TokenType | null;
  site_id?: string | null;
  board_uv?: UV | null;
  expected_world_version: number;
  timestamp_utc: string;
}

/** Response of POST /action. Rejections are rendered, never computed, by the UI. */
export interface ActionResult {
  action_id: string;
  accepted: boolean;
  reason?: string | null;
  world_version: number;
}

export type VisionStatus = "confirmed" | "unconfirmed" | "unavailable" | "scanning";

export interface ObjectObservation {
  event_type: "object_observed";
  event_id: string;
  frame_id: number;
  token_id: string;
  object_type: TokenType;
  class_source: VisionSource;
  perceptron_box_1000?: [number, number, number, number];
  board_uv: UV;
  rotation_deg?: number;
  stable_ms?: number;
  vision_status: VisionStatus;
  frame_provenance?: string;
}

export interface BranchComparison {
  baseline_snapshot_id: string;
  branches: Array<{ id: string; action: string; [metric: string]: number | string }>;
  metric_provenance: string;
}

export type Envelope =
  | { type: "world.snapshot"; seq: number; sent_at: string; payload: WorldSnapshot }
  | { type: "vision.status"; seq: number; sent_at: string; payload: { observations: ObjectObservation[]; latency_ms?: number } }
  | { type: "narration"; seq: number; sent_at: string; payload: { text: string; source: "gemini" | "template" } }
  | { type: "warning"; seq: number; sent_at: string; payload: { code: string; message: string } }
  | { type: "server.hello"; seq?: number; sent_at?: string; payload: { status: string } };

export interface ModeBadges {
  VISION: "LIVE_PERCEPTRON" | "REPLAY" | "MANUAL";
  PROJECTOR: "CALIBRATED" | "SCREEN";
  GEMINI: "LIVE" | "TEXT" | "OFF";
  DATA: "HOT_DERIVED" | "SCHEMATIC";
}

export const TOKEN_LABELS: Record<TokenType, string> = {
  hospital: "Hospital / Field Care",
  shelter: "Emergency Shelter",
  food_shelter: "Food & Water",
  bridge: "Temporary Bridge",
  disaster_start: "Start Disaster",
  person: "People / Household",
  truck: "Relief Truck",
  helicopter: "Helicopter",
  time_dial: "Time Dial",
};

/** Which site kind each token may target; mirrors contracts/token_catalog.json valid_site_kinds. */
export const TOKEN_SITE_KIND: Partial<Record<TokenType, SiteKind>> = {
  hospital: "medical_site",
  shelter: "shelter_site",
  food_shelter: "food_site",
  bridge: "bridge_crossing",
  disaster_start: "control_start_pad",
  person: "population_node",
};
