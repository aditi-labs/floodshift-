/**
 * FLOODSHIFT Shared Contracts - Schema Version 2
 * TypeScript mirror of backend/contracts.py
 * Person 2 owns this file (mirrors P3's Pydantic schemas)
 */

// =============================================================================
// TOKEN TYPES - Six required pieces
// =============================================================================

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

export type SiteKind =
  | "medical_site"
  | "shelter_site"
  | "food_site"
  | "bridge_crossing"
  | "control_start_pad"
  | "population_node";

export type Phase = "ready" | "disaster_active";

export type VisionStatus = "pending" | "confirmed" | "rejected" | "unavailable";

export type VisionSource = "perceptron" | "manual" | "replay";

// =============================================================================
// OBJECT OBSERVATION - Person 3 produces
// =============================================================================

export interface ObjectObservation {
  event_type: "object_observed";
  event_id: string;
  frame_id: number;
  token_id: string;
  object_type: TokenType;
  class_source: VisionSource;
  perceptron_box_1000: [number, number, number, number] | null;
  board_uv: [number, number];
  rotation_deg: number;
  stable_ms: number;
  vision_status: VisionStatus;
  frame_provenance: string;
}

// =============================================================================
// WORLD ACTION - P2 manual controls / P3 gateway -> P4 reducer
// =============================================================================

export type ActionType =
  | "place_token"
  | "move_token"
  | "remove_token"
  | "advance_stage"
  | "reset"
  | "suggest"
  | "branch"
  | "compare";

export interface WorldAction {
  action_id: string;
  type: ActionType;
  source: "physical_perceptron" | "manual" | "replay";
  token_id?: string;
  token_type?: TokenType;
  site_id?: string;
  board_uv?: [number, number];
  expected_world_version: number;
  timestamp_utc?: string;
}

export interface ActionResult {
  accepted: boolean;
  action_id: string;
  world_version: number;
  rejection_reason?: string;
}

// =============================================================================
// WORLD SNAPSHOT - P4 produces, P3 serves, P2 renders
// =============================================================================

export interface TokenState {
  id: string;
  type: TokenType;
  board_uv: [number, number];
  site_id?: string;
  vision_source: VisionSource;
  status: "accepted" | "pending" | "rejected";
}

export interface FacilityState {
  id: string;
  type: TokenType;
  capacity_model: number;
  used_capacity_model: number;
  reachable: boolean;
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
  reason?: string;
}

export interface WorldMetrics {
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
  board_uv: [number, number];
  reason_code: string;
}

export interface NarrationEvent {
  event_type: string;
  model_only: boolean;
}

export interface WorldSnapshot {
  schema_version: number;
  world_version: number;
  scenario_id: string;
  phase: Phase;
  simulation_stage: number;
  branch_id: string;
  token_inventory: Record<string, number>;
  tokens: TokenState[];
  facilities: FacilityState[];
  population_demand: PopulationDemand[];
  edges: EdgeState[];
  metrics: WorldMetrics;
  ghost_suggestion?: GhostSuggestion;
  narration_event?: NarrationEvent;
  provenance_label: string;
}

// =============================================================================
// API SCHEMAS
// =============================================================================

export interface HealthResponse {
  status: string;
  world_version?: number;
  vision_mode: string;
  perceptron_status: string;
  gemini_status: string;
}

export interface SuggestRequest {
  goal_id?: string;
}

export interface BranchSaveRequest {
  name: string;
}

export interface BranchLoadRequest {
  branch_id: string;
}

export interface NarrateRequest {
  question: string;
}

export interface NarrateResponse {
  answer: string;
  grounded_in_version: number;
}

// =============================================================================
// WEBSOCKET EVENT ENVELOPE
// =============================================================================

export type WSEventType = "world.snapshot" | "vision.status" | "narration" | "warning" | "server.hello";

export interface WSEvent {
  type: WSEventType;
  seq: number;
  sent_at: string;
  payload: Record<string, unknown>;
}

// =============================================================================
// GEOMETRY HELPERS (for projection)
// =============================================================================

export const BOARD_WIDTH = 1000;
export const BOARD_HEIGHT = 707.14; // 1000 * 297 / 420 (A3 ratio)

export function toSvgPoint(u: number, v: number): { x: number; y: number } {
  return { x: u * BOARD_WIDTH, y: v * BOARD_HEIGHT };
}
