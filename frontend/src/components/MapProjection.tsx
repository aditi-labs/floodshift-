import { useMemo } from "react";
import type { RiskZone, ServiceRoute, UV, WorldSnapshot } from "../types/contracts";
import type { RoadGeometry, ScenarioGeometry } from "../types/scenario";
import { BOARD_HEIGHT, BOARD_WIDTH, FIDUCIAL_CORNERS, toSvgPoint, uvToPathD, uvToPoints } from "../types/geometry";
import type { Feedback } from "../hooks/useWorldSocket";
import { TOKEN_COLORS, TokenGlyph } from "./TokenIcon";

/** Convert UV radius to SVG pixels */
function uvRadiusToSvg(radiusUv: number): number {
  return radiusUv * Math.max(BOARD_WIDTH, BOARD_HEIGHT);
}

export interface MapProjectionProps {
  scenario: ScenarioGeometry;
  snapshot: WorldSnapshot;
  feedback?: Feedback[];
  /** Draw rivers/roads/pads. Off when projecting onto the printed map (overlays only). */
  showBasemap: boolean;
  /** Black squares over corner fiducials so projected light never washes out ArUco tracking. */
  maskFiducials?: boolean;
  /** Smaller text, no banner; used for the operator's mini map. */
  compact?: boolean;
  onSiteClick?: (siteId: string) => void;
}

const SERVICE_OFFSET: Record<ServiceRoute["service"], number> = { medical: -5, food: 0, refuge: 5 };

function midpoint(path: UV[]): UV {
  const pts = path.map(([u, v]) => toSvgPoint(u, v));
  let total = 0;
  const seg: number[] = [];
  for (let i = 1; i < pts.length; i++) {
    const d = Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
    seg.push(d);
    total += d;
  }
  let half = total / 2;
  for (let i = 0; i < seg.length; i++) {
    if (half <= seg[i]) {
      const t = seg[i] ? half / seg[i] : 0;
      const a = path[i];
      const b = path[i + 1];
      return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    }
    half -= seg[i];
  }
  return path[0];
}

/** Chain edge geometries into one ordered polyline for an animated route. */
function chain(roads: Map<string, RoadGeometry>, edgeIds: string[]): UV[] {
  const out: UV[] = [];
  for (const id of edgeIds) {
    const r = roads.get(id);
    if (!r) continue;
    let p = r.path;
    if (out.length) {
      const last = out[out.length - 1];
      const dStart = Math.hypot(p[0][0] - last[0], p[0][1] - last[1]);
      const dEnd = Math.hypot(p[p.length - 1][0] - last[0], p[p.length - 1][1] - last[1]);
      if (dEnd < dStart) p = [...p].reverse();
      out.push(...p.slice(1));
    } else {
      // Orient the first segment so its end meets the next edge.
      const next = roads.get(edgeIds[1] ?? "");
      if (next) {
        const end = p[p.length - 1];
        const touches = (q: UV) => Math.hypot(q[0] - end[0], q[1] - end[1]) < 1e-6;
        if (!touches(next.path[0]) && !touches(next.path[next.path.length - 1])) p = [...p].reverse();
      }
      out.push(...p);
    }
  }
  return out;
}

