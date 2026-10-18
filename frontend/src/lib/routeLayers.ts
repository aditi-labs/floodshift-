import type { ServiceKind, ServiceRoute, UV } from "../types/contracts";
import type { RoadGeometry } from "../types/scenario";

// Drawing helpers for backend-computed service routes. Reachability is never decided
// here: we only group the backend's edge ids so shared roads are drawn once.

export const SERVICE_ORDER: ServiceKind[] = ["medical", "food", "refuge"];

export interface EdgeRun {
  edge_id: string;
  path: UV[];
  /** Services whose route uses this mapped edge, in SERVICE_ORDER. */
  services: ServiceKind[];
}

/** Chain mapped edge geometries into one ordered polyline (fallback when board_uv is absent). */
export function chain(roads: Map<string, RoadGeometry>, edgeIds: string[]): UV[] {
  const out: UV[] = [];
  const near = (a: UV, b: UV) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  edgeIds.forEach((id, i) => {
    const r = roads.get(id);
    if (!r) return;
    let p = r.path;
    if (out.length) {
      const last = out[out.length - 1];
      if (near(p[p.length - 1], last) < near(p[0], last)) p = [...p].reverse();
      out.push(...p.slice(1));
    } else {
      // Orient the first edge so its end meets the next one.
      const next = roads.get(edgeIds[i + 1] ?? "");
      if (next) {
        const end = p[p.length - 1];
        const touches = (q: UV) => near(q, end) < 1e-6;
        if (!touches(next.path[0]) && !touches(next.path[next.path.length - 1])) p = [...p].reverse();
      }
      out.push(...p);
    }
  });
  return out;
}

/** The polyline to draw for a route: the backend's own geometry when present. */
export function routePolyline(route: ServiceRoute, roads: Map<string, RoadGeometry>): UV[] {
  return route.board_uv && route.board_uv.length >= 2 ? route.board_uv : chain(roads, route.edge_ids);
}

/**
 * Group routes per mapped edge. Open edges carry every service that reaches through
 * them; cut edges are only the ones no open route already draws.
 */
export function aggregateRouteEdges(routes: ServiceRoute[], roads: Map<string, RoadGeometry>): { open: EdgeRun[]; cut: EdgeRun[] } {
  const collect = (list: ServiceRoute[], skip: Set<string>) => {
    const byEdge = new Map<string, Set<ServiceKind>>();
    for (const r of list) {
      for (const id of r.edge_ids) {
        if (skip.has(id) || !roads.has(id)) continue;
        if (!byEdge.has(id)) byEdge.set(id, new Set());
        byEdge.get(id)!.add(r.service);
      }
    }
    return [...byEdge.entries()]
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([edge_id, set]) => ({ edge_id, path: roads.get(edge_id)!.path, services: SERVICE_ORDER.filter((s) => set.has(s)) }));
  };
  const open = collect(routes.filter((r) => r.reachable), new Set());
  const cut = collect(routes.filter((r) => !r.reachable), new Set(open.map((e) => e.edge_id)));
  return { open, cut };
}

/** Polyline length in the given units (used to time draw-on animations). */
export function polylineLength(points: { x: number; y: number }[]): number {
  let total = 0;
  for (let i = 1; i < points.length; i++) total += Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
  return total;
}
