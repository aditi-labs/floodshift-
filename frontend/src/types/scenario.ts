import type { SiteKind, UV } from "./contracts";

// Static, immutable scenario geometry (P4 exports it as roads.json / sites.json /
// hazard.json; P3 serves it from GET /scenario). The UI only draws it; whether an
// edge is blocked or a route is reachable always comes from the WorldSnapshot.

export interface RoadGeometry {
  id: string; // matches WorldSnapshot.edges[].id
  from: string;
  to: string;
  kind: "road" | "crossing";
  path: UV[];
}

export interface SiteGeometry {
  id: string;
  kind: SiteKind;
  label: string;
  board_uv: UV;
  /** Placement radius the reducer accepts around board_uv. */
  tolerance_uv?: number;
  /** For bridge_crossing: span angle in degrees for the ghost silhouette. */
  rotation_deg?: number;
}

export interface FloodCorridor {
  id: string;
  stage: number;
  path: UV[];
  /** Full corridor width in board units. */
  width_uv: number;
  waterway: string;
}

export interface ScenarioGeometry {
  scenario_id: string;
  name: string;
  data_label: "HOT_DERIVED" | "SCHEMATIC";
  /** Physical board width / height. HOT bundles are square (1.0); the schematic is A3 (≈1.414). */
  aspect_ratio?: number;
  board?: { width_mm?: number; height_mm?: number; control_inset_uv?: [number, number, number, number] };
  provenance_label?: string;
  rivers: UV[][];
  /** Scenario flood footprints (polygons), when the bundle has them. */
  hazard_zones: { id: string; stage: number; polygon: UV[] }[];
  /** Otherwise: illustrative river reaches near that stage's simulated closures (backend-derived). */
  flood_corridors?: FloodCorridor[];
  /** Number of hazard stages including the dry stage 0. */
  stage_count?: number;
  hazard?: { method?: string | null; kind: "simulated_hazard"; geometry_source: string; limitations?: string[] };
  roads: RoadGeometry[];
  sites: SiteGeometry[];
  labels: { text: string; board_uv: UV }[];
}
