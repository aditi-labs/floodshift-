import type {
  ActionResult,
  BranchComparison,
  Envelope,
  NarrateResponse,
  SuggestResponse,
  WorldAction,
  WorldSnapshot,
} from "../types/contracts";
import type { ScenarioGeometry } from "../types/scenario";
import { newActionId, nowUtc, type ConnectionStatus, type WorldTransport } from "./transport";

const STALE_AFTER_MS = 10_000;

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = "";
    try {
      detail = JSON.stringify((await res.json()).detail ?? "");
    } catch {
      /* body was not JSON */
    }
    throw new Error(`${res.status} ${res.statusText}${detail ? " " + detail : ""}`);
  }
  return (await res.json()) as T;
}

export function createLiveTransport(baseUrl: string): WorldTransport {
  const http = baseUrl.replace(/\/$/, "");
  const wsUrl = http.replace(/^http/, "ws") + "/ws";

  const post = <T>(path: string, body: unknown) =>
    fetch(http + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(json<T>);

  return {
    kind: "live",
    baseUrl: http,

    connect(onEnvelope, onStatus) {
      let ws: WebSocket | null = null;
      let closed = false;
      let retry = 0;
      let staleTimer: number | undefined;
      let heartbeat: number | undefined;

      const markFresh = () => {
        window.clearTimeout(staleTimer);
        onStatus("live");
        staleTimer = window.setTimeout(() => onStatus("stale"), STALE_AFTER_MS);
      };

      const open = () => {
        onStatus("connecting");
        ws = new WebSocket(wsUrl);
        ws.onopen = async () => {
          retry = 0;
          markFresh();
          heartbeat = window.setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send("ping"), 5000);
          // After any (re)connect, pull the current snapshot rather than trusting old state.
          try {
            const snap = await fetch(http + "/world").then(json<WorldSnapshot>);
            onEnvelope({ type: "world.snapshot", seq: -1, sent_at: nowUtc(), payload: snap });
          } catch {
            /* the socket will still deliver snapshots */
          }
        };
        ws.onmessage = (ev) => {
          markFresh();
          try {
            onEnvelope(JSON.parse(ev.data) as Envelope);
          } catch {
            /* ignore non-JSON heartbeats */
          }
        };
        ws.onclose = () => {
          window.clearInterval(heartbeat);
          if (closed) return;
          onStatus("offline");
          retry = Math.min(retry + 1, 5);
          window.setTimeout(open, 500 * 2 ** retry);
        };
        ws.onerror = () => ws?.close();
      };

      open();
      return () => {
        closed = true;
        window.clearTimeout(staleTimer);
        window.clearInterval(heartbeat);
        ws?.close();
      };
    },

    getWorld: () => fetch(http + "/world").then(json<WorldSnapshot>),

    // No fallback geometry: if the gateway is down the UI says so instead of drawing a fake board.
    getScenario: () => fetch(http + "/scenario").then(json<ScenarioGeometry>),

    sendAction: (action: WorldAction) => post<ActionResult>("/action", action),
    reset: () => post<{ reset: boolean; world_version: number }>("/reset", {}),

    // backend returns {has_suggestion, suggestion, world_version}; the ghost itself arrives
    // in the next snapshot's ghost_suggestion.
    suggest: async (goalId) => {
      const r = await post<SuggestResponse>("/plan/suggest", { goal_id: goalId });
      return {
        action_id: newActionId("suggest"),
        accepted: r.has_suggestion,
        world_version: r.world_version,
        rejection_reason: r.has_suggestion ? null : (r.rejection_reason ?? "no_suggestion"),
      };
    },

    branchSave: (name) => post<{ branch_id: string }>("/branch/save", { name }),
    branchLoad: (branchId) => post<WorldSnapshot>("/branch/load", { branch_id: branchId }),
    compare: (a, b) => fetch(`${http}/branch/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`).then(json<BranchComparison>),
    narrate: async (question) => {
      const r = await post<NarrateResponse>("/narrate", { question });
      // Never label the state-derived fallback as a live Gemini answer.
      return { text: r.answer, source: r.mode === "LIVE" ? ("gemini" as const) : ("template" as const) };
    },
  };
}

export type { ConnectionStatus };
