import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ActionResult, Envelope, ObjectObservation, TokenType, UV, WorldAction, WorldSnapshot } from "../types/contracts";
import type { ScenarioGeometry } from "../types/scenario";
import { createLiveTransport } from "../lib/liveTransport";
import { setBoardAspect } from "../types/geometry";
import { newActionId, nowUtc, type ConnectionStatus, type WorldTransport } from "../lib/transport";
import { diffSnapshots, type ReactionSet } from "../lib/worldReactions";

// The real FastAPI WorldService is the only source of state. There is no scripted or
// offline mode: if the gateway is unreachable the UI shows an explicit error.
export const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

let shared: WorldTransport | null = null;
function transport(): WorldTransport {
  shared ??= createLiveTransport(API_URL);
  return shared;
}

/** How long one set of environmental reactions stays on the board. */
export const REACTION_MS = 4600;

export interface LogEntry {
  at: string;
  kind: "accepted" | "rejected" | "info" | "warning" | "narration" | "vision" | "reaction";
  text: string;
}

/** Short-lived visual feedback the projector shows at a board position. */
export interface Feedback {
  id: string;
  kind: "accepted" | "rejected" | "recognized";
  board_uv: UV;
  label: string;
  until: number;
}

export interface ActiveReactions extends ReactionSet {
  until: number;
}

