import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ActionResult, Envelope, ObjectObservation, TokenType, UV, WorldAction, WorldSnapshot } from "../types/contracts";
import type { ScenarioGeometry } from "../types/scenario";
import { createLiveTransport } from "../lib/liveTransport";
import { createMockTransport } from "../mocks/mockTransport";
import { setBoardAspect } from "../types/geometry";
import { newActionId, nowUtc, type ConnectionStatus, type WorldTransport } from "../lib/transport";

export const USE_MOCKS = String(import.meta.env.VITE_USE_MOCKS ?? "true") !== "false";
const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

let shared: WorldTransport | null = null;
function transport(): WorldTransport {
  shared ??= USE_MOCKS ? createMockTransport() : createLiveTransport(API_URL);
  return shared;
}

export interface LogEntry {
  at: string;
  kind: "accepted" | "rejected" | "info" | "warning" | "narration" | "vision";
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

export function useWorldSocket() {
  const t = useMemo(transport, []);
  const [snapshot, setSnapshot] = useState<WorldSnapshot | null>(null);
  const [scenario, setScenario] = useState<ScenarioGeometry | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [narration, setNarration] = useState<{ text: string; source: string } | null>(null);
  const [observations, setObservations] = useState<ObjectObservation[]>([]);
  const [visionLatency, setVisionLatency] = useState<number | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [feedback, setFeedback] = useState<Feedback[]>([]);
  const lastSeq = useRef(-Infinity);
  const snapRef = useRef<WorldSnapshot | null>(null);

  const push = useCallback((kind: LogEntry["kind"], text: string) => {
    setLog((l) => [{ at: new Date().toLocaleTimeString(), kind, text }, ...l].slice(0, 80));
  }, []);

  const flash = useCallback((kind: Feedback["kind"], board_uv: UV, label: string, ms = 2600) => {
    const f: Feedback = { id: `${kind}-${Math.random().toString(36).slice(2)}`, kind, board_uv, label, until: Date.now() + ms };
    setFeedback((list) => [...list.filter((x) => x.until > Date.now()), f]);
    window.setTimeout(() => setFeedback((list) => list.filter((x) => x.id !== f.id)), ms);
  }, []);

  useEffect(() => {
    t.getScenario().then((s) => {
      setBoardAspect(s.aspect_ratio);
      setScenario(s);
    });
    const onEnvelope = (e: Envelope) => {
      // A new connection (possibly to a restarted server) restarts the sequence.
      if (e.type === "server.hello") lastSeq.current = -Infinity;
      if (typeof e.seq === "number" && e.seq > 0 && e.seq <= lastSeq.current) return;
      if (typeof e.seq === "number" && e.seq > 0) lastSeq.current = e.seq;
      switch (e.type) {
        case "world.snapshot": {
          const prev = snapRef.current;
          // Ignore out-of-order snapshots on the same branch (reset/branch load lowers the version legitimately).
          if (prev && e.payload.branch_id === prev.branch_id && e.payload.world_version < prev.world_version && e.payload.world_version !== 0) return;
          snapRef.current = e.payload;
          setSnapshot(e.payload);
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
  }, [t, push, flash]);

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
        return handleResult(r, `${action.type}${action.token_type ? " " + action.token_type : ""}${action.site_id ? " @ " + action.site_id : ""}`, action.board_uv);
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

  const reset = useCallback(() => send({ type: "reset" }), [send]);

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
    transportKind: t.kind,
    snapshot,
    scenario,
    status,
    narration,
    observations,
    visionLatency,
    log,
    feedback,
    placeToken,
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
};

export function reasonText(reason?: string | null): string {
  if (!reason) return "REJECTED";
  if (reason.startsWith("mock_script_expects:")) return "NOT IN DEMO SCRIPT";
  return REASONS[reason] ?? reason.replace(/_/g, " ").toUpperCase();
}
