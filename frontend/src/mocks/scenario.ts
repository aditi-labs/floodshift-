import type { ScenarioGeometry } from "../types/scenario";

// SCHEMATIC stand-in for P4's nepal_rasuwa_v1 bundle (roads.json / sites.json /
// hazard.json). Invented layout so the UI can be built before HOT geometry is
// exported. Replace by GET /scenario in live mode; ids must match P4's ids.
export const MOCK_SCENARIO: ScenarioGeometry = {
  scenario_id: "nepal_rasuwa_v1",
  name: "Nepal 2026 — Bhote Koshi / Trishuli educational exercise",
  data_label: "SCHEMATIC",
  rivers: [
    [
      [0.53, 0.0],
      [0.5, 0.18],
      [0.47, 0.36],
      [0.495, 0.52],
      [0.53, 0.7],
      [0.525, 0.8],
      [0.49, 1.0],
    ],
  ],
  hazard_zones: [
    {
      id: "corridor_stage_1",
      stage: 1,
      polygon: [
        [0.49, 0.0],
        [0.57, 0.0],
        [0.54, 0.18],
        [0.52, 0.36],
        [0.55, 0.52],
        [0.59, 0.7],
        [0.58, 0.82],
        [0.54, 1.0],
        [0.44, 1.0],
        [0.47, 0.8],
        [0.47, 0.7],
        [0.44, 0.52],
        [0.42, 0.36],
        [0.46, 0.18],
      ],
    },
  ],
  roads: [
    { id: "r_depot_food", from: "depot", to: "food_site_west", kind: "road", path: [[0.12, 0.3], [0.18, 0.3], [0.24, 0.31]] },
    { id: "r_depot_whub", from: "depot", to: "w_hub", kind: "road", path: [[0.12, 0.3], [0.22, 0.38], [0.3, 0.45]] },
    { id: "r_depot_wnorth", from: "depot", to: "w_north", kind: "road", path: [[0.12, 0.3], [0.24, 0.24], [0.36, 0.2]] },
    { id: "r_whub_med", from: "w_hub", to: "medical_site_west", kind: "road", path: [[0.3, 0.45], [0.24, 0.52], [0.2, 0.58]] },
    { id: "r_whub_shelter", from: "w_hub", to: "shelter_site_west", kind: "road", path: [[0.3, 0.45], [0.31, 0.58], [0.3, 0.72]] },
    { id: "r_whub_wbank", from: "w_hub", to: "w_bank", kind: "road", path: [[0.3, 0.45], [0.38, 0.5], [0.44, 0.52]] },
    { id: "crossing_east_road", from: "w_bank", to: "e_bank", kind: "crossing", path: [[0.44, 0.52], [0.55, 0.53]] },
    { id: "r_ebank_ehub", from: "e_bank", to: "e_hub", kind: "road", path: [[0.55, 0.53], [0.62, 0.51], [0.7, 0.48]] },
    { id: "r_ehub_village", from: "e_hub", to: "people_east", kind: "road", path: [[0.7, 0.48], [0.77, 0.44], [0.84, 0.42]] },
    { id: "r_wnorth_wnbank", from: "w_north", to: "wn_bank", kind: "road", path: [[0.36, 0.2], [0.45, 0.19]] },
    { id: "crossing_north_road", from: "wn_bank", to: "en_bank", kind: "crossing", path: [[0.45, 0.19], [0.56, 0.17]] },
    { id: "r_enbank_enorth", from: "en_bank", to: "people_north", kind: "road", path: [[0.56, 0.17], [0.68, 0.16], [0.8, 0.18]] },
    { id: "r_enorth_village", from: "people_north", to: "people_east", kind: "road", path: [[0.8, 0.18], [0.83, 0.3], [0.84, 0.42]] },
    { id: "r_whub_wsbank", from: "w_hub", to: "ws_bank", kind: "road", path: [[0.3, 0.45], [0.4, 0.66], [0.47, 0.8]] },
    { id: "crossing_south_road", from: "ws_bank", to: "es_bank", kind: "crossing", path: [[0.47, 0.8], [0.58, 0.81]] },
    { id: "r_esbank_ehub", from: "es_bank", to: "e_hub", kind: "road", path: [[0.58, 0.81], [0.66, 0.64], [0.7, 0.48]] },
  ],
  sites: [
    { id: "control_start_pad", kind: "control_start_pad", label: "START", board_uv: [0.09, 0.86] },
    { id: "medical_site_west", kind: "medical_site", label: "Field care pad", board_uv: [0.2, 0.58] },
    { id: "food_site_west", kind: "food_site", label: "Food & water pad", board_uv: [0.24, 0.31] },
    { id: "shelter_site_west", kind: "shelter_site", label: "Shelter pad", board_uv: [0.3, 0.72] },
    { id: "people_east", kind: "population_node", label: "East village", board_uv: [0.84, 0.42] },
    { id: "people_north", kind: "population_node", label: "Upper settlement", board_uv: [0.8, 0.18] },
    { id: "crossing_east", kind: "bridge_crossing", label: "East crossing", board_uv: [0.495, 0.525], rotation_deg: 5 },
    { id: "crossing_north", kind: "bridge_crossing", label: "North crossing", board_uv: [0.505, 0.18], rotation_deg: -10 },
    { id: "crossing_south", kind: "bridge_crossing", label: "South crossing", board_uv: [0.525, 0.805], rotation_deg: 5 },
  ],
  labels: [
    { text: "WEST DEPOT", board_uv: [0.12, 0.26] },
    { text: "BHOTE KOSHI (schematic)", board_uv: [0.6, 0.94] },
  ],
};