export function useWorldSocket() {
  const t = useMemo(transport, []);
  const [snapshot, setSnapshot] = useState<WorldSnapshot | null>(null);
  const [scenario, setScenario] = useState<ScenarioGeometry | null>(null);
  const [scenarioError, setScenarioError] = useState<string | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [narration, setNarration] = useState<{ text: string; source: string } | null>(null);
  const [observations, setObservations] = useState<ObjectObservation[]>([]);
  const [visionLatency, setVisionLatency] = useState<number | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [feedback, setFeedback] = useState<Feedback[]>([]);
  const [reactions, setReactions] = useState<ActiveReactions[]>([]);
  const lastSeq = useRef(-Infinity);
  const snapRef = useRef<WorldSnapshot | null>(null);
  const reacted = useRef(new Set<string>());

  const push = useCallback((kind: LogEntry["kind"], text: string) => {
    setLog((l) => [{ at: new Date().toLocaleTimeString(), kind, text }, ...l].slice(0, 120));
  }, []);

  const flash = useCallback((kind: Feedback["kind"], board_uv: UV, label: string, ms = 2600) => {
    const f: Feedback = { id: `${kind}-${Math.random().toString(36).slice(2)}`, kind, board_uv, label, until: Date.now() + ms };
    setFeedback((list) => [...list.filter((x) => x.until > Date.now()), f]);
    window.setTimeout(() => setFeedback((list) => list.filter((x) => x.id !== f.id)), ms);
  }, []);

  const react = useCallback(
    (prev: WorldSnapshot | null, next: WorldSnapshot) => {
      const set = diffSnapshots(prev, next);
      if (!set || reacted.current.has(set.key)) return;
      reacted.current.add(set.key);
      const active: ActiveReactions = { ...set, until: Date.now() + REACTION_MS };
      setReactions((list) => [...list.filter((r) => r.until > Date.now()), active]);
      window.setTimeout(() => setReactions((list) => list.filter((r) => r.key !== set.key)), REACTION_MS);
      if (set.headline) push("reaction", `${set.headline.text}${set.scoreDelta ? ` (score ${set.scoreDelta > 0 ? "+" : ""}${set.scoreDelta})` : ""}`);
    },
    [push],
  );

  // Geometry is static per scenario, but the server may be started after the UI.
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const load = () =>
      t.getScenario().then(
        (s) => {
          if (cancelled) return;
          setBoardAspect(s.aspect_ratio);
          setScenario(s);
          setScenarioError(null);
        },
        (err: Error) => {
          if (cancelled) return;
          setScenarioError(`GET ${t.baseUrl}/scenario failed: ${err.message}`);
          timer = window.setTimeout(load, 2000);
        },
      );
    load();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [t]);

  useEffect(() => {
    const onEnvelope = (e: Envelope) => {
      // A new connection (possibly to a restarted server) restarts the sequence.
      if (e.type === "server.hello") lastSeq.current = -Infinity;
      if (typeof e.seq === "number" && e.seq > 0 && e.seq <= lastSeq.current) return;
      if (typeof e.seq === "number" && e.seq > 0) lastSeq.current = e.seq;
      switch (e.type) {
        case "world.snapshot": {
          const prev = snapRef.current;
          // Ignore out-of-order snapshots on the same branch (reset/branch load still raise the version).
          if (prev && e.payload.branch_id === prev.branch_id && e.payload.world_version < prev.world_version && e.payload.world_version !== 0) return;
          // A restarted server begins again at version 0: treat it as a new world, not a diff.
          const restarted = prev && e.payload.world_version === 0 && prev.world_version > 0;
          snapRef.current = e.payload;
          setSnapshot(e.payload);
          if (!restarted) react(prev, e.payload);
          break;
        }
        case "narration":
          setNarration(e.payload);
          push("narration", e.payload.text);
          break;
        case "vision.status":
          setObservations(e.payload.observations);
          setVisionLatency(e.payload.latency_ms ?? null);
          for (const o of e.payload.observations) {
            push("vision", `${o.object_type} ${o.vision_status} (${o.class_source}) at [${o.board_uv.map((n) => n.toFixed(2)).join(", ")}]`);
            if (o.vision_status === "confirmed") flash("recognized", o.board_uv, o.object_type.replace("_", " ").toUpperCase(), 1400);
          }
          break;
        case "warning":
          push("warning", e.payload.message);
          break;
        case "server.hello":
          push("info", `server: ${e.payload.status}`);
          break;
      }
    };
    return t.connect(onEnvelope, setStatus);
  }, [t, push, flash, react]);

  const handleResult = useCallback(
    (r: ActionResult, label: string, uv?: UV | null) => {
      if (r.accepted) {
        push("accepted", `${label} → world ${r.world_version}`);
        if (uv) flash("accepted", uv, "✓");
      } else {
        push("rejected", `${label} rejected: ${r.rejection_reason}`);
        if (uv) flash("rejected", uv, reasonText(r.rejection_reason));
      }
      return r;
    },
    [push, flash],
  );

  const send = useCallback(
    async (partial: Omit<WorldAction, "action_id" | "expected_world_version" | "timestamp_utc" | "source"> & { source?: WorldAction["source"] }) => {
      const action: WorldAction = {
        source: "manual",
        ...partial,
        action_id: newActionId(partial.type),
        expected_world_version: snapRef.current?.world_version ?? 0,
        timestamp_utc: nowUtc(),
      };
      try {
        const r = await t.sendAction(action);
        const label = `${action.type}${action.token_type ? " " + action.token_type : ""}${action.site_id ? " @ " + action.site_id : ""}${action.token_id && action.type !== "place_token" ? " " + action.token_id : ""}`;
        return handleResult(r, label, action.board_uv);
      } catch (err) {
        push("warning", `POST /action failed: ${(err as Error).message}`);
        return null;
      }
    },
    [t, handleResult, push],
  );

  const placeToken = useCallback(
    (token_type: TokenType, site_id: string, board_uv: UV, token_id?: string) =>
      // One id per pad: two people on two pads are two tokens, not a repeat of one.
      send({ type: "place_token", token_type, site_id, board_uv, token_id: token_id ?? `manual-${token_type}-${site_id}` }),
    [send],
  );

  const removeToken = useCallback((token_id: string) => send({ type: "remove_token", token_id }), [send]);

  const moveToken = useCallback(
    (token_id: string, site_id: string, board_uv: UV) => send({ type: "move_token", token_id, site_id, board_uv }),
    [send],
  );

  const advanceStage = useCallback(() => send({ type: "advance_stage" }), [send]);

  const reset = useCallback(async () => {
    try {
      const r = await t.reset();
      push(r.reset ? "accepted" : "rejected", `reset → world ${r.world_version}`);
      return r;
    } catch (err) {
      push("warning", `POST /reset failed: ${(err as Error).message}`);
      return null;
    }
  }, [t, push]);

  const suggest = useCallback(
    async (goalId = "needs_served") => {
      try {
        const r = await t.suggest(goalId, snapRef.current?.world_version ?? 0);
        return handleResult(r, "suggest bridge");
      } catch (err) {
        push("warning", `POST /plan/suggest failed: ${(err as Error).message}`);
        return null;
      }
    },
    [t, handleResult, push],
  );

  const wrap = useCallback(
    <A extends unknown[], R>(name: string, fn: (...a: A) => Promise<R>) =>
      async (...a: A): Promise<R | null> => {
        try {
          return await fn(...a);
        } catch (err) {
          push("warning", `${name} failed: ${(err as Error).message}`);
          return null;
        }
      },
    [push],
  );

  return {
    apiUrl: t.baseUrl,
    snapshot,
    scenario,
    scenarioError,
    status,
    narration,
    observations,
    visionLatency,
    log,
    feedback,
    reactions,
    placeToken,
    removeToken,
    moveToken,
    advanceStage,
    reset,
    suggest,
    send,
    branchSave: useMemo(() => wrap("branch save", t.branchSave), [wrap, t]),
    branchLoad: useMemo(() => wrap("branch load", t.branchLoad), [wrap, t]),
    compare: useMemo(() => wrap("compare", t.compare), [wrap, t]),
    ask: useCallback(
      async (question: string) => {
        push("info", `Q: ${question}`);
        const r = await wrap("POST /narrate", t.narrate)(question);
        if (r) {
          setNarration(r);
          push("narration", r.text);
        }
        return r;
      },
      [wrap, t, push],
    ),
  };
}

