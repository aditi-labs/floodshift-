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
  /** For bridge_crossing: span angle in degrees for the ghost silhouette. */
  rotation_deg?: number;
}

export interface ScenarioGeometry {
  scenario_id: string;
  name: string;
  data_label: "HOT_DERIVED" | "SCHEMATIC";
  rivers: UV[][];
  hazard_zones: { id: string; stage: number; polygon: UV[] }[];
  roads: RoadGeometry[];
  sites: SiteGeometry[];
  labels: { text: string; board_uv: UV }[];
}
