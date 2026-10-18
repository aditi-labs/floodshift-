import { useCallback, useEffect, useRef, useState } from "react";
import { CORE_TOKENS, TOKEN_LABELS, TOKEN_SITE_KIND, type BranchComparison, type TokenType, type WorldSnapshot } from "../types/contracts";
import type { ScenarioGeometry } from "../types/scenario";
import type { WorldHook } from "../hooks/useWorldSocket";
import { GameHud, Objectives, ResultsModal, ScoreBreakdown } from "./GamePanels";
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

type Tool = { kind: "place"; type: TokenType } | { kind: "move"; tokenId: string } | null;

/** First free pad of the right kind; for a bridge, the backend's ghost suggestion first. */
function defaultSite(scenario: ScenarioGeometry, snapshot: WorldSnapshot, type: TokenType) {
  const kind = TOKEN_SITE_KIND[type];
  if (type === "bridge" && snapshot.ghost_suggestion) {
    const ghost = scenario.sites.find((s) => s.id === snapshot.ghost_suggestion!.site_id);
    if (ghost) return ghost;
  }
  const used = new Set(snapshot.tokens.map((t) => t.site_id));
  return scenario.sites.find((s) => s.kind === kind && !used.has(s.id)) ?? scenario.sites.find((s) => s.kind === kind) ?? null;
}

