import type { PlacedToken, ServiceKind, ServiceRoute, TokenType, UV, WorldSnapshot } from "../types/contracts";

// Environmental reactions are derived ONLY from differences between two authoritative
// WorldSnapshots. Nothing here decides reachability or invents numbers: every message
// is backed by a change the backend computed. The same diff runs for mouse, keyboard,
// Perceptron and local-CV actions because all of them arrive as snapshots.

export type ReactionKind =
  | "flood_stage"
  | "flood_recede"
  | "edge_restored"
  | "edge_blocked"
  | "route_opened"
  | "route_lost"
  | "coverage"
  | "isolated"
  | "token_placed"
  | "token_removed"
  | "need_reduced"
  | "need_increased"
  | "communities_changed"
  | "facility_changed"
  | "budget_changed";

export type Tone = "good" | "bad" | "info";

export interface Reaction {
  id: string;
  kind: ReactionKind;
  tone: Tone;
  board_uv?: UV;
  edge_ids?: string[];
  /** Ordered route polyline from the backend (population → facility). */
  path?: UV[];
  service?: ServiceKind;
  token_type?: TokenType;
  stage?: number;
  amount?: number;
  text: string;
}

export interface ReactionSet {
  /** scenario:branch:version — identical deliveries of one snapshot react once. */
  key: string;
  reactions: Reaction[];
  headline: { text: string; tone: Tone } | null;
  scoreDelta: number | null;
  /** Reset or branch load: the world was replaced, not changed by one intervention. */
  replaced: boolean;
}

export const SERVICE_OF: Partial<Record<TokenType, ServiceKind>> = {
  hospital: "medical",
  food_shelter: "food",
  shelter: "refuge",
};

const NEED_LABEL: Record<ServiceKind, string> = { medical: "medical", food: "food", refuge: "shelter" };
const DIRECTION: Record<string, string> = { east: "EASTERN", west: "WESTERN", north: "NORTHERN", south: "SOUTHERN" };
const TYPE_LABEL: Partial<Record<TokenType, string>> = {
  hospital: "HOSPITAL",
  food_shelter: "FOOD STATION",
  shelter: "SHELTER",
  bridge: "BRIDGE",
  person: "COMMUNITY",
};

export function snapshotKey(s: WorldSnapshot): string {
  return `${s.scenario_id}:${s.branch_id}:${s.world_version}`;
}

const routeKey = (r: ServiceRoute) => `${r.population_id}|${r.service}`;

function byId<T extends { id: string }>(items: T[] | undefined): Map<string, T> {
  return new Map((items ?? []).map((i) => [i.id, i]));
}

function unmet(s: WorldSnapshot, need: ServiceKind): number {
  const m = s.metrics;
  return need === "medical" ? m.unmet_medical_model : need === "food" ? m.unmet_food_model : m.unmet_refuge_model;
}

function reachableFor(s: WorldSnapshot, need: ServiceKind): number {
  const m = s.metrics;
  return need === "medical" ? m.people_reachable_for_medical : need === "food" ? m.people_reachable_for_food : m.people_reachable_for_shelter;
}

/** "crossing_east" → "EASTERN"; only for ids whose last word is a compass direction. */
function direction(siteId?: string | null): string | null {
  const suffix = siteId?.split("_").pop() ?? "";
  return DIRECTION[suffix] ?? null;
}

/** True when nothing an intervention can change differs (ghost, narration, bookmarks only). */
function sameOutcome(a: WorldSnapshot, b: WorldSnapshot): boolean {
  const pick = (s: WorldSnapshot) =>
    JSON.stringify([
      s.phase,
      s.simulation_stage,
      s.budget_remaining_model,
      s.tokens.map((t) => [t.id, t.site_id, t.type]),
      s.edges.map((e) => [e.id, e.blocked]),
      (s.service_routes ?? []).map((r) => [routeKey(r), r.reachable, r.facility_id]),
      s.facilities.map((f) => [f.id, f.reachable, f.active, f.used_capacity_model]),
      s.metrics,
    ]);
  return pick(a) === pick(b);
}

