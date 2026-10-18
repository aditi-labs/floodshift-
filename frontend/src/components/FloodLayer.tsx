import { useId, useMemo } from "react";
import type { UV } from "../types/contracts";
import type { ScenarioGeometry } from "../types/scenario";
import { BOARD_HEIGHT, BOARD_WIDTH, uvToPathD } from "../types/geometry";

// Woodblock-style illustrated flood, drawn as reusable SVG over the real map.
//
// Placement comes only from backend scenario geometry: hazard_zones (flood footprints)
// or, when a bundle has none, flood_corridors (mapped river reaches near the stage's
// simulated closures). The art is a picture OF the simulated hazard; it never decides
// which roads are closed. Each stage group mounts once when the backend reaches that
// stage, so the entrance plays once per stage — never on every snapshot — and a reset
// (stage 0) unmounts the water entirely.

const INK = "#0a1533";
const NAVY = "#0c2257";
const INDIGO = "#1d3484";
const COBALT = "#2552a8";
const TURQUOISE = "#2fa6c2";
const ICE = "#b3e3f1";
const FOAM = "#f7fbff";

const TILE_W = 96;
const TILE_H = 48;
const CREST_H = 132;

interface Shape {
  kind: "polygon" | "corridor";
  d: string;
  width: number;
  bounds: [number, number, number, number];
}

/**
 * Chaikin corner cutting for closed rings. Raster-derived footprints are stair-stepped;
 * two passes round the steps for the illustration while staying inside each step's cell.
 */
export function smoothRing(ring: UV[], passes = 2): UV[] {
  let pts = ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1] ? ring.slice(0, -1) : ring;
  for (let p = 0; p < passes && pts.length >= 3; p++) {
    pts = pts.flatMap((a, i) => {
      const b = pts[(i + 1) % pts.length];
      return [
        [a[0] * 0.75 + b[0] * 0.25, a[1] * 0.75 + b[1] * 0.25] as UV,
        [a[0] * 0.25 + b[0] * 0.75, a[1] * 0.25 + b[1] * 0.75] as UV,
      ];
    });
  }
  return pts;
}

function shapesFor(scenario: ScenarioGeometry): Map<number, Shape[]> {
  const out = new Map<number, Shape[]>();
  const add = (stage: number, s: Shape) => out.set(stage, [...(out.get(stage) ?? []), s]);
  const bounds = (pts: UV[], pad: number): Shape["bounds"] => {
    const xs = pts.map(([u]) => u * BOARD_WIDTH);
    const ys = pts.map(([, v]) => v * BOARD_HEIGHT);
    return [Math.min(...xs) - pad, Math.min(...ys) - pad, Math.max(...xs) + pad, Math.max(...ys) + pad];
  };
  for (const h of scenario.hazard_zones) {
    if (h.polygon.length >= 3) {
      const ring = smoothRing(h.polygon);
      add(h.stage, { kind: "polygon", d: uvToPathD(ring, true), width: 0, bounds: bounds(ring, 0) });
    }
  }
  for (const c of scenario.flood_corridors ?? []) {
    const width = c.width_uv * BOARD_WIDTH;
    if (c.path.length >= 2) add(c.stage, { kind: "corridor", d: uvToPathD(c.path), width, bounds: bounds(c.path, width / 2) });
  }
  return out;
}

/** Paint every shape as a mask/outline: polygons filled, corridors stroked at their width. */
function ShapePaint({ shapes, color, grow = 0 }: { shapes: Shape[]; color: string; grow?: number }) {
  return (
    <>
      {shapes.map((s, i) =>
        s.kind === "polygon" ? (
          <path key={i} d={s.d} fill={grow ? "none" : color} stroke={grow ? color : "none"} strokeWidth={grow} strokeLinejoin="round" />
        ) : (
          <path key={i} d={s.d} fill="none" stroke={color} strokeWidth={s.width + grow} strokeLinecap="round" strokeLinejoin="round" />
        ),
      )}
    </>
  );
}

/** One curling crest (Great-Wave silhouette) in local units, ~124 wide × 132 tall. */
function Crest({ fill = COBALT, inner = TURQUOISE }: { fill?: string; inner?: string }) {
  return (
    <g>
      <path
        d="M0 132 L0 62 C0 22 40 0 80 4 C110 8 126 30 114 54 C106 68 86 66 84 54 C82 44 92 40 98 46 C96 32 84 24 70 26 C46 30 40 62 52 92 C60 112 80 124 100 132 Z"
        fill={fill}
        stroke={INK}
        strokeWidth={3.2}
        strokeLinejoin="round"
      />
      <path d="M12 120 C6 84 14 44 44 24 C60 14 80 12 96 20" fill="none" stroke={inner} strokeWidth={4} strokeLinecap="round" />
      <path d="M22 116 C18 90 24 62 44 44" fill="none" stroke={ICE} strokeWidth={2} strokeLinecap="round" />
      {/* Foam lip and claw-like spray along the curl. */}
      <path d="M28 24 C52 6 92 0 114 22" fill="none" stroke={FOAM} strokeWidth={5.5} strokeLinecap="round" strokeDasharray="1 7" />
      <path d="M86 50 C84 42 92 38 98 46" fill="none" stroke={FOAM} strokeWidth={3} strokeLinecap="round" />
      <circle cx={120} cy={14} r={3.4} fill={FOAM} stroke={INK} strokeWidth={1} />
      <circle cx={127} cy={26} r={2.4} fill={FOAM} stroke={INK} strokeWidth={0.8} />
      <circle cx={116} cy={4} r={2.2} fill={FOAM} stroke={INK} strokeWidth={0.8} />
      <circle cx={130} cy={40} r={1.8} fill={FOAM} />
    </g>
  );
}