export type WorldHook = ReturnType<typeof useWorldSocket>;

const REASONS: Record<string, string> = {
  invalid_site: "PLACE ON A MARKED PAD",
  invalid_crossing: "PLACE AT HIGHLIGHTED CROSSING",
  resource_exhausted: "RESOURCE ALREADY SPENT",
  already_started: "ALREADY STARTED",
  start_first: "PLACE START FIRST",
  stale_version: "WORLD CHANGED — TRY AGAIN",
  duplicate: "ALREADY APPLIED",
  no_suggestion: "NO BRIDGE NEEDED",
  no_supply_route: "NO SUPPLY ROUTE",
  site_in_hazard: "SITE IN HAZARD ZONE",
  // Codes emitted by backend/world/rules.py and service.py
  outside_site: "PLACE INSIDE THE PAD",
  site_occupied: "PAD ALREADY USED",
  site_exposed: "SITE IN HAZARD ZONE",
  site_in_flood_footprint: "SITE IN FLOOD ZONE",
  site_not_approved: "SITE NOT APPROVED",
  insufficient_budget: "NOT ENOUGH BUDGET",
  crossing_already_open: "CROSSING ALREADY OPEN",
  flood_closure_not_restorable: "FLOODED — BRIDGE CAN'T HELP",
  token_already_placed: "PIECE ALREADY PLACED",
  too_far_from_mapped_road: "PLACE ON A ROAD",
  unknown_branch: "NO SAVED BRANCH",
  last_stage: "LAST STAGE",
  unknown_token: "PIECE NOT ON BOARD",
  start_is_latched: "START STAYS UNTIL RESET",
};

export function reasonText(reason?: string | null): string {
  if (!reason) return "REJECTED";
  return REASONS[reason] ?? reason.replace(/_/g, " ").toUpperCase();
}