export function OperatorPanel({ world }: { world: WorldHook }) {
  const { snapshot, scenario, scenarioError, status, narration, observations, visionLatency, log, feedback, reactions } = world;
  const [tool, setTool] = useState<Tool>(null);
  const [comparison, setComparison] = useState<BranchComparison | null>(null);
  const [showResults, setShowResults] = useState(false);
  const [speak, setSpeak] = useState(false);
  const [question, setQuestion] = useState("");
  const lastSpoken = useRef<string | null>(null);
  // Test-sequence memory: a bridge was placed and later removed in this session.
  const [bridgeCycle, setBridgeCycle] = useState({ placed: false, removed: false });

  const place = useCallback(
    (type: TokenType, siteId?: string) => {
      if (!scenario || !snapshot) return;
      const site = siteId ? scenario.sites.find((s) => s.id === siteId) : defaultSite(scenario, snapshot, type);
      if (site) world.placeToken(type, site.id, site.board_uv);
    },
    [scenario, snapshot, world],
  );

  const bridgeToken = snapshot?.tokens.find((t) => t.type === "bridge");
  useEffect(() => {
    if (bridgeToken) setBridgeCycle((c) => (c.placed ? c : { placed: true, removed: false }));
    else setBridgeCycle((c) => (c.placed && !c.removed ? { ...c, removed: true } : c));
  }, [bridgeToken]);
  useEffect(() => {
    if (snapshot?.phase === "ready") setBridgeCycle({ placed: false, removed: false });
  }, [snapshot?.phase]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      if (KEY_TOKENS[e.key]) place(KEY_TOKENS[e.key]);
      else if (e.key === "g") world.suggest();
      else if (e.key === "R") world.reset();
      else if (e.key === "Escape") setTool(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [place, world]);

  useEffect(() => {
    if (!speak || !narration || narration.text === lastSpoken.current || !("speechSynthesis" in window)) return;
    lastSpoken.current = narration.text;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(narration.text));
  }, [speak, narration]);

  if (!snapshot || !scenario) {
    return (
      <div className="operator loading">
        <div className="backend-error">
          <h2>{scenarioError ? "Backend unavailable" : "Connecting to the world service…"}</h2>
          <p>
            The UI only shows state computed by the FastAPI WorldService at <code>{world.apiUrl}</code>. There is no offline or scripted fallback.
          </p>
          {scenarioError && <pre>{scenarioError}</pre>}
          <p className="muted">
            Start it with <code>uvicorn backend.main:app --port 8000</code> from the repo root (link: {status}).
          </p>
        </div>
      </div>
    );
  }

  const live = observations.some((o) => o.class_source === "perceptron" || o.class_source === "local_cv");
  const visionMode = observations.some((o) => o.class_source === "perceptron") ? "LIVE_PERCEPTRON" : observations.some((o) => o.class_source === "local_cv") ? "LOCAL_CV" : "MANUAL";
  const connTone = status === "live" ? "ok" : status === "stale" ? "warn" : "bad";
  const latest = reactions[reactions.length - 1];
  const stages = Math.max(1, (scenario.stage_count ?? 2) - 1);
  const game = snapshot.game;

  const onSiteClick = (siteId: string) => {
    const site = scenario.sites.find((s) => s.id === siteId);
    if (!site) return;
    if (tool?.kind === "move") {
      world.moveToken(tool.tokenId, site.id, site.board_uv);
      setTool(null);
      return;
    }
    const type = tool?.kind === "place" ? tool.type : (Object.entries(TOKEN_SITE_KIND).find(([, k]) => k === site.kind)?.[0] as TokenType | undefined);
    if (type) place(type, siteId);
  };

  const has = (type: TokenType) => snapshot.tokens.some((t) => t.type === type);
  const steps: { label: string; done: boolean; action?: () => void; actionLabel?: string }[] = [
    { label: "Reset world", done: snapshot.phase === "ready" && snapshot.tokens.length === 0, action: world.reset, actionLabel: "Reset" },
    { label: "Start flood", done: snapshot.phase === "disaster_active", action: () => place("disaster_start"), actionLabel: "Start" },
    { label: "Place population", done: has("person"), action: () => place("person"), actionLabel: "Place" },
    { label: "Place hospital", done: has("hospital"), action: () => place("hospital"), actionLabel: "Place" },
    { label: "Place food station", done: has("food_shelter"), action: () => place("food_shelter"), actionLabel: "Place" },
    { label: "Place shelter", done: has("shelter"), action: () => place("shelter"), actionLabel: "Place" },
    { label: "See blocked routes & unmet demand", done: (snapshot.service_routes ?? []).some((r) => !r.reachable) || bridgeCycle.placed },
    { label: "Suggest a bridge", done: !!snapshot.ghost_suggestion || bridgeCycle.placed, action: () => world.suggest(), actionLabel: "Suggest" },
    { label: "Place bridge", done: bridgeCycle.placed, action: () => place("bridge"), actionLabel: "Place" },
    { label: "Observe recomputed access", done: !!game?.objectives.find((o) => o.id === "restore_access")?.complete || bridgeCycle.removed },
    { label: "Remove bridge", done: bridgeCycle.removed, action: bridgeToken ? () => world.removeToken(bridgeToken.id) : undefined, actionLabel: "Remove" },
    { label: "Routes recomputed without it", done: bridgeCycle.removed && !bridgeToken && (snapshot.service_routes ?? []).some((r) => !r.reachable) },
    { label: "Compare strategies (Save A / B → Compare)", done: !!comparison },
  ];

  return (
    <div className="operator">
      <header className="op-header">
        <h1>FLOODSHIFT</h1>
        <span className="op-scenario">{scenario.name}</span>
        {!live && <span className="mode-pill" title="Actions go through POST /action — the same reducer a confirmed camera observation uses">MANUAL TEST MODE · real backend · no camera required</span>}
        <StateBadge label="WORLD" value={String(snapshot.world_version).padStart(3, "0")} tone="info" />
        <StateBadge label="PHASE" value={snapshot.phase.replace("_", " ").toUpperCase()} tone={snapshot.phase === "ready" ? "neutral" : "warn"} />
        <StateBadge label="BRANCH" value={snapshot.branch_id} />
        <span className="spacer" />
        <StateBadge label="LINK" value={status.toUpperCase()} tone={connTone} />
        <StateBadge label="VISION" value={visionMode} tone={visionMode === "LIVE_PERCEPTRON" ? "ok" : "warn"} title="A fallback never masquerades as a live model call" />
        <StateBadge label="GEMINI" value={narration?.source === "gemini" ? "LIVE" : "TEXT"} tone={narration?.source === "gemini" ? "ok" : "neutral"} />
        <StateBadge label="MAP" value={scenario.data_label} tone={scenario.data_label === "HOT_DERIVED" ? "ok" : "warn"} title="Measured geographic data source" />
        <StateBadge label="HAZARD" value="SIMULATED" tone="warn" title={scenario.hazard?.geometry_source ?? "scenario hazard"} />
        <StateBadge label="OUTCOMES" value="MODEL" tone="neutral" title="Access, demand and score are model estimates" />
        <a className="op-link" href="/projector" target="floodshift-projector">
          Open projector ↗
        </a>
      </header>
      {status !== "live" && <div className="link-warning">World link is {status.toUpperCase()} — showing the last snapshot received from {world.apiUrl}. Actions will fail until it reconnects.</div>}

      <main className="op-grid">
        <section className="card op-map" style={{ ["--board-aspect" as string]: String(scenario.aspect_ratio ?? 1) }}>
          <h2>
            Board
            <small>
              {tool?.kind === "place" ? `click a pad to place ${TOKEN_LABELS[tool.type]} · Esc cancels` : tool?.kind === "move" ? "click the destination pad · Esc cancels" : "click a pad to place its matching piece"}
            </small>
          </h2>
          {latest?.headline && (
            <div key={latest.key} className={`reaction-toast tone-${latest.headline.tone}`}>
              {latest.headline.text}
              {latest.scoreDelta != null && <b>{latest.scoreDelta > 0 ? " +" : " "}{latest.scoreDelta}</b>}
            </div>
          )}
          <MapProjection scenario={scenario} snapshot={snapshot} feedback={feedback} reactions={reactions} showBasemap compact onSiteClick={onSiteClick} />
          <p className="muted small">
            Flood art: {scenario.hazard?.geometry_source ?? "none"}. Routes, closures and demand come from the backend snapshot.
          </p>
        </section>

        <section className="card op-game">
          <h2>
            Response <small>game layer</small>
            <button className="btn btn-sm push-right" onClick={() => setShowResults(true)} disabled={game?.status !== "active"}>
              Results
            </button>
          </h2>
          <GameHud snapshot={snapshot} scenario={scenario} />
          <ScoreBreakdown game={game} />
          <h3>Objectives</h3>
          <Objectives game={game} />
        </section>

        <section className="card op-controls">
          <h2>Controls <small>keys 1–6 · G suggest · shift+R reset</small></h2>
          <div className="btn-grid">
            {CORE_TOKENS.map((t, i) => (
              <button
                key={t}
                className={`btn btn-token ${tool?.kind === "place" && tool.type === t ? "active" : ""}`}
                onClick={() => place(t)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  setTool(tool?.kind === "place" && tool.type === t ? null : { kind: "place", type: t });
                }}
                title="Click: place at the first free pad · right-click: choose the pad on the board"
              >
                <TokenIcon type={t} /> <span>{i + 1}</span> {TOKEN_LABELS[t]} <em>×{snapshot.token_inventory[t] ?? 0}</em>
              </button>
            ))}
          </div>
          <div className="btn-row">
            <button className="btn btn-ghost" onClick={() => world.suggest()}>Suggest bridge</button>
            <button className="btn" onClick={() => world.advanceStage()} disabled={snapshot.phase !== "disaster_active" || snapshot.simulation_stage >= stages} title="Advance the simulated flood to its next scenario stage">
              Advance flood stage
            </button>
            <button className="btn" onClick={() => world.reset()}>Reset</button>
          </div>
          <h3>Pieces on the board</h3>
          <ul className="placed">
            {snapshot.tokens.length === 0 && <li className="muted">None placed.</li>}
            {snapshot.tokens.map((t) => (
              <li key={t.id}>
                <TokenIcon type={t.type} size={14} /> {TOKEN_LABELS[t.type]} <code>{t.site_id}</code>
                {t.type !== "disaster_start" && (
                  <span className="placed-actions">
                    <button className={`btn btn-sm ${tool?.kind === "move" && tool.tokenId === t.id ? "active" : ""}`} onClick={() => setTool({ kind: "move", tokenId: t.id })}>
                      move
                    </button>
                    <button className="btn btn-sm" onClick={() => world.removeToken(t.id)}>remove</button>
                  </span>
                )}
              </li>
            ))}
          </ul>
          <h3>Strategy comparison</h3>
          <div className="btn-row">
            <button className="btn" onClick={() => world.branchSave("A")}>Save A</button>
            <button className="btn" onClick={() => world.branchSave("B")}>Save B</button>
            <button className="btn" onClick={() => world.branchLoad("A")}>Load A</button>
            <button className="btn" onClick={() => world.branchLoad("B")}>Load B</button>
            <button className="btn" onClick={async () => setComparison(await world.compare("A", "B"))}>Compare A/B</button>
          </div>
          {comparison && <Comparison c={comparison} onClose={() => setComparison(null)} />}
        </section>

        <section className="card op-test">
          <h2>Hardware-free test sequence <small>steps tick from live state</small></h2>
          <ol className="steps">
            {steps.map((s, i) => (
              <li key={i} className={s.done ? "done" : ""}>
                <span className="obj-check">{s.done ? "✓" : i + 1}</span>
                <span>{s.label}</span>
                {s.action && !s.done && (
                  <button className="btn btn-sm push-right" onClick={s.action}>
                    {s.actionLabel}
                  </button>
                )}
              </li>
            ))}
          </ol>
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

        <section className="card op-vision">
          <h2>
            Camera / Perceptron <small>{visionLatency != null ? `${visionLatency} ms` : "no observation yet — manual mode"}</small>
          </h2>
          {observations.length === 0 ? (
            <p className="muted">No camera observations. Manual placements use the same reducer as a confirmed observation.</p>
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
          <table className="facilities">
            <tbody>
              {snapshot.facilities.map((f) => (
                <tr key={f.id}>
                  <td>
                    <TokenIcon type={f.type} size={14} /> {TOKEN_LABELS[f.type]}
                  </td>
                  <td>
                    {f.used_capacity_model}/{f.capacity_model} cap
                  </td>
                  <td className={f.reachable && (f.active ?? true) ? "ok" : "bad"}>{f.reachable ? ((f.active ?? true) ? "supplied" : "inactive") : "cut off"}</td>
                </tr>
              ))}
            </tbody>
          </table>
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
        Map: HOT/OSM mapped geography © OpenStreetMap contributors · Flood: simulated educational scenario · Access, demand and score: model estimates — not a real disaster prediction
      </footer>
      {showResults && <ResultsModal snapshot={snapshot} onClose={() => setShowResults(false)} />}
    </div>
  );
}

function Comparison({ c, onClose }: { c: BranchComparison; onClose: () => void }) {
  const keys = ["game_score", ...Object.keys(c.branches[0] ?? {}).filter((k) => !["id", "action", "game_score"].includes(k))];
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
          <tr>
            <td>pieces</td>
            {c.branches.map((b, i) => (
              <td key={b.id} className={i === 0 ? "branch-a" : "branch-b"}>
                {b.action}
              </td>
            ))}
          </tr>
          {keys.map((k) => (
            <tr key={k}>
              <td>{k.replace(/_/g, " ")}</td>
              {c.branches.map((b, i) => (
                <td key={b.id} className={i === 0 ? "branch-a" : "branch-b"}>
                  {typeof b[k] === "number" ? +(b[k] as number).toFixed(3) : String(b[k] ?? "–")}
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
