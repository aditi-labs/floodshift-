import { describe, expect, it } from "vitest";
import type { UV, WorldSnapshot } from "../types/contracts";
import type { RoadGeometry } from "../types/scenario";
import afterBridge from "../../../scenarios/nepal_rasuwa_hot_v1/data/fixture_after_bridge.json";
import beforeBridge from "../../../scenarios/nepal_rasuwa_hot_v1/data/fixture_world.json";
import { aggregateRouteEdges, chain, routePolyline } from "./routeLayers";

const after = afterBridge as unknown as WorldSnapshot;
const before = beforeBridge as unknown as WorldSnapshot;

describe("route rendering uses backend route identity", () => {
  it("draws the backend polyline verbatim (operator and projector share it)", () => {
    for (const r of after.service_routes!) expect(routePolyline(r, new Map())).toBe(r.board_uv);
  });

  it("groups shared edges once per mapped edge id, with each service listed", () => {
    const ids = new Set(after.service_routes!.flatMap((r) => r.edge_ids));
    const roads = new Map([...ids].map((id) => [id, { id, from: "", to: "", kind: "road" as const, path: [[0, 0], [1, 1]] as UV[] }]));
    const { open, cut } = aggregateRouteEdges(after.service_routes!, roads);
    expect(cut).toEqual([]);
    expect(new Set(open.map((e) => e.edge_id))).toEqual(ids);
    // No duplicate edge entries even though three services share most of the path.
    expect(open.length).toBe(ids.size);
    const shared = open.find((e) => e.edge_id === "crossing_east_road")!;
    expect(shared.services).toEqual(["medical", "food", "refuge"]);
  });

  it("keeps unreachable routes unreachable and never draws a cut edge under an open one", () => {
    const ids = new Set(before.service_routes!.flatMap((r) => r.edge_ids));
    const roads = new Map([...ids].map((id) => [id, { id, from: "", to: "", kind: "road" as const, path: [[0, 0], [1, 1]] as UV[] }]));
    const { open, cut } = aggregateRouteEdges(before.service_routes!, roads);
    const openIds = new Set(open.map((e) => e.edge_id));
    expect(cut.some((e) => e.edge_id === "crossing_east_road")).toBe(true);
    expect(cut.every((e) => !openIds.has(e.edge_id))).toBe(true);
  });

  it("chain orients segments so consecutive edges meet without shortcuts", () => {
    const roads = new Map<string, RoadGeometry>([
      ["a", { id: "a", from: "1", to: "2", kind: "road", path: [[0.2, 0], [0.1, 0], [0, 0]] }],
      ["b", { id: "b", from: "3", to: "2", kind: "road", path: [[0.2, 0.3], [0.2, 0.1], [0.2, 0]] }],
    ]);
    // Edge a is stored backwards relative to the route; b is stored end-first.
    expect(chain(roads, ["a", "b"])).toEqual([[0, 0], [0.1, 0], [0.2, 0], [0.2, 0.1], [0.2, 0.3]]);
  });

  it("fixture routes carry geometry for every route", () => {
    for (const r of [...after.service_routes!, ...before.service_routes!]) expect(r.board_uv!.length).toBeGreaterThanOrEqual(2);
  });
});
