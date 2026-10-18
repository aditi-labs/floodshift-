// Mirror of backend/contracts.py (P3, schema_version 2) — that file is authoritative.
// If a field changes there, change it here in the same PR and bump SCHEMA_VERSION.
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

export type Phase = "prevention" | "ready" | "disaster_active";

export type UV = [number, number];

/** local_cv = OpenCV colour+shape rule for the printed bridge; shown as LOCAL_CV, never as Perceptron. */
export type VisionSource = "perceptron" | "local_cv" | "replay" | "manual";
export type TokenStatus = "accepted" | "pending" | "rejected";

/** backend TokenState. With markerless tracking (spec §07b) ids look like "tracked-<n>". */
export interface PlacedToken {
  id: string;
  type: TokenType;
  board_uv: UV;
  site_id?: string | null;
  vision_source: VisionSource;
  status: TokenStatus;
  rotation_deg?: number | null;
}

/** backend FacilityState */
export interface Facility {
  id: string;
  type: TokenType;
  capacity_model: number;
  used_capacity_model: number;
  /** A supply route from the depot exists. */
  reachable: boolean;
  /** Which site the facility sits on, for icon placement. */
  site_id?: string | null;
  node_id?: string | null;
  /** false: food station without supply, or site inside a flood footprint. */
  active?: boolean;
}

export interface PopulationDemand {
  id: string;
  households_model: number;
  people_model: number;
  need_food: number;
  need_medical: number;
  need_refuge: number;
  /** Capacity-bounded unmet units for this node (metrics hold the totals). */
  unmet_food?: number | null;
  unmet_medical?: number | null;
  unmet_refuge?: number | null;
  token_id?: string | null;
  /** Reasoning bundle: false means people/need fields are placeholders, not zeros. */
  headcount_known?: boolean | null;
}

export interface EdgeState {
  id: string;
  blocked: boolean;
  reason?: string | null;
}

/** backend WorldMetrics */
export interface Metrics {
  people_reachable_for_medical: number;
  people_reachable_for_food: number;
  people_reachable_for_shelter: number;
  unmet_food_model: number;
  unmet_medical_model: number;
  unmet_refuge_model: number;
  blocked_roads: number;
  resource_spent?: number;
  reachable_communities?: number;
  road_access_fraction?: number;
}

export interface GhostSuggestion {
  token_type: TokenType;
  site_id: string;
  board_uv: UV;
  reason_code: string;
  rotation_deg?: number | null;
  gain_model?: number | null;
  resource_cost?: number | null;
  /** Edge ids of the restored route through this crossing (cyan dashed preview). */
  preview_edge_ids?: string[] | null;
}

export interface NarrationEvent {
  event_type: string;
  model_only: boolean;
}

export type ServiceKind = "medical" | "food" | "refuge";

/** Backend-computed service route, so React never runs routing. If unreachable,
 *  edge_ids is the path that would work with closures open (drawn as cut). */
export interface ServiceRoute {
  population_id: string;
  service: ServiceKind;
  facility_id: string | null;
  reachable: boolean;
  edge_ids: string[];
}

export type RiskLevel = "low" | "medium" | "high" | "critical";

/** Risk zone for prevention/relief mode overlay. Colors adapt as tokens provide protection. */
export interface RiskZone {
  zone_id: string;
  node_id: string;
  board_uv_center: UV;
  radius_uv: number;
  risk_level: RiskLevel;
  flood_probability: number;
  base_probability: number;
  population_exposed: number;
  elevation_m?: number | null;
  color: string;  // Hex color for rendering
  is_protected: boolean;
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
  ghost_suggestion?: GhostSuggestion | null;
  narration_event?: NarrationEvent | null;
  provenance_label: string;
  snapshot_id?: string | null;
  data_mode?: "HOT_DERIVED" | "SCHEMATIC" | null;
  budget_remaining_model?: number | null;
  service_routes?: ServiceRoute[];
  /** Reasoning bundle only: fractional group evacuation plan (see backend/planning/population_routes.py). */
  routing_decision?: Record<string, unknown> | null;
  /** Risk zones with colors that adapt as tokens provide protection */
  risk_zones?: RiskZone[];
  mode?: "prevention" | "relief";
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

export type ActionSource = "physical_perceptron" | "physical_local_cv" | "manual" | "replay";

export interface WorldAction {
  action_id: string;
  type: ActionType;
  source: ActionSource;
  token_id?: string | null;
  token_type?: TokenType | null;
  site_id?: string | null;
  board_uv?: UV | null;
  expected_world_version: number;
  timestamp_utc?: string;
  goal?: string | null;
  branch_id?: string | null;
  from_snapshot_id?: string | null;
  branches?: string[] | null;
}

/** Response of POST /action. Rejections are rendered, never computed, by the UI. */
export interface ActionResult {
  accepted: boolean;
  action_id: string;
  world_version: number;
  rejection_reason?: string | null;
}

/** Response of POST /plan/suggest (backend/main.py). */
export interface SuggestResponse {
  has_suggestion: boolean;
  suggestion: GhostSuggestion | null;
  world_version: number;
  rejection_reason?: string | null;
}

/** Response of POST /narrate. */
export interface NarrateResponse {
  answer: string;
  grounded_in_version: number;
  /** LIVE only when Gemini actually answered; TEXT is the state-derived fallback. */
  mode?: "LIVE" | "TEXT";
  reason?: string | null;
}

export interface HealthResponse {
  status: string;
  world_version?: number | null;
  vision_mode: string;
  perceptron_status: string;
  gemini_status: string;
}

export type VisionStatus = "pending" | "confirmed" | "rejected" | "unavailable";

export interface ObjectObservation {
  event_type: "object_observed";
  event_id: string;
  frame_id: number;
  token_id: string;
  object_type: TokenType;
  class_source: VisionSource;
  perceptron_box_1000?: [number, number, number, number] | null;
  board_uv: UV;
  rotation_deg?: number;
  stable_ms?: number;
  vision_status: VisionStatus;
  frame_provenance?: string;
}

export interface BranchComparison {
  baseline_snapshot_id: string | null;
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
  VISION: "LIVE_PERCEPTRON" | "LOCAL_CV" | "REPLAY" | "MANUAL";
  PROJECTOR: "CALIBRATED" | "SCREEN";
  GEMINI: "LIVE" | "TEXT" | "OFF";
  DATA: "HOT_DERIVED" | "SCHEMATIC";
}

export const TOKEN_LABELS: Record<TokenType, string> = {
  hospital: "Hospital / Field Care",
  shelter: "Emergency Shelter",
  food_shelter: "Food & Water Station",
  bridge: "Temporary Bridge",
  disaster_start: "START DISASTER",
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
