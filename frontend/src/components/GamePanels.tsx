import type { GameOutcomes, GameState, WorldSnapshot } from "../types/contracts";
import { TOKEN_LABELS } from "../types/contracts";
import type { ScenarioGeometry } from "../types/scenario";
import { TokenIcon } from "./TokenIcon";

// Game layer views. Every number is read from snapshot.game / snapshot.metrics, which
// backend/world/game.py computes from the authoritative state. Nothing is scored here.

const PART_LABELS: Record<string, string> = {
  access: "Service access gained",
  needs_met: "Needs met vs no response",
  communities: "Communities reconnected",
  unmet_penalty: "Unmet need",
  spend_penalty: "Budget spent",
  ineffective_penalty: "Ineffective pieces",
};

export function GameHud({ snapshot, scenario }: { snapshot: WorldSnapshot; scenario: ScenarioGeometry }) {
  const m = snapshot.metrics;
  const game = snapshot.game;
  const communities = snapshot.population_demand.length;
  const people = snapshot.population_demand.reduce((n, d) => n + d.people_model, 0);
  const supported = Math.min(m.people_reachable_for_medical, m.people_reachable_for_food, m.people_reachable_for_shelter);
  const stages = Math.max(1, (scenario.stage_count ?? 2) - 1);
  const unit = snapshot.population_demand.some((d) => d.headcount_known === false) ? "groups" : "model people";
  return (
    <div className="hud">
      <div className="hud-score" title={game?.formula}>
        <span className="hud-score-value">{game?.status === "active" ? game.score : "—"}</span>
        <span className="hud-score-label">GAME SCORE</span>
      </div>
      <div className="hud-grid">
        <Stat label="Community access" value={`${m.reachable_communities ?? 0}/${communities}`} hint="model communities reaching the supply depot" />
        <Stat label="People supported" value={`${supported}/${people}`} hint={`${unit} reaching all three services`} />
        <Stat label="Medical access" value={`${m.people_reachable_for_medical}/${people}`} tone="medical" />
        <Stat label="Food access" value={`${m.people_reachable_for_food}/${people}`} tone="food" />
        <Stat label="Shelter access" value={`${m.people_reachable_for_shelter}/${people}`} tone="refuge" />
        <Stat label="Resources left" value={`${snapshot.budget_remaining_model ?? "–"}${game?.budget_total_model != null ? `/${game.budget_total_model}` : ""}`} />
        <Stat label="Disaster stage" value={snapshot.phase === "disaster_active" ? `${snapshot.simulation_stage}/${stages}` : "dry"} tone={snapshot.phase === "disaster_active" ? "bad" : undefined} />
      </div>
      <p className="muted small">
        Population is in {unit} (scenario assumptions, no verified headcount). {game?.label}
      </p>
    </div>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className={`stat ${tone ? "stat-" + tone : ""}`} title={hint}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

export function Objectives({ game }: { game?: GameState | null }) {
  if (!game || game.status !== "active") return <p className="muted">Objectives appear when the flood starts.</p>;
  return (
    <ul className="objectives">
      {game.objectives.map((o) => (
        <li key={o.id} className={o.complete ? "done" : ""}>
          <span className="obj-check">{o.complete ? "✓" : "○"}</span>
          <div>
            <b>{o.label}</b>
            <small>{o.detail}</small>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function ScoreBreakdown({ game }: { game?: GameState | null }) {
  if (!game || game.status !== "active") return null;
  return (
    <details className="score-breakdown">
      <summary>How the score is computed</summary>
      <table>
        <tbody>
          {Object.entries(game.score_parts).map(([k, v]) => (
            <tr key={k}>
              <td>{PART_LABELS[k] ?? k}</td>
              <td className={(v ?? 0) >= 0 ? "ok" : "bad"}>{(v ?? 0) > 0 ? "+" : ""}{v}</td>
            </tr>
          ))}
          <tr className="total">
            <td>Total</td>
            <td>{game.score}</td>
          </tr>
        </tbody>
      </table>
      <p className="muted small">{game.formula}. Weights live in backend/world/game.py (SCORING). The score is recomputed from the current state, so placing and removing pieces cannot farm points.</p>
    </details>
  );
}

const OUTCOME_ROWS: [keyof GameOutcomes, string][] = [
  ["reachable_communities", "Communities reaching supplies"],
  ["people_reachable_for_medical", "People reaching medical"],
  ["people_reachable_for_food", "People reaching food"],
  ["people_reachable_for_shelter", "People reaching shelter"],
  ["unmet_medical_model", "Unmet medical"],
  ["unmet_food_model", "Unmet food"],
  ["unmet_refuge_model", "Unmet shelter"],
];

export function ResultsModal({ snapshot, onClose }: { snapshot: WorldSnapshot; onClose: () => void }) {
  const game = snapshot.game;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Disaster outcome">
        <header>
          <h2>Disaster outcome</h2>
          <button className="btn btn-sm" onClick={onClose}>close</button>
        </header>
        {!game || game.status !== "active" || !game.baseline || !game.current ? (
          <p className="muted">Start the flood and place response pieces to see an outcome.</p>
        ) : (
          <>
            <div className="results-score">
              <span>{game.score}</span>
              <small>final game score · {game.label}</small>
            </div>
            <div className="results-facts">
              <Fact label="Interventions used" value={game.interventions.length} />
              <Fact label="Budget spent" value={`${game.budget_spent_model}/${game.budget_total_model}`} />
              <Fact label="Communities reconnected" value={game.communities_reconnected ?? 0} />
              <Fact label="Unmet needs left" value={`${game.unmet_total_model}/${game.total_need_model}`} />
            </div>
            <table className="results-table">
              <thead>
                <tr>
                  <th>Outcome (model units)</th>
                  <th>No response</th>
                  <th>Your response</th>
                </tr>
              </thead>
              <tbody>
                {OUTCOME_ROWS.map(([k, label]) => {
                  const better = k.startsWith("unmet") ? game.current![k] < game.baseline![k] : game.current![k] > game.baseline![k];
                  return (
                    <tr key={k}>
                      <td>{label}</td>
                      <td>{game.baseline![k]}</td>
                      <td className={better ? "ok" : ""}>{game.current![k]}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="results-cols">
              <section>
                <h3>What improved</h3>
                {game.summary?.improved.length ? <ul>{game.summary.improved.map((l) => <li key={l}>{l}</li>)}</ul> : <p className="muted">Nothing yet.</p>}
              </section>
              <section>
                <h3>What did not</h3>
                {game.summary?.unresolved.length ? <ul>{game.summary.unresolved.map((l) => <li key={l}>{l}</li>)}</ul> : <p className="muted">No remaining gaps in this model.</p>}
              </section>
            </div>
            <h3>Interventions</h3>
            <ul className="intervention-list">
              {game.interventions.map((i) => (
                <li key={i.token_id} className={i.effective ? "" : "ineffective"}>
                  <TokenIcon type={i.type} size={14} /> {TOKEN_LABELS[i.type]} @ {i.site_id} · cost {i.cost_model} · {i.effective ? "effective" : "changed no outcome"}
                </li>
              ))}
            </ul>
            <p className="muted small">"No response" = the same flood stage and communities with no response pieces. All values are educational model estimates, not real-world predictions.</p>
          </>
        )}
      </div>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="fact">
      <b>{value}</b>
      <small>{label}</small>
    </div>
  );
}
