import { useMemo } from "react";
import type { RiskZone, ServiceKind, UV, WorldSnapshot } from "../types/contracts";
import type { RoadGeometry, ScenarioGeometry } from "../types/scenario";
import { BOARD_HEIGHT, BOARD_WIDTH, FIDUCIAL_CORNERS, toSvgPoint, uvToPathD, uvToPoints } from "../types/geometry";
import type { ActiveReactions, Feedback } from "../hooks/useWorldSocket";
import { aggregateRouteEdges, chain, polylineLength, SERVICE_ORDER } from "../lib/routeLayers";
import type { Reaction } from "../lib/worldReactions";
import { FloodLayer } from "./FloodLayer";
import { TOKEN_COLORS, TokenGlyph } from "./TokenIcon";

/** Convert UV radius to SVG pixels */
function uvRadiusToSvg(radiusUv: number): number {
  return radiusUv * Math.max(BOARD_WIDTH, BOARD_HEIGHT);
}

export interface MapProjectionProps {
  scenario: ScenarioGeometry;
  snapshot: WorldSnapshot;
  feedback?: Feedback[];
  reactions?: ActiveReactions[];
  /** Draw rivers/roads/pads. Off when projecting onto the printed map (overlays only). */
  showBasemap: boolean;
  /** Black squares over corner fiducials so projected light never washes out ArUco tracking. */
  maskFiducials?: boolean;
  /** Smaller text, no banner; used for the operator's mini map. */
  compact?: boolean;
  onSiteClick?: (siteId: string) => void;
}

export const SERVICE_COLOR: Record<ServiceKind, string> = {
  medical: "var(--c-medical)",
  food: "var(--c-food)",
  refuge: "var(--c-refuge)",
};
const STRIPE = 11;

function midpoint(path: UV[]): UV {
  const pts = path.map(([u, v]) => toSvgPoint(u, v));
  let half = polylineLength(pts) / 2;
  for (let i = 1; i < pts.length; i++) {
    const d = Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
    if (half <= d) {
      const t = d ? half / d : 0;
      return [path[i - 1][0] + (path[i][0] - path[i - 1][0]) * t, path[i - 1][1] + (path[i][1] - path[i - 1][1]) * t];
    }
    half -= d;
  }
  return path[0];
}