export function diffSnapshots(prev: WorldSnapshot | null, next: WorldSnapshot): ReactionSet | null {
  if (!prev || snapshotKey(prev) === snapshotKey(next)) return null;
  if (prev.scenario_id !== next.scenario_id) return null;
  const key = snapshotKey(next);
  const replaced =
    next.branch_id !== prev.branch_id ||
    next.world_version < prev.world_version ||
    next.narration_event?.event_type === "branch_loaded" ||
    (prev.phase === "disaster_active" && next.phase === "ready");
  if (sameOutcome(prev, next)) return null;

  const reactions: Reaction[] = [];
  const add = (r: Omit<Reaction, "id">) => reactions.push({ ...r, id: `${key}#${reactions.length}` });

  // Flood stage: the board's hazard changed (start, advance, reset, branch load).
  if (next.simulation_stage > prev.simulation_stage) {
    add({ kind: "flood_stage", tone: "bad", stage: next.simulation_stage, text: `Flood reached stage ${next.simulation_stage}` });
  } else if (next.simulation_stage < prev.simulation_stage) {
    add({ kind: "flood_recede", tone: "info", stage: next.simulation_stage, text: `Flood stage ${next.simulation_stage}` });
  }

  if (replaced) {
    const text = next.phase === "ready" ? "BOARD RESET" : `STRATEGY ${next.branch_id.toUpperCase()} LOADED`;
    return { key, reactions, headline: { text, tone: "info" }, scoreDelta: null, replaced: true };
  }

  const prevTokens = byId(prev.tokens);
  const nextTokens = byId(next.tokens);
  const added = next.tokens.filter((t) => !prevTokens.has(t.id) || prevTokens.get(t.id)!.site_id !== t.site_id);
  const removed = prev.tokens.filter((t) => !nextTokens.has(t.id) || nextTokens.get(t.id)!.site_id !== t.site_id);

  const prevEdges = byId(prev.edges);
  const restoredEdges = next.edges.filter((e) => !e.blocked && prevEdges.get(e.id)?.blocked).map((e) => e.id);
  const blockedEdges = next.edges.filter((e) => e.blocked && prevEdges.get(e.id) && !prevEdges.get(e.id)!.blocked).map((e) => e.id);

  const prevRoutes = new Map((prev.service_routes ?? []).map((r) => [routeKey(r), r]));
  const nextRoutes = new Map((next.service_routes ?? []).map((r) => [routeKey(r), r]));
  const opened = [...nextRoutes.values()].filter((r) => r.reachable && !prevRoutes.get(routeKey(r))?.reachable);
  const lost = [...prevRoutes.values()].filter((r) => r.reachable && !nextRoutes.get(routeKey(r))?.reachable);

  const bridgeAdded = added.find((t) => t.type === "bridge");
  const bridgeRemoved = removed.find((t) => t.type === "bridge");

  if (restoredEdges.length) {
    add({ kind: "edge_restored", tone: "good", edge_ids: restoredEdges, board_uv: bridgeAdded?.board_uv,
          text: `${restoredEdges.length} road section(s) reopened` });
  }
  if (blockedEdges.length) {
    add({ kind: "edge_blocked", tone: "bad", edge_ids: blockedEdges, board_uv: bridgeRemoved?.board_uv,
          text: `${blockedEdges.length} road section(s) closed` });
  }
  for (const r of opened) {
    add({ kind: "route_opened", tone: "good", service: r.service, edge_ids: r.edge_ids, path: r.board_uv ?? undefined,
          text: `${r.population_id} reaches ${NEED_LABEL[r.service]}` });
  }
  for (const r of lost) {
    const now = nextRoutes.get(routeKey(r));
    add({ kind: "route_lost", tone: "bad", service: r.service, edge_ids: r.edge_ids, path: (now?.board_uv ?? r.board_uv) ?? undefined,
          text: `${r.population_id} lost ${NEED_LABEL[r.service]} access` });
  }

  for (const t of added) {
    const service = SERVICE_OF[t.type];
    if (service) {
      const serves = [...nextRoutes.values()].some((r) => r.reachable && r.facility_id === t.id);
      add({ kind: "coverage", tone: serves ? "good" : "bad", service, token_type: t.type, board_uv: t.board_uv,
            text: serves ? `${TYPE_LABEL[t.type]} serving` : `${TYPE_LABEL[t.type]} unreachable` });
    } else if (t.type === "person") {
      const own = [...nextRoutes.values()].filter((r) => r.population_id === (t.site_id ?? ""));
      const isolated = own.length > 0 && own.every((r) => !r.reachable);
      add({ kind: isolated ? "isolated" : "token_placed", tone: isolated ? "bad" : "info", token_type: t.type, board_uv: t.board_uv,
            text: isolated ? "Community cut off from every service" : "Community placed" });
    } else if (t.type !== "disaster_start") {
      add({ kind: "token_placed", tone: "info", token_type: t.type, board_uv: t.board_uv, text: `${t.type} placed` });
    }
  }
  for (const t of removed) {
    add({ kind: "token_removed", tone: "info", token_type: t.type, board_uv: t.board_uv, text: `${t.type} removed` });
  }

  for (const need of ["medical", "food", "refuge"] as ServiceKind[]) {
    const delta = unmet(next, need) - unmet(prev, need);
    if (delta) {
      add({ kind: delta < 0 ? "need_reduced" : "need_increased", tone: delta < 0 ? "good" : "bad", service: need,
            amount: Math.abs(delta), text: `Unmet ${NEED_LABEL[need]} ${delta < 0 ? "−" : "+"}${Math.abs(delta)} model units` });
    }
  }
  const communities = (next.metrics.reachable_communities ?? 0) - (prev.metrics.reachable_communities ?? 0);
  if (communities) {
    add({ kind: "communities_changed", tone: communities > 0 ? "good" : "bad", amount: communities,
          text: `${Math.abs(communities)} model communit${Math.abs(communities) === 1 ? "y" : "ies"} ${communities > 0 ? "connected" : "cut off"}` });
  }
  const prevFacilities = byId(prev.facilities);
  for (const f of next.facilities) {
    const was = prevFacilities.get(f.id);
    if (was && (was.active !== f.active || was.reachable !== f.reachable)) {
      const up = (f.active ?? true) && f.reachable;
      add({ kind: "facility_changed", tone: up ? "good" : "bad", token_type: f.type, text: `${TYPE_LABEL[f.type] ?? f.type} ${up ? "supplied" : "lost supply"}` });
    }
  }
  const budget = (next.budget_remaining_model ?? 0) - (prev.budget_remaining_model ?? 0);
  if (budget) add({ kind: "budget_changed", tone: "info", amount: budget, text: `Budget ${budget > 0 ? "+" : ""}${budget}` });

  const prevScore = prev.game?.status === "active" ? prev.game.score : null;
  const nextScore = next.game?.status === "active" ? next.game.score : null;
  // Placing communities is scenario setup, not a decision: its score change is not celebrated or blamed.
  const setupOnly = [...added, ...removed].length > 0 && [...added, ...removed].every((t) => t.type === "person" || t.type === "disaster_start");
  const scoreDelta = !setupOnly && prevScore != null && nextScore != null && nextScore !== prevScore ? nextScore - prevScore : null;

  return {
    key,
    reactions,
    headline: headline(prev, next, { added, removed, opened, lost, restoredEdges, bridgeAdded, bridgeRemoved, communities }),
    scoreDelta,
    replaced: false,
  };
}

