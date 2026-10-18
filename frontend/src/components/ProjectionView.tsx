import { useEffect, useState } from "react";
import type { WorldHook } from "../hooks/useWorldSocket";
import { BOARD_HEIGHT, BOARD_WIDTH, toSvgPoint } from "../types/geometry";
import type { UV } from "../types/contracts";
import { MapProjection } from "./MapProjection";

// Fullscreen projector output (/projector). No DevTools-style chrome: keys only.
//   F  fullscreen      M  overlay-only <-> screen basemap      C  calibration
// Calibration is a 2D affine nudge on top of the projector's own keystone (spec §08 P0 path).

export interface Calibration {
  dx: number;
  dy: number;
  sx: number;
  sy: number;
  rot: number;
}

const DEFAULT_CAL: Calibration = { dx: 0, dy: 0, sx: 1, sy: 1, rot: 0 };
const CAL_KEY = "floodshift.projector.calibration.v1";

/** Printed registration crosses P1 adds to map_print.svg; projector crosses must land on them. */
export const REGISTRATION_POINTS: UV[] = [
  [0.1, 0.1],
  [0.9, 0.1],
  [0.9, 0.9],
  [0.1, 0.9],
];

function loadCal(): Calibration {
  try {
    const raw = localStorage.getItem(CAL_KEY);
    return raw ? { ...DEFAULT_CAL, ...JSON.parse(raw) } : DEFAULT_CAL;
  } catch {
    return DEFAULT_CAL;
  }
}

function saveCal(c: Calibration) {
  try {
    localStorage.setItem(CAL_KEY, JSON.stringify(c));
  } catch {
    /* private window: calibration lasts for this session only */
  }
}

export function ProjectionView({ world }: { world: WorldHook }) {
  const params = new URLSearchParams(window.location.search);
  const [overlayOnly, setOverlayOnly] = useState(params.get("mode") === "overlay");
  const [calibrating, setCalibrating] = useState(false);
  const [cal, setCal] = useState<Calibration>(loadCal);

  useEffect(() => saveCal(cal), [cal]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      if (k === "f") {
        if (document.fullscreenElement) document.exitFullscreen();
        else document.documentElement.requestFullscreen().catch(() => {});
      } else if (k === "m") setOverlayOnly((v) => !v);
      else if (k === "c") setCalibrating((v) => !v);
      else if (calibrating) {
        const step = e.shiftKey ? 10 : 1;
        setCal((c) => {
          switch (e.key) {
            case "ArrowLeft": return { ...c, dx: c.dx - step };
            case "ArrowRight": return { ...c, dx: c.dx + step };
            case "ArrowUp": return { ...c, dy: c.dy - step };
            case "ArrowDown": return { ...c, dy: c.dy + step };
            case "[": return { ...c, rot: +(c.rot - 0.1 * step).toFixed(2) };
            case "]": return { ...c, rot: +(c.rot + 0.1 * step).toFixed(2) };
            case "-": return { ...c, sx: +(c.sx - 0.002 * step).toFixed(4), sy: +(c.sy - 0.002 * step).toFixed(4) };
            case "=": return { ...c, sx: +(c.sx + 0.002 * step).toFixed(4), sy: +(c.sy + 0.002 * step).toFixed(4) };
            case ",": return { ...c, sx: +(c.sx - 0.002 * step).toFixed(4) };
            case ".": return { ...c, sx: +(c.sx + 0.002 * step).toFixed(4) };
            case ";": return { ...c, sy: +(c.sy - 0.002 * step).toFixed(4) };
            case "'": return { ...c, sy: +(c.sy + 0.002 * step).toFixed(4) };
            case "0": return DEFAULT_CAL;
            default: return c;
          }
        });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [calibrating]);

  const { snapshot, scenario, feedback, reactions, status, scenarioError } = world;
  const cx = BOARD_WIDTH / 2;
  const cy = BOARD_HEIGHT / 2;
  const transform = `translate(${cal.dx}px, ${cal.dy}px) rotate(${cal.rot}deg) scale(${cal.sx}, ${cal.sy})`;

  return (
    <div className={`projector ${overlayOnly ? "projector-overlay" : "projector-screen"}`}>
      <div className="projector-stage" style={{ transform, transformOrigin: "50% 50%" }}>
        {snapshot && scenario ? (
          <MapProjection scenario={scenario} snapshot={snapshot} feedback={feedback} reactions={reactions} showBasemap={!overlayOnly} maskFiducials={overlayOnly} />
        ) : (
          <div className="projector-wait">{scenarioError ? `BACKEND UNAVAILABLE — ${scenarioError}` : "Waiting for world snapshot…"}</div>
        )}
        {calibrating && (
          <svg className="calibration-overlay" viewBox={`0 0 ${BOARD_WIDTH} ${BOARD_HEIGHT}`} preserveAspectRatio="xMidYMid meet">
            <rect x={1} y={1} width={BOARD_WIDTH - 2} height={BOARD_HEIGHT - 2} className="cal-border" />
            {REGISTRATION_POINTS.map(([u, v], i) => {
              const p = toSvgPoint(u, v);
              return <path key={i} d={`M${p.x - 24} ${p.y} H${p.x + 24} M${p.x} ${p.y - 24} V${p.y + 24}`} className="cal-cross" />;
            })}
            <path d={`M${cx - 12} ${cy} H${cx + 12} M${cx} ${cy - 12} V${cy + 12}`} className="cal-cross" />
          </svg>
        )}
      </div>
      {calibrating && (
        <div className="cal-panel">
          <b>CALIBRATION</b> arrows move · [ ] rotate · - = scale · , . x-scale · ; ' y-scale · shift ×10 · 0 reset · C close
          <br />
          dx {cal.dx} dy {cal.dy} rot {cal.rot}° sx {cal.sx} sy {cal.sy}
        </div>
      )}
      {status !== "live" && <div className="projector-status">{status.toUpperCase()}</div>}
    </div>
  );
}