/** A column of crests stacked along a vertical leading edge. */
function CrestColumn({ x, y0, y1, scale = 1, fill, inner }: { x: number; y0: number; y1: number; scale?: number; fill?: string; inner?: string }) {
  const step = CREST_H * scale * 0.82;
  const rows: number[] = [];
  for (let y = y0 - CREST_H * scale; y < y1 + step; y += step) rows.push(y);
  return (
    <g>
      {rows.map((y, i) => (
        <g key={i} transform={`translate(${x + (i % 2 ? -18 * scale : 0)} ${y}) scale(${scale * (i % 3 === 1 ? 0.86 : 1)})`}>
          <Crest fill={fill} inner={inner} />
        </g>
      ))}
    </g>
  );
}

function WaveDefs({ id }: { id: string }) {
  // Tile of two curling bands; rows leave navy gaps that read as layered water.
  const band = (x0: number) =>
    `M${x0} 30 C${x0 + 10} 26 ${x0 + 18} 12 ${x0 + 30} 12 C${x0 + 40} 12 ${x0 + 44} 20 ${x0 + 38} 25 C${x0 + 34} 28 ${x0 + 29} 24 ${x0 + 32} 21 C${x0 + 36} 26 ${x0 + 42} 30 ${x0 + 48} 30`;
  return (
    <defs>
      <pattern id={`${id}-bands`} width={TILE_W} height={TILE_H} patternUnits="userSpaceOnUse" patternTransform="rotate(-9) scale(1.08)">
        <path d={`${band(0)} ${band(48).replace(/^M[^C]+/, "")} L${TILE_W} ${TILE_H} L0 ${TILE_H} Z`} fill={COBALT} stroke={INK} strokeWidth={2.2} strokeLinejoin="round" />
        <path d={`M6 33 C14 29 20 18 30 17 M54 33 C62 29 68 18 78 17`} fill="none" stroke={TURQUOISE} strokeWidth={2.2} strokeLinecap="round" />
        <path d={`M4 41 C16 38 28 38 40 41 M52 41 C64 38 76 38 88 41`} fill="none" stroke={INDIGO} strokeWidth={3} strokeLinecap="round" />
        <path d={`M22 14.5 C30 11 39 12 41 18 M70 14.5 C78 11 87 12 89 18`} fill="none" stroke={FOAM} strokeWidth={2.2} strokeLinecap="round" />
        <circle cx={43} cy={15} r={1.8} fill={FOAM} />
        <circle cx={91} cy={15} r={1.8} fill={FOAM} />
      </pattern>
      <pattern id={`${id}-ribbons`} width={TILE_W * 1.5} height={TILE_H * 1.5} patternUnits="userSpaceOnUse" patternTransform="rotate(7) translate(31 17)">
        <path
          d="M0 20 C18 10 34 8 50 16 C58 20 62 26 56 30 C52 32 49 28 52 25 C40 22 24 26 8 34 Z M72 56 C90 46 106 44 122 52 C130 56 134 62 128 66 C124 68 121 64 124 61 C112 58 96 62 80 70 Z"
          fill={TURQUOISE}
          stroke={INK}
          strokeWidth={1.8}
          strokeLinejoin="round"
        />
        <path d="M6 24 C20 16 34 14 46 19 M78 60 C92 52 106 50 118 55" fill="none" stroke={ICE} strokeWidth={1.6} strokeLinecap="round" />
      </pattern>
      <pattern id={`${id}-foam`} width={TILE_W * 2} height={TILE_H * 2} patternUnits="userSpaceOnUse" patternTransform="rotate(-4)">
        <g fill={FOAM}>
          <circle cx={20} cy={18} r={2.2} />
          <circle cx={27} cy={14} r={1.5} />
          <circle cx={150} cy={64} r={2.4} />
          <circle cx={158} cy={60} r={1.4} />
          <circle cx={92} cy={86} r={1.6} />
        </g>
        <path d="M60 40 c6 -6 14 -6 18 0 M120 10 c5 -5 11 -5 15 0" fill="none" stroke={FOAM} strokeWidth={1.8} strokeLinecap="round" />
      </pattern>
    </defs>
  );
}