interface Changes {
  added: PlacedToken[];
  removed: PlacedToken[];
  opened: ServiceRoute[];
  lost: ServiceRoute[];
  restoredEdges: string[];
  bridgeAdded?: PlacedToken;
  bridgeRemoved?: PlacedToken;
  communities: number;
}

/** One short projector line, chosen by priority, and only if the state supports it. */
function headline(prev: WorldSnapshot, next: WorldSnapshot, c: Changes): ReactionSet["headline"] {
  if (prev.simulation_stage === 0 && next.simulation_stage > 0) return { text: "FLOOD ARRIVING", tone: "bad" };
  if (next.simulation_stage > prev.simulation_stage) return { text: `FLOOD STAGE ${next.simulation_stage}`, tone: "bad" };

  if (c.bridgeAdded) {
    if (c.opened.length) {
      // A direction is named only if a newly opened route actually crosses this bridge's edge.
      const crosses = c.opened.some((r) => r.edge_ids.some((id) => c.restoredEdges.includes(id)));
      const dir = crosses ? direction(c.bridgeAdded.site_id) : null;
      return { text: `BRIDGE DEPLOYED — ${dir ? dir + " " : ""}ACCESS RESTORED`, tone: "good" };
    }
    return { text: c.restoredEdges.length ? "BRIDGE DEPLOYED — NO NEW ACCESS" : "BRIDGE PLACED", tone: "info" };
  }
  if (c.bridgeRemoved) return { text: c.lost.length ? "BRIDGE REMOVED — ACCESS LOST" : "BRIDGE REMOVED", tone: c.lost.length ? "bad" : "info" };
  if (c.communities > 0) {
    return { text: `${c.communities} MODEL ${c.communities === 1 ? "COMMUNITY" : "COMMUNITIES"} CONNECTED`, tone: "good" };
  }

  for (const t of c.added) {
    const service = SERVICE_OF[t.type];
    if (!service) continue;
    const reduced = unmet(next, service) < unmet(prev, service);
    const reached = reachableFor(next, service) > reachableFor(prev, service);
    if (t.type === "hospital") return reduced ? { text: "MEDICAL COVERAGE IMPROVED", tone: "good" } : { text: "HOSPITAL OPEN — NO ONE CAN REACH IT", tone: "bad" };
    if (t.type === "food_shelter") return reduced ? { text: "FOOD & WATER DISTRIBUTION ACTIVE", tone: "good" } : { text: "FOOD STATION — NO ONE CAN REACH IT", tone: "bad" };
    if (t.type === "shelter") {
      const safe = reachableFor(next, "refuge") - reachableFor(prev, "refuge");
      return reached && safe > 0 ? { text: `SHELTER OPEN — ${safe} MODEL PEOPLE CAN REACH SAFETY`, tone: "good" } : { text: "SHELTER OPEN — NO ONE CAN REACH IT", tone: "bad" };
    }
  }
  const person = c.added.find((t) => t.type === "person");
  if (person) {
    const own = (next.service_routes ?? []).filter((r) => r.population_id === person.site_id);
    if (!own.length) return { text: "COMMUNITY PLACED — NO SERVICES YET", tone: "info" };
    return own.every((r) => !r.reachable) ? { text: "COMMUNITY ISOLATED", tone: "bad" } : { text: "COMMUNITY HAS ACCESS", tone: "good" };
  }
  const gone = c.removed.find((t) => SERVICE_OF[t.type]);
  if (gone) return { text: `${TYPE_LABEL[gone.type]} REMOVED${c.lost.length ? " — ACCESS LOST" : ""}`, tone: c.lost.length ? "bad" : "info" };
  if (c.opened.length) return { text: "ACCESS RESTORED", tone: "good" };
  if (c.lost.length) return { text: "ACCESS LOST", tone: "bad" };
  return null;
}