export function MapProjection({ scenario, snapshot, feedback = [], reactions = [], showBasemap, maskFiducials, compact, onSiteClick }: MapProjectionProps) {
  const roads = useMemo(() => new Map(scenario.roads.map((r) => [r.id, r])), [scenario]);
  const sites = useMemo(() => new Map(scenario.sites.map((s) => [s.id, s])), [scenario]);
  const blocked = snapshot.edges.filter((e) => e.blocked);
  const active = snapshot.phase === "disaster_active";
  const routes = snapshot.service_routes ?? [];
  const { open, cut } = useMemo(() => aggregateRouteEdges(routes, roads), [routes, roads]);
  const anyCut = routes.some((r) => !r.reachable);
  const allOk = routes.length > 0 && routes.every((r) => r.reachable);
  const ghost = snapshot.ghost_suggestion;
  const ghostSite = ghost ? sites.get(ghost.site_id) : undefined;
  const fs = compact ? 0.8 : 1;
  const latest = reactions[reactions.length - 1];
  const game = snapshot.game?.status === "active" ? snapshot.game : null;
  const stages = Math.max(1, (scenario.stage_count ?? 2) - 1);

  const banner = latest?.headline
    ? latest.headline.text
    : !active
      ? "PLACE START TO BEGIN THE FLOOD"
      : ghost
        ? "PLACE BRIDGE HERE"
        : allOk
          ? "ALL COMMUNITIES CONNECTED"
          : anyCut
            ? "ROUTES BLOCKED BY FLOOD"
            : "FLOOD ACTIVE";
  const bannerTone = latest?.headline ? `banner-${latest.headline.tone}` : allOk ? "banner-good" : anyCut ? "banner-bad" : "";

  // Population access, read straight from backend service routes.
  const access = useMemo(() => {
    const map = new Map<string, Partial<Record<ServiceKind, boolean>>>();
    for (const r of routes) map.set(r.population_id, { ...map.get(r.population_id), [r.service]: r.reachable });
    return map;
  }, [routes]);

  return (
    <svg
      className={`map-projection ${showBasemap ? "with-basemap" : "overlay-only"}`}
      viewBox={`0 0 ${BOARD_WIDTH} ${BOARD_HEIGHT}`}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="FLOODSHIFT board projection"
    >
      <defs>
        <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="3" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* 1 · Basemap (screen mode only — the paper already has this printed) */}
      {showBasemap && (
        <g className="layer-basemap">
          <rect width={BOARD_WIDTH} height={BOARD_HEIGHT} fill="var(--c-paper)" />
          {scenario.rivers.map((r, i) => (
            <path key={i} d={uvToPathD(r)} className="river" />
          ))}
          {scenario.roads.map((r) => (
            <path key={r.id} d={uvToPathD(r.path)} className={`road road-${r.kind}`} />
          ))}
          {scenario.labels.map((l) => {
            const p = toSvgPoint(...l.board_uv);
            return (
              <text key={l.text} x={p.x} y={p.y} className="map-label" fontSize={13 * fs}>
                {l.text}
              </text>
            );
          })}
        </g>
      )}

      {/* 1.5 · Risk zones (prevention data): colored circles that adapt as tokens provide protection */}
      {!active && snapshot.risk_zones && snapshot.risk_zones.length > 0 && (
        <g className="layer-risk-zones">
          {snapshot.risk_zones.map((zone: RiskZone) => {
            const p = toSvgPoint(...zone.board_uv_center);
            const r = uvRadiusToSvg(zone.radius_uv);
            return (
              <g key={zone.zone_id} className={`risk-zone risk-${zone.risk_level} ${zone.is_protected ? "protected" : ""}`}>
                <circle cx={p.x} cy={p.y} r={r} fill={zone.color} fillOpacity={0.25} stroke={zone.color} strokeWidth={2} strokeOpacity={0.7} />
                {zone.is_protected && <circle cx={p.x} cy={p.y} r={r + 4} fill="none" stroke="#00CC00" strokeWidth={3} strokeDasharray="8 4" className="protection-ring" />}
              </g>
            );
          })}
        </g>
      )}

      {/* 2 · Simulated flood: illustrated, opaque, placed by backend hazard geometry */}
      <FloodLayer scenario={scenario} stage={snapshot.simulation_stage} active={active} />

      {/* 2.5 · Pads above the water so placement targets stay visible */}
      {showBasemap && (
        <g className="layer-sites">
          {scenario.sites.map((s) => {
            const p = toSvgPoint(...s.board_uv);
            const occupied = snapshot.tokens.some((t) => t.site_id === s.id);
            return (
              <g key={s.id} transform={`translate(${p.x} ${p.y})`} className={`site site-${s.kind}`}>
                {s.kind === "control_start_pad" ? <rect x={-34} y={-24} width={68} height={48} rx={6} /> : <circle r={s.kind === "bridge_crossing" ? 16 : 20} />}
                {(!occupied || s.kind === "control_start_pad") && (
                  <text y={s.kind === "control_start_pad" ? 38 : 34} className="site-label" fontSize={11 * fs}>
                    {s.label}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      )}

      {/* 3 · Service routes from the backend: one line per mapped edge; shared edges striped */}
      <g className="layer-routes">
        {cut.map((e) => (
          <path key={`cut-${e.edge_id}`} d={uvToPathD(e.path)} className="route route-cut" />
        ))}
        {open.map((e) => (
          <path key={`case-${e.edge_id}`} d={uvToPathD(e.path)} className="route-casing" />
        ))}
        {open.map((e) =>
          e.services.map((s, i) => (
            <path
              key={`${e.edge_id}-${s}`}
              d={uvToPathD(e.path)}
              className={`route route-ok route-${s}`}
              stroke={SERVICE_COLOR[s]}
              strokeDasharray={e.services.length > 1 ? `${STRIPE} ${STRIPE * (e.services.length - 1)}` : undefined}
              strokeDashoffset={-i * STRIPE}
            />
          )),
        )}
      </g>

      {/* 4 · Closed roads: thick red dash + X */}
      <g className="layer-blocked">
        {blocked.map((e) => {
          const r = roads.get(e.id);
          if (!r) return null;
          const m = toSvgPoint(...midpoint(r.path));
          return (
            <g key={e.id}>
              <path d={uvToPathD(r.path)} className="road-blocked" />
              <circle cx={m.x} cy={m.y} r={13} className="road-x-badge" />
              <path d={`M${m.x - 7} ${m.y - 7} L${m.x + 7} ${m.y + 7} M${m.x + 7} ${m.y - 7} L${m.x - 7} ${m.y + 7}`} className="road-x" />
            </g>
          );
        })}
      </g>

      {/* 5 · Ghost suggestion: cyan dashed silhouette + preview route */}
      {ghost && (
        <g className="layer-ghost">
          {ghost.preview_edge_ids && <polyline points={uvToPoints(chain(roads, ghost.preview_edge_ids))} className="ghost-route" />}
          {(() => {
            const p = toSvgPoint(...ghost.board_uv);
            return (
              <g transform={`translate(${p.x} ${p.y}) rotate(${ghostSite?.rotation_deg ?? 0})`} className="ghost-bridge" filter="url(#glow)">
                <rect x={-46} y={-14} width={92} height={28} rx={4} />
                <path d="M-40 -14 V14 M40 -14 V14 M-46 -8 H46 M-46 8 H46" />
              </g>
            );
          })()}
          <text x={toSvgPoint(...ghost.board_uv).x} y={toSvgPoint(...ghost.board_uv).y - 30} className="ghost-label" fontSize={15 * fs}>
            PLACE BRIDGE HERE
          </text>
        </g>
      )}

      {/* 6 · Tokens + facility capacity + population access */}
      <g className="layer-tokens">
        {snapshot.tokens.map((t) => {
          const p = toSvgPoint(...t.board_uv);
          const fac = snapshot.facilities.find((f) => f.id === t.id) ?? snapshot.facilities.find((f) => f.site_id === t.site_id);
          const demand = t.type === "person" ? snapshot.population_demand.find((d) => d.id === t.site_id) : undefined;
          const services = demand ? access.get(demand.id) : undefined;
          const isolated = !!services && Object.values(services).length > 0 && Object.values(services).every((v) => !v);
          return (
            <g key={t.id} transform={`translate(${p.x} ${p.y})`} className={`token token-${t.status} token-type-${t.type}`}>
              {fac && fac.reachable && (fac.active ?? true) && <circle r={36} className={`coverage-halo coverage-${t.type}`} />}
              {isolated && <circle r={34} className="isolated-ring" />}
              <circle r={22} className="token-ring" style={{ stroke: TOKEN_COLORS[t.type] }} />
              <g transform={`rotate(${t.rotation_deg ?? 0})`}>
                <TokenGlyph type={t.type} size={20} />
              </g>
              {fac && (
                <g transform="translate(0 38)" className={`facility-badge ${fac.reachable && (fac.active ?? true) ? "ok" : "cut"}`}>
                  <rect x={-34} y={-10} width={68} height={20} rx={10} />
                  <text fontSize={11 * fs} dy="4">
                    {fac.reachable ? "" : "✕ "}
                    {fac.used_capacity_model}/{fac.capacity_model}
                  </text>
                </g>
              )}
              {services && (
                <g transform="translate(-21 -36)" className="access-dots">
                  {SERVICE_ORDER.map((s, i) =>
                    s in services ? (
                      <circle key={s} cx={i * 21} r={6} className={services[s] ? "dot-ok" : "dot-cut"} style={{ fill: services[s] ? SERVICE_COLOR[s] : undefined, stroke: SERVICE_COLOR[s] }} />
                    ) : null,
                  )}
                </g>
              )}
              {isolated && !compact && (
                <text y={-54} className="isolated-label" fontSize={12}>
                  CUT OFF
                </text>
              )}
              {demand && demand.headcount_known !== false && <NeedBars demand={demand} metrics={snapshot.metrics} fs={fs} />}
            </g>
          );
        })}
      </g>

      {/* 7 · Environmental reactions derived from snapshot differences */}
      <g className="layer-reactions">
        {reactions.map((set) => (
          <g key={set.key}>
            {set.reactions.map((r) => (
              <ReactionMark key={r.id} r={r} roads={roads} />
            ))}
          </g>
        ))}
      </g>

      {/* 8 · Transient feedback: recognized / accepted / rejected */}
      <g className="layer-feedback">
        {feedback.map((f) => {
          const p = toSvgPoint(...f.board_uv);
          return (
            <g key={f.id} transform={`translate(${p.x} ${p.y})`} className={`fb fb-${f.kind}`}>
              <circle r={26} className="fb-ring" />
              <text y={f.kind === "accepted" ? 6 : -36} fontSize={(f.kind === "accepted" ? 20 : 13) * fs} className="fb-text">
                {f.label}
              </text>
            </g>
          );
        })}
      </g>

      {/* 9 · Banner, minimal game line and provenance (kept in the margins) */}
      {!compact && (
        <g className="layer-chrome">
          <text key={latest?.key ?? "steady"} x={BOARD_WIDTH / 2} y={34} className={`banner ${bannerTone} ${latest?.headline ? "banner-pop" : ""}`}>
            {banner}
          </text>
          {latest?.scoreDelta != null && (
            <text key={`d-${latest.key}`} x={BOARD_WIDTH / 2} y={62} className={`score-delta ${latest.scoreDelta > 0 ? "up" : "down"}`}>
              {latest.scoreDelta > 0 ? "+" : ""}
              {latest.scoreDelta} GAME POINTS
            </text>
          )}
          {game && latest?.scoreDelta == null && (
            <text x={BOARD_WIDTH / 2} y={60} className="hud-line">
              SCORE {game.score} · STAGE {snapshot.simulation_stage}/{stages} · ACCESS {game.current?.reachable_communities ?? 0}/{game.communities_total ?? 0} · BUDGET {snapshot.budget_remaining_model ?? "–"}
            </text>
          )}
          <text x={BOARD_WIDTH / 2} y={BOARD_HEIGHT - 10} className="disclaimer">
            Map: {scenario.data_label === "SCHEMATIC" ? "schematic layout" : "HOT/OSM mapped"} · Flood: simulated scenario (illustrative) · Outcomes: model estimates, not a prediction
          </text>
        </g>
      )}

      {maskFiducials &&
        FIDUCIAL_CORNERS.map(([u, v], i) => {
          const p = toSvgPoint(u, v);
          return <rect key={i} x={p.x - 28} y={p.y - 28} width={56} height={56} fill="#000" />;
        })}

      {/* Clickable site targets for manual/mouse fallback (same WorldAction as camera). */}
      {onSiteClick && (
        <g className="layer-hit">
          {scenario.sites.map((s) => {
            const p = toSvgPoint(...s.board_uv);
            return (
              <circle key={s.id} cx={p.x} cy={p.y} r={28} className="site-hit" onClick={() => onSiteClick(s.id)}>
                <title>{s.label}</title>
              </circle>
            );
          })}
        </g>
      )}
    </svg>
  );
}

function ReactionMark({ r, roads }: { r: Reaction; roads: Map<string, RoadGeometry> }) {
  const at = r.board_uv ? toSvgPoint(...r.board_uv) : null;
  const color = r.service ? SERVICE_COLOR[r.service] : r.tone === "good" ? "var(--c-ok)" : r.tone === "bad" ? "var(--c-cut)" : "#fff";
  switch (r.kind) {
    case "edge_restored":
    case "edge_blocked":
      return (
        <g className={`rx rx-${r.kind}`}>
          {(r.edge_ids ?? []).map((id) => {
            const road = roads.get(id);
            return road ? <path key={id} d={uvToPathD(road.path)} className="rx-edge" /> : null;
          })}
          {at && [0, 1, 2].map((i) => <circle key={i} cx={at.x} cy={at.y} r={20} className="rx-pulse" style={{ animationDelay: `${i * 0.28}s` }} />)}
        </g>
      );
    case "route_opened":
    case "route_lost": {
      const pts = r.path && r.path.length >= 2 ? r.path : chain(roads, r.edge_ids ?? []);
      if (pts.length < 2) return null;
      const len = polylineLength(pts.map(([u, v]) => toSvgPoint(u, v)));
      return (
        <polyline
          points={uvToPoints(pts)}
          className={`rx rx-${r.kind}`}
          stroke={color}
          // Services draw one after another so shared stretches show every colour.
          style={{ ["--len" as string]: `${len.toFixed(1)}`, animationDelay: r.service ? `${0.2 + SERVICE_ORDER.indexOf(r.service) * 0.35}s, 3.4s` : undefined }}
        />
      );
    }
    case "coverage":
      return at ? (
        <g className={`rx rx-coverage rx-${r.tone}`} transform={`translate(${at.x} ${at.y})`}>
          <circle r={30} className="rx-halo" stroke={color} fill={color} />
          <circle r={30} className="rx-halo rx-halo-2" stroke={color} fill="none" />
        </g>
      ) : null;
    case "isolated":
      return at ? <circle cx={at.x} cy={at.y} r={30} className="rx rx-isolated" /> : null;
    case "token_removed":
      return at ? <circle cx={at.x} cy={at.y} r={26} className="rx rx-removed" /> : null;
    default:
      return null;
  }
}

function NeedBars({ demand, metrics, fs }: { demand: WorldSnapshot["population_demand"][number]; metrics: WorldSnapshot["metrics"]; fs: number }) {
  // Per-node unmet comes from the backend; global metrics are only a fallback.
  const rows = [
    { k: "FOOD", need: demand.need_food, unmet: demand.unmet_food ?? metrics.unmet_food_model, c: "var(--c-food)" },
    { k: "CARE", need: demand.need_medical, unmet: demand.unmet_medical ?? metrics.unmet_medical_model, c: "var(--c-medical)" },
    { k: "REFUGE", need: demand.need_refuge, unmet: demand.unmet_refuge ?? metrics.unmet_refuge_model, c: "var(--c-refuge)" },
  ];
  const w = 70;
  return (
    <g transform="translate(-35 32)" className="need-bars">
      <text x={w / 2} y={-2} fontSize={10 * fs} className="need-title">
        {demand.people_model} model people
      </text>
      {rows.map((r, i) => {
        const met = r.need ? (r.need - Math.min(r.unmet, r.need)) / r.need : 1;
        return (
          <g key={r.k} transform={`translate(0 ${6 + i * 14})`}>
            <rect width={w} height={9} rx={2} className="need-track" />
            <rect width={w * met} height={9} rx={2} fill={r.c} />
            <text x={w + 4} y={8} fontSize={9 * fs} className="need-label">
              {r.k} {Math.min(r.unmet, r.need)} unmet
            </text>
          </g>
        );
      })}
    </g>
  );
}

