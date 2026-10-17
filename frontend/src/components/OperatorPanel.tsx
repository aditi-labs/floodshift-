import { useCallback, useEffect, useRef, useState } from "react";
import { CORE_TOKENS, TOKEN_LABELS, TOKEN_SITE_KIND, type BranchComparison, type TokenType } from "../types/contracts";
import type { WorldHook } from "../hooks/useWorldSocket";
import { SCRIPT } from "../mocks/playthrough";
import { MapProjection } from "./MapProjection";
import { StateBadge } from "./StateBadge";
import { TokenIcon } from "./TokenIcon";

// Operator laptop HUD (spec §16 Screen B). Every button emits the same WorldAction
// the camera would; results come back as snapshots — nothing is computed here.

const KEY_TOKENS: Record<string, TokenType> = {
  "1": "disaster_start",
  "2": "person",
  "3": "hospital",
  "4": "food_shelter",
  "5": "shelter",
  "6": "bridge",
};

export function OperatorPanel({ world }: { world: WorldHook }) {
  const { snapshot, scenario, status, narration, observations, visionLatency, log, feedback, transportKind } = world;
  const [tool, setTool] = useState<TokenType | null>(null);
  const [comparison, setComparison] = useState<BranchComparison | null>(null);
  const [speak, setSpeak] = useState(false);
  const [question, setQuestion] = useState("");
  const lastSpoken = useRef<string | null>(null);

  const defaultSite = useCallback(
    (type: TokenType) => {
      if (!scenario) return null;
      if (type === "bridge" && snapshot?.ghost_suggestion) {
        return scenario.sites.find((s) => s.id === snapshot.ghost_suggestion!.site_id) ?? null;
      }
      const kind = TOKEN_SITE_KIND[type];
      // Prefer the site the demo script expects so keyboard play follows the happy path.
      const scripted = SCRIPT.find((s) => s.expect?.token_type === type)?.expect?.site_id;
      return scenario.sites.find((s) => s.id === scripted && s.kind === kind) ?? scenario.sites.find((s) => s.kind === kind) ?? null;
    },
    [scenario, snapshot],
  );

  const place = useCallback(
    (type: TokenType, siteId?: string) => {
      const site = siteId ? scenario?.sites.find((s) => s.id === siteId) : defaultSite(type);
      if (!site) return;
      world.placeToken(type, site.id, site.board_uv);
    },
    [scenario, defaultSite, world],
  );

  const nextScripted = useCallback(() => {
    if (!snapshot) return;
    const i = SCRIPT.findIndex((s) => s.snapshot.world_version === snapshot.world_version);
    const next = SCRIPT[i + 1]?.expect;
    if (!next) return;
    if (next.type === "suggest") world.suggest();
    else if (next.type === "place_token" && next.token_type) place(next.token_type, next.site_id);
  }, [snapshot, world, place]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      if (KEY_TOKENS[e.key]) place(KEY_TOKENS[e.key]);
      else if (e.key === "g") world.suggest();
      else if (e.key === "R") world.reset();
      else if (e.key === " " && transportKind === "mock") {
        e.preventDefault();
        nextScripted();
      } else if (e.key === "Escape") setTool(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [place, world, nextScripted, transportKind]);

  useEffect(() => {
    if (!speak || !narration || narration.text === lastSpoken.current || !("speechSynthesis" in window)) return;
    lastSpoken.current = narration.text;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(narration.text));
  }, [speak, narration]);

  if (!snapshot || !scenario) return <div className="operator loading">Connecting to world… ({status})</div>;

  const m = snapshot.metrics;
  const people = snapshot.population_demand.reduce((n, d) => n + d.people_model, 0);
  const visionMode = transportKind === "mock" ? "REPLAY" : observations.some((o) => o.class_source === "perceptron") ? "LIVE_PERCEPTRON" : "MANUAL";
  const connTone = status === "live" ? "ok" : status === "mock" ? "info" : status === "stale" ? "warn" : "bad";

  const onSiteClick = (siteId: string) => {
    const site = scenario.sites.find((s) => s.id === siteId);
    if (!site) return;
    const type = tool ?? (Object.entries(TOKEN_SITE_KIND).find(([, k]) => k === site.kind)?.[0] as TokenType | undefined);
    if (type) place(type, siteId);
  };

  return (
    <div className="operator">
      <header className="op-header">
        <h1>FLOODSHIFT</h1>
        <span className="op-scenario">Nepal 2026</span>
        <StateBadge label="WORLD" value={String(snapshot.world_version).padStart(3, "0")} tone="info" />
        <StateBadge label="PHASE" value={snapshot.phase.replace("_", " ").toUpperCase()} tone={snapshot.phase === "ready" ? "neutral" : "warn"} />
        <StateBadge label="BRANCH" value={snapshot.branch_id} />
        <span className="spacer" />
        <StateBadge label="LINK" value={status.toUpperCase()} tone={connTone} />
        <StateBadge label="VISION" value={visionMode} tone={visionMode === "LIVE_PERCEPTRON" ? "ok" : "warn"} title="A fallback never masquerades as a live model call" />
        <StateBadge label="PROJECTOR" value="SCREEN" tone="neutral" title="Set CALIBRATED once the projector view is aligned" />
        <StateBadge label="GEMINI" value={narration?.source === "gemini" ? "LIVE" : "TEXT"} tone={narration?.source === "gemini" ? "ok" : "neutral"} />
        <StateBadge label="DATA" value={scenario.data_label} tone={scenario.data_label === "HOT_DERIVED" ? "ok" : "warn"} />
        <a className="op-link" href="/projector" target="floodshift-projector">
          Open projector ↗
        </a>
      </header>

      <main className="op-grid">
        <section className="card op-map">
          <h2>
            Board <small>{tool ? `click a pad to place ${TOKEN_LABELS[tool]} · Esc cancels` : "click a pad to place its matching piece"}</small>
          </h2>
          <MapProjection scenario={scenario} snapshot={snapshot} feedback={feedback} showBasemap compact onSiteClick={onSiteClick} />
        </section>

        <section className="card op-vision">
          <h2>
            Camera / Perceptron <small>{visionLatency != null ? `${visionLatency} ms` : transportKind === "mock" ? "replay fixture" : "no request yet"}</small>
          </h2>
          {observations.length === 0 ? (
            <p className="muted">No observations yet.</p>
          ) : (
            <ul className="obs-list">
              {observations.map((o) => (
                <li key={o.event_id}>
                  <TokenIcon type={o.object_type} />
                  <b>{o.object_type}</b> <code>{o.token_id}</code>
                  <span className={`pill pill-${o.vision_status}`}>{o.vision_status}</span>
                  <span className="muted">
                    {o.class_source} · uv {o.board_uv.map((n) => n.toFixed(2)).join(",")}
                    {o.stable_ms ? ` · stable ${o.stable_ms}ms` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card op-metrics">
          <h2>World metrics <small>model units</small></h2>
          <div className="metric-grid">
            <Metric label="Unmet food" value={m.unmet_food_model} of={people ? snapshot.population_demand.reduce((n, d) => n + d.need_food, 0) : undefined} tone="food" />
            <Metric label="Unmet care" value={m.unmet_medical_model} of={people ? snapshot.population_demand.reduce((n, d) => n + d.need_medical, 0) : undefined} tone="medical" />
            <Metric label="Unmet refuge" value={m.unmet_refuge_model} of={people ? snapshot.population_demand.reduce((n, d) => n + d.need_refuge, 0) : undefined} tone="refuge" />
            <Metric label="Blocked roads" value={m.blocked_roads} tone="bad" />
          </div>
          <table className="facilities">
            <tbody>
              {snapshot.facilities.map((f) => (
                <tr key={f.id}>
                  <td>
                    <TokenIcon type={f.type} size={14} /> {TOKEN_LABELS[f.type]}
                  </td>
                  <td>
                    {f.used_capacity_model}/{f.capacity_model}
                  </td>
                  <td className={f.reachable ? "ok" : "bad"}>{f.reachable ? "reachable" : "cut off"}</td>
                </tr>
              ))}
              {snapshot.facilities.length === 0 && (
                <tr>
                  <td className="muted">No services placed.</td>
                </tr>
              )}
            </tbody>
          </table>
          <div className="inventory">
            {CORE_TOKENS.map((t) => (
              <span key={t} className="inv" title={TOKEN_LABELS[t]}>
                <TokenIcon type={t} size={14} /> {snapshot.token_inventory[t] ?? 0}
              </span>
            ))}
          </div>
        </section>

        <section className="card op-controls">
          <h2>Demo controls <small>keys 1–6 · G suggest · shift+R reset{transportKind === "mock" ? " · space next" : ""}</small></h2>
          <div className="btn-grid">
            {CORE_TOKENS.map((t, i) => (
              <button
                key={t}
                className={`btn btn-token ${tool === t ? "active" : ""}`}
                onClick={() => place(t)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  setTool(tool === t ? null : t);
                }}
                title="Click: place at default pad · right-click: choose pad on the board"
              >
                <TokenIcon type={t} /> <span>{i + 1}</span> {TOKEN_LABELS[t]}
              </button>
            ))}
          </div>
          <div className="btn-row">
            <button className="btn btn-ghost" onClick={() => world.suggest()}>Suggest bridge</button>
            <button className="btn" onClick={() => world.reset()}>Reset</button>
            {transportKind === "mock" && <button className="btn" onClick={nextScripted}>Next ▶</button>}
          </div>
          <div className="btn-row">
            <button className="btn" onClick={() => world.branchSave("A")}>Save A</button>
            <button className="btn" onClick={() => world.branchLoad("baseline")}>Baseline</button>
            <button className="btn" onClick={() => world.branchSave("B")}>Save B</button>
            <button className="btn" onClick={async () => setComparison(await world.compare("A", "B"))}>Compare A/B</button>
            <button className="btn" onClick={() => world.branchSave("baseline")} title="Mark the current state as the rewind point">Set baseline</button>
          </div>
          {comparison && <Comparison c={comparison} onClose={() => setComparison(null)} />}
        </section>

        <section className="card op-narration">
          <h2>
            Coordinator <small>{narration?.source === "gemini" ? "Gemini · grounded in world state" : "state-derived template"}</small>
            <label className="speak">
              <input type="checkbox" checked={speak} onChange={(e) => setSpeak(e.target.checked)} /> speak
            </label>
          </h2>
          <p className="narration">{narration?.text ?? "—"}</p>
          <form
            className="ask"
            onSubmit={async (e) => {
              e.preventDefault();
              if (!question.trim()) return;
              await world.ask(question.trim());
              setQuestion("");
            }}
          >
            <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask: Why is the village cut off?" />
            <button className="btn">Ask</button>
          </form>
        </section>

        <section className="card op-log">
          <h2>Event log</h2>
          <ol className="log">
            {log.map((l, i) => (
              <li key={i} className={`log-${l.kind}`}>
                <time>{l.at}</time> {l.text}
              </li>
            ))}
          </ol>
        </section>
      </main>

      <footer className="op-footer">
        History: UNOSAT 4259 (preliminary) · HOT/OSM mapped geography © OpenStreetMap contributors · Current intervention: educational counterfactual — not a real disaster prediction
      </footer>
    </div>
  );
}

function Metric({ label, value, of, tone }: { label: string; value: number; of?: number; tone: string }) {
  return (
    <div className={`metric metric-${tone}`}>
      <div className="metric-value">
        {value}
        {of != null && <small>/{of}</small>}
      </div>
      <div className="metric-label">{label}</div>
    </div>
  );
}

function Comparison({ c, onClose }: { c: BranchComparison; onClose: () => void }) {
  const keys = Object.keys(c.branches[0] ?? {}).filter((k) => k !== "id" && k !== "action");
  return (
    <div className="comparison">
      <table>
        <thead>
          <tr>
            <th>metric</th>
            {c.branches.map((b, i) => (
              <th key={b.id} className={i === 0 ? "branch-a" : "branch-b"}>
                {b.id}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {keys.map((k) => (
            <tr key={k}>
              <td>{k.replace(/_/g, " ")}</td>
              {c.branches.map((b, i) => (
                <td key={b.id} className={i === 0 ? "branch-a" : "branch-b"}>
                  {String(b[k])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">
        {c.metric_provenance} <button className="btn btn-sm" onClick={onClose}>close</button>
      </p>
    </div>
  );
}
