import type { ActionResult, BranchComparison, Envelope, WorldAction, WorldSnapshot } from "../types/contracts";
import type { ScenarioGeometry } from "../types/scenario";

export type ConnectionStatus = "connecting" | "live" | "stale" | "offline";

/**
 * Everything the UI can ask of the backend (P3's FastAPI gateway, spec §17).
 * The UI never mutates world state itself: it sends a WorldAction and waits for
 * the next world.snapshot envelope.
 */
export interface WorldTransport {
  readonly kind: "live";
  readonly baseUrl: string;
  connect(onEnvelope: (e: Envelope) => void, onStatus: (s: ConnectionStatus) => void): () => void;
  getWorld(): Promise<WorldSnapshot>;
  getScenario(): Promise<ScenarioGeometry>;
  sendAction(action: WorldAction): Promise<ActionResult>;
  /** POST /reset: the gateway reads the current version itself, so reset never goes stale. */
  reset(): Promise<{ reset: boolean; world_version: number }>;
  suggest(goalId: string, expectedVersion: number): Promise<ActionResult>;
  branchSave(name: string): Promise<{ branch_id: string }>;
  branchLoad(branchId: string): Promise<WorldSnapshot>;
  compare(a: string, b: string): Promise<BranchComparison>;
  narrate(question: string): Promise<{ text: string; source: "gemini" | "template" }>;
}

let counter = 0;
export function newActionId(prefix = "ui"): string {
  counter += 1;
  return `${prefix}-${Date.now().toString(36)}-${counter}`;
}

export function nowUtc(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}
