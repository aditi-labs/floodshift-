import { describe, expect, it } from "vitest";
import type { WorldSnapshot } from "../types/contracts";
// Real snapshots produced by the backend reducer (python -m backend.world.demo --write-fixtures).
import beforeBridge from "../../../scenarios/nepal_rasuwa_hot_v1/data/fixture_world.json";
import afterBridge from "../../../scenarios/nepal_rasuwa_hot_v1/data/fixture_after_bridge.json";
import { diffSnapshots, snapshotKey } from "./worldReactions";

const before = beforeBridge as unknown as WorldSnapshot;
const after = afterBridge as unknown as WorldSnapshot;
const clone = (s: WorldSnapshot): WorldSnapshot => JSON.parse(JSON.stringify(s));

describe("diffSnapshots", () => {
  it("reacts to a real bridge placement with backend-backed changes only", () => {
    const set = diffSnapshots(before, after)!;
    expect(set.key).toBe(snapshotKey(after));
    expect(set.replaced).toBe(false);
    const kinds = set.reactions.map((r) => r.kind);
    expect(kinds).toContain("edge_restored");
    expect(kinds).toContain("route_opened");
    expect(set.reactions.find((r) => r.kind === "edge_restored")!.edge_ids).toEqual(["crossing_east_road"]);
    // Every opened route is one the backend now marks reachable, drawn on its own geometry.
    for (const r of set.reactions.filter((x) => x.kind === "route_opened")) {
      const route = after.service_routes!.find((s) => s.service === r.service && s.reachable && s.edge_ids.join() === r.edge_ids!.join());
      expect(route).toBeDefined();
      expect(r.path).toEqual(route!.board_uv);
    }
    expect(set.headline).toEqual({ text: "BRIDGE DEPLOYED — EASTERN ACCESS RESTORED", tone: "good" });
    expect(set.scoreDelta).toBe(after.game!.score - before.game!.score);
  });

  it("does not react to the same snapshot delivered twice (socket + /world refetch)", () => {
    expect(diffSnapshots(after, clone(after))).toBeNull();
  });

  it("ignores updates that change no outcome (suggestion ghost, narration, bookmarks)", () => {
    const ghostOnly = clone(before);
    ghostOnly.world_version += 1;
    ghostOnly.ghost_suggestion = null;
    ghostOnly.narration_event = { event_type: "branch_saved", model_only: true };
    expect(diffSnapshots(before, ghostOnly)).toBeNull();
  });

  it("reports removal as lost access and a negative score delta", () => {
    const removed = clone(before);
    removed.world_version = after.world_version + 1;
    const set = diffSnapshots(after, removed)!;
    expect(set.reactions.map((r) => r.kind)).toEqual(expect.arrayContaining(["edge_blocked", "route_lost", "token_removed"]));
    expect(set.headline?.text).toBe("BRIDGE REMOVED — ACCESS LOST");
    expect(set.scoreDelta).toBeLessThan(0);
  });

  it("never names a direction or success when the bridge opened no route", () => {
    const useless = clone(before);
    useless.world_version = before.world_version + 1;
    const bridge = after.tokens.find((t) => t.type === "bridge")!;
    useless.tokens = [...useless.tokens, { ...bridge, site_id: "crossing_south" }];
    useless.edges = useless.edges.map((e) => (e.id === "crossing_south_road" ? { ...e, blocked: false } : e));
    const set = diffSnapshots(before, useless)!;
    expect(set.reactions.some((r) => r.kind === "route_opened")).toBe(false);
    expect(set.headline?.text).toBe("BRIDGE DEPLOYED — NO NEW ACCESS");
  });

  it("treats reset as a replacement, not an achievement", () => {
    const reset = clone(after);
    reset.world_version += 1;
    reset.phase = "ready";
    reset.simulation_stage = 0;
    reset.tokens = [];
    const set = diffSnapshots(after, reset)!;
    expect(set.replaced).toBe(true);
    expect(set.scoreDelta).toBeNull();
    expect(set.headline?.text).toBe("BOARD RESET");
    expect(set.reactions.map((r) => r.kind)).toEqual(["flood_recede"]);
  });

  it("announces the flood when the backend advances from the dry stage", () => {
    const dry = clone(before);
    dry.phase = "ready";
    dry.simulation_stage = 0;
    dry.world_version = 0;
    dry.tokens = [];
    const started = clone(dry);
    started.world_version = 1;
    started.phase = "disaster_active";
    started.simulation_stage = 1;
    const set = diffSnapshots(dry, started)!;
    expect(set.reactions[0]).toMatchObject({ kind: "flood_stage", stage: 1 });
    expect(set.headline?.text).toBe("FLOOD ARRIVING");
  });
});