export function FloodLayer({ scenario, stage, active }: { scenario: ScenarioGeometry; stage: number; active: boolean }) {
  const id = `fl${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const byStage = useMemo(() => shapesFor(scenario), [scenario]);
  const inset = scenario.board?.control_inset_uv;
  const stages = active ? [...byStage.keys()].filter((s) => s >= 1 && s <= stage).sort((a, b) => a - b) : [];
  if (!stages.length) return null;
  return (
    <g className="layer-flood" aria-label="Simulated flood (scenario hazard, illustrative art)">
      <WaveDefs id={id} />
      {stages.map((s) => (
        <FloodStage
          key={s}
          id={`${id}-s${s}`}
          patterns={id}
          shapes={byStage.get(s)!}
          earlier={stages.filter((e) => e < s).flatMap((e) => byStage.get(e)!)}
          inset={inset}
        />
      ))}
    </g>
  );
}

function FloodStage({ id, patterns, shapes, earlier, inset }: { id: string; patterns: string; shapes: Shape[]; earlier: Shape[]; inset?: [number, number, number, number] }) {
  const pad = TILE_W;
  const x0 = Math.min(...shapes.map((s) => s.bounds[0])) - pad;
  const y0 = Math.min(...shapes.map((s) => s.bounds[1])) - pad;
  const x1 = Math.max(...shapes.map((s) => s.bounds[2])) + pad;
  const y1 = Math.max(...shapes.map((s) => s.bounds[3])) + pad;
  const crestW = 140;
  // Content starts fully left of the region and slides in; its crest ends past the right edge.
  const sweep = -(x1 - x0 + crestW);
  const insetRect = inset ? (
    <rect x={inset[0] * BOARD_WIDTH} y={inset[1] * BOARD_HEIGHT} width={(inset[2] - inset[0]) * BOARD_WIDTH} height={(inset[3] - inset[1]) * BOARD_HEIGHT} fill="#000" />
  ) : null;
  // Only newly inundated area animates: earlier stages are cut out of this stage's mask.
  const exclusions = (
    <>
      <ShapePaint shapes={earlier} color="#000" />
      {insetRect}
    </>
  );
  return (
    <g className="flood-stage">
      <defs>
        <mask id={`${id}-water`} maskUnits="userSpaceOnUse" x={0} y={0} width={BOARD_WIDTH} height={BOARD_HEIGHT}>
          <rect width={BOARD_WIDTH} height={BOARD_HEIGHT} fill="#000" />
          <ShapePaint shapes={shapes} color="#fff" />
          {exclusions}
        </mask>
        <mask id={`${id}-rim`} maskUnits="userSpaceOnUse" x={0} y={0} width={BOARD_WIDTH} height={BOARD_HEIGHT}>
          <rect width={BOARD_WIDTH} height={BOARD_HEIGHT} fill="#fff" />
          {exclusions}
        </mask>
      </defs>

      {/* Bold woodblock outline: ink rim with a foam line, inked in after the wave lands. */}
      <g className="flood-rim" mask={`url(#${id}-rim)`}>
        <ShapePaint shapes={shapes} color={INK} grow={14} />
        <ShapePaint shapes={shapes} color={FOAM} grow={6} />
      </g>

      <g mask={`url(#${id}-water)`}>
        <g className="flood-sweep" style={{ ["--sweep" as string]: `${sweep}px` }}>
          <rect x={x0 - TILE_W * 2} y={y0} width={x1 - x0 + TILE_W * 4} height={y1 - y0} fill={NAVY} />
          <g className="flood-drift">
            <rect x={x0 - TILE_W * 2} y={y0} width={x1 - x0 + TILE_W * 4} height={y1 - y0} fill={`url(#${patterns}-bands)`} />
          </g>
          <g className="flood-drift-slow">
            <rect x={x0 - TILE_W * 2} y={y0} width={x1 - x0 + TILE_W * 4} height={y1 - y0} fill={`url(#${patterns}-ribbons)`} />
          </g>
          <g className="flood-foam">
            <rect x={x0 - TILE_W * 2} y={y0} width={x1 - x0 + TILE_W * 4} height={y1 - y0} fill={`url(#${patterns}-foam)`} />
          </g>
          {/* Leading great wave: rides the front edge, then rests outside the region (masked). */}
          <CrestColumn x={x1 + 8} y0={y0} y1={y1} scale={1.05} />
        </g>
        {/* Secondary waves overlap the first and roll on through. */}
        <g className="flood-follow flood-follow-1" style={{ ["--sweep" as string]: `${sweep}px`, ["--exit" as string]: `${x1 - x0}px` }}>
          <CrestColumn x={x0} y0={y0 + 40} y1={y1} scale={0.8} fill={INDIGO} inner={ICE} />
        </g>
        <g className="flood-follow flood-follow-2" style={{ ["--sweep" as string]: `${sweep}px`, ["--exit" as string]: `${x1 - x0}px` }}>
          <CrestColumn x={x0} y0={y0 - 30} y1={y1} scale={0.62} fill={TURQUOISE} inner={FOAM} />
        </g>
      </g>
    </g>
  );
}