export function MapProjection({ scenario, snapshot, feedback = [], showBasemap, maskFiducials, compact, onSiteClick }: MapProjectionProps) {
  const roads = useMemo(() => new Map(scenario.roads.map((r) => [r.id, r])), [scenario]);
  const sites = useMemo(() => new Map(scenario.sites.map((s) => [s.id, s])), [scenario]);
  const blocked = snapshot.edges.filter((e) => e.blocked);
  const active = snapshot.phase === "disaster_active";
  const routes = snapshot.service_routes ?? [];
  const anyCut = routes.some((r) => !r.reachable);
  const allOk = routes.length > 0 && routes.every((r) => r.reachable);
  const ghost = snapshot.ghost_suggestion;
  const ghostSite = ghost ? sites.get(ghost.site_id) : undefined;
  const fs = compact ? 0.8 : 1;

  const banner = !active
    ? "NEPAL 2026 · PLACE START TO BEGIN"
    : ghost
      ? "PLACE BRIDGE HERE"
      : allOk
        ? "RECONNECTED"
        : anyCut
          ? "ROUTE BLOCKED"
          : "NEPAL 2026 · SCENARIO ACTIVE";

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
        <pattern id="hazard-hatch" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(35)">
          <rect width="14" height="14" fill="var(--c-hazard-fill)" />
          <line x1="0" y1="0" x2="0" y2="14" stroke="var(--c-hazard)" strokeWidth="2" opacity="0.5" />
        </pattern>
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

      {/* Clickable site targets for manual/mouse fallback (same WorldAction as camera). */}
      {onSiteClick && (
        <g className="layer-hit">
          {scenario.sites.map((s) => {
            const p = toSvgPoint(...s.board_uv);
            return <circle key={s.id} cx={p.x} cy={p.y} r={28} className="site-hit" onClick={() => onSiteClick(s.id)}><title>{s.label}</title></circle>;
          })}
        </g>
      )}

      {/* 1.5 · Risk zones: colored circles that adapt as tokens provide protection */}
      {snapshot.risk_zones && snapshot.risk_zones.length > 0 && (
        <g className="layer-risk-zones">
          {snapshot.risk_zones.map((zone: RiskZone) => {
            const p = toSvgPoint(...zone.board_uv_center);
            const r = uvRadiusToSvg(zone.radius_uv);
            return (
              <g key={zone.zone_id} className={`risk-zone risk-${zone.risk_level} ${zone.is_protected ? "protected" : ""}`}>
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={r}
                  fill={zone.color}
                  fillOpacity={0.35}
                  stroke={zone.color}
                  strokeWidth={2}
                  strokeOpacity={0.7}
                />
                {/* Protection indicator ring */}
                {zone.is_protected && (
                  <circle
                    cx={p.x}
                    cy={p.y}
                    r={r + 4}
                    fill="none"
                    stroke="#00CC00"
                    strokeWidth={3}
                    strokeDasharray="8 4"
                    className="protection-ring"
                  />
                )}
                {/* Population label */}
                {!compact && zone.population_exposed > 50 && (
                  <text
                    x={p.x}
                    y={p.y + r + 16}
                    className="risk-label"
                    fontSize={10 * fs}
                    textAnchor="middle"
                    fill={zone.color}
                  >
                    ~{zone.population_exposed} residents (model est.)
                  </text>
                )}
              </g>
            );
          })}
        </g>
      )}

      {/* 2 · Simulated hazard — dashed, animated: model, not observation */}
      {active &&
        scenario.hazard_zones
          .filter((h) => h.stage <= snapshot.simulation_stage)
          .map((h) => (
            <g key={h.id} className="layer-hazard">
              <path d={uvToPathD(h.polygon, true)} fill="url(#hazard-hatch)" className="hazard-fill" />
              <path d={uvToPathD(h.polygon, true)} className="hazard-edge" />
            </g>
          ))}

      {/* 3 · Service routes: computed by backend, drawn here */}
      <g className="layer-routes">
        {routes.map((r) => {
          const pts = chain(roads, r.edge_ids);
          if (pts.length < 2) return null;
          return (
            <polyline
              key={`${r.population_id}-${r.service}`}
              points={uvToPoints(pts)}
              transform={`translate(0 ${SERVICE_OFFSET[r.service]})`}
              className={`route route-${r.service} ${r.reachable ? "route-ok" : "route-cut"}`}
            />
          );
        })}
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
              <path d={`M${m.x - 9} ${m.y - 9} L${m.x + 9} ${m.y + 9} M${m.x + 9} ${m.y - 9} L${m.x - 9} ${m.y + 9}`} className="road-x" />
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

      {/* 6 · Tokens + facility capacity + population needs */}
      <g className="layer-tokens">
        {snapshot.tokens.map((t) => {
          const p = toSvgPoint(...t.board_uv);
          const fac = snapshot.facilities.find((f) => f.site_id === t.site_id);
          const demand = snapshot.population_demand.find((d) => d.id === t.site_id);
          return (
            <g key={t.id} transform={`translate(${p.x} ${p.y})`} className={`token token-${t.status}`}>
              <circle r={22} className="token-ring" style={{ stroke: TOKEN_COLORS[t.type] }} />
              <g transform={`rotate(${t.rotation_deg ?? 0})`}>
                <TokenGlyph type={t.type} size={20} />
              </g>
              {fac && (
                <g transform="translate(0 38)" className={`facility-badge ${fac.reachable ? "ok" : "cut"}`}>
                  <rect x={-34} y={-10} width={68} height={20} rx={10} />
                  <text fontSize={11 * fs} dy="4">
                    {fac.reachable ? "✓" : "✕"} {fac.used_capacity_model}/{fac.capacity_model}
                  </text>
                </g>
              )}
              {demand && demand.headcount_known !== false && <NeedBars demand={demand} metrics={snapshot.metrics} fs={fs} />}
            </g>
          );
        })}
      </g>

      {/* 7 · Transient feedback: recognized / accepted / rejected */}
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

      {/* 8 · Banner + disclaimer (kept in the margins) */}
      {!compact && (
        <g className="layer-chrome">
          <text x={BOARD_WIDTH / 2} y={30} className={`banner ${allOk ? "banner-ok" : anyCut ? "banner-cut" : ""}`}>
            {banner}
          </text>
          <text x={BOARD_WIDTH / 2} y={BOARD_HEIGHT - 10} className="disclaimer">
            {snapshot.provenance_label} · {scenario.data_label === "SCHEMATIC" ? "schematic layout" : "HOT/OSM-derived"} · not a real disaster prediction
          </text>
        </g>
      )}

      {maskFiducials &&
        FIDUCIAL_CORNERS.map(([u, v], i) => {
          const p = toSvgPoint(u, v);
          return <rect key={i} x={p.x - 28} y={p.y - 28} width={56} height={56} fill="#000" />;
        })}
    </svg>
  );
}

function NeedBars({ demand, metrics, fs }: { demand: WorldSnapshot["population_demand"][number]; metrics: WorldSnapshot["metrics"]; fs: number }) {
  // Needs are read straight from the snapshot; bars show unmet / total for this node.
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
