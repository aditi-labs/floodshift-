import type { ActionResult, BranchComparison, Envelope, WorldAction, WorldSnapshot } from "../types/contracts";
import { nowUtc, type ConnectionStatus, type WorldTransport } from "../lib/transport";
import { MOCK_SCENARIO } from "./scenario";
import { SCRIPT } from "./playthrough";

// Stand-in for P3's gateway + P4's WorldService. It does NOT simulate anything:
// it walks the scripted fixture snapshots in SCRIPT and rejects anything off-script.
// Tabs (operator + projector) stay in sync through a BroadcastChannel so both
// windows show the same world_version, as they would with the real /ws.

type Msg =
  | { kind: "action"; action: WorldAction }
  | { kind: "suggest"; expected: number }
  | { kind: "load"; branchId: string }
  | { kind: "save"; name: string }
  | { kind: "sync_request" }
  | { kind: "sync_state"; step: number; branches: Record<string, number>; current: WorldSnapshot };

const CHANNEL = "floodshift-mock-world";

export function createMockTransport(): WorldTransport {
  let step = 0;
  let current: WorldSnapshot = SCRIPT[0].snapshot;
  let seq = 0;
  const branches: Record<string, number> = {};
  const applied = new Set<string>();
  const listeners = new Set<(e: Envelope) => void>();
  const channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel(CHANNEL) : null;

  const emit = (e: Omit<Envelope, "seq" | "sent_at">) => {
    seq += 1;
    const env = { ...e, seq, sent_at: nowUtc() } as Envelope;
    listeners.forEach((l) => l(env));
  };

  const publish = (snap: WorldSnapshot, narration?: string) => {
    current = snap;
    emit({ type: "world.snapshot", payload: snap });
    if (narration) emit({ type: "narration", payload: { text: narration, source: "template" } });
  };

  function reject(action_id: string, reason: string): ActionResult {
    emit({ type: "warning", payload: { code: reason, message: `Rejected: ${reason}` } });
    return { action_id, accepted: false, reason, world_version: current.world_version };
  }

  /** Pure function of (state, action) so every tab reaches the same result. */
  function apply(action: WorldAction): ActionResult {
    if (applied.has(action.action_id)) return reject(action.action_id, "duplicate");
    applied.add(action.action_id);

    if (action.type === "reset") {
      step = 0;
      publish(SCRIPT[0].snapshot, SCRIPT[0].narration);
      return { action_id: action.action_id, accepted: true, world_version: 0 };
    }
    if (action.expected_world_version !== current.world_version) return reject(action.action_id, "stale_version");

    if (action.type === "place_token") {
      if (action.token_type === "disaster_start" && current.phase !== "ready") return reject(action.action_id, "already_started");
      if (action.token_type !== "disaster_start" && current.phase === "ready") return reject(action.action_id, "start_first");
      if ((current.token_inventory[action.token_type!] ?? 0) <= 0) return reject(action.action_id, "resource_exhausted");
      const site = MOCK_SCENARIO.sites.find((s) => s.id === action.site_id);
      if (!site) return reject(action.action_id, "invalid_site");
    }

    const next = SCRIPT[step + 1];
    const e = next?.expect;
    const matches =
      e && e.type === action.type && (e.token_type === undefined || e.token_type === action.token_type) && (e.site_id === undefined || e.site_id === action.site_id);
    if (!matches) {
      const reason = action.token_type === "bridge" ? "invalid_crossing" : "mock_script_expects:" + (next?.label ?? "reset");
      return reject(action.action_id, reason);
    }

    step += 1;
    if (next.observation) {
      emit({ type: "vision.status", payload: { observations: [{ ...next.observation, event_id: `obs-${seq}`, frame_id: seq }] } });
    }
    publish(next.snapshot, next.narration);
    return { action_id: action.action_id, accepted: true, world_version: next.snapshot.world_version };
  }

  function loadBranch(branchId: string): WorldSnapshot {
    const s = branches[branchId] ?? 0;
    step = s;
    const snap = { ...SCRIPT[s].snapshot, branch_id: branchId };
    publish(snap, `Loaded branch "${branchId}" (world ${snap.world_version}).`);
    return snap;
  }

  channel?.addEventListener("message", (ev: MessageEvent<Msg>) => {
    const m = ev.data;
    if (m.kind === "action") apply(m.action);
    else if (m.kind === "suggest") apply(suggestAction(m.expected));
    else if (m.kind === "save") branches[m.name] = step;
    else if (m.kind === "load") loadBranch(m.branchId);
    else if (m.kind === "sync_request") channel.postMessage({ kind: "sync_state", step, branches, current } satisfies Msg);
    else if (m.kind === "sync_state" && m.current.world_version > current.world_version) {
      step = m.step;
      Object.assign(branches, m.branches);
      publish(m.current);
    }
  });

  function suggestAction(expected: number): WorldAction {
    return { action_id: `suggest-v${expected}`, type: "suggest", source: "manual", expected_world_version: expected, timestamp_utc: nowUtc() };
  }

  return {
    kind: "mock",

    connect(onEnvelope, onStatus) {
      listeners.add(onEnvelope);
      onStatus("mock");
      onEnvelope({ type: "world.snapshot", seq: 0, sent_at: nowUtc(), payload: current });
      channel?.postMessage({ kind: "sync_request" } satisfies Msg);
      return () => listeners.delete(onEnvelope);
    },

    getWorld: async () => current,
    getScenario: async () => MOCK_SCENARIO,

    async sendAction(action) {
      channel?.postMessage({ kind: "action", action } satisfies Msg);
      return apply(action);
    },

    async suggest(_goalId, expected) {
      channel?.postMessage({ kind: "suggest", expected } satisfies Msg);
      return apply(suggestAction(expected));
    },

    async branchSave(name) {
      branches[name] = step;
      channel?.postMessage({ kind: "save", name } satisfies Msg);
      emit({ type: "narration", payload: { text: `Saved branch "${name}" at world ${current.world_version}.`, source: "template" } });
      return { branch_id: name };
    },

    async branchLoad(branchId) {
      channel?.postMessage({ kind: "load", branchId } satisfies Msg);
      return loadBranch(branchId);
    },

    async compare(a, b): Promise<BranchComparison> {
      const row = (id: string) => {
        const m = SCRIPT[branches[id] ?? 0].snapshot.metrics;
        return {
          id,
          action: id,
          unmet_food_model: m.unmet_food_model,
          unmet_medical_model: m.unmet_medical_model,
          unmet_refuge_model: m.unmet_refuge_model,
          blocked_roads: m.blocked_roads,
        };
      };
      return { baseline_snapshot_id: "snap-0", branches: [row(a), row(b)], metric_provenance: "educational scenario assumptions (mock fixture)" };
    },

    async narrate(question) {
      const m = current.metrics;
      return {
        source: "template",
        text:
          `[template, mock] "${question}" — In the current model: ${m.blocked_roads} blocked links; unmet food ${m.unmet_food_model}, ` +
          `medical ${m.unmet_medical_model}, refuge ${m.unmet_refuge_model} model units. Outcomes are illustrative.`,
      };
    },
  };
}

export type { ConnectionStatus };
