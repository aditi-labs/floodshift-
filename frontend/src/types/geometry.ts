import type { UV } from "./contracts";

// board_uv (0,0) = printed-map top-left on ALL screens. Width is fixed at 1000 SVG
// units; height follows the scenario's physical aspect (A3 schematic by default, square
// for the HOT-derived map). `export let` is a live binding, so callers see updates.
export const BOARD_WIDTH = 1000;
export let BOARD_HEIGHT = 707.14; // 1000 * 297 / 420

/** Call once when GET /scenario arrives, before rendering that scenario. */
export function setBoardAspect(widthOverHeight: number | undefined) {
  if (widthOverHeight && Number.isFinite(widthOverHeight) && widthOverHeight > 0) BOARD_HEIGHT = BOARD_WIDTH / widthOverHeight;
}

export function toSvgPoint(u: number, v: number) {
  return { x: u * BOARD_WIDTH, y: v * BOARD_HEIGHT };
}

export function uvToPoints(path: UV[]): string {
  return path.map(([u, v]) => `${(u * BOARD_WIDTH).toFixed(1)},${(v * BOARD_HEIGHT).toFixed(1)}`).join(" ");
}

export function uvToPathD(path: UV[], closed = false): string {
  const d = path
    .map(([u, v], i) => `${i === 0 ? "M" : "L"}${(u * BOARD_WIDTH).toFixed(1)} ${(v * BOARD_HEIGHT).toFixed(1)}`)
    .join(" ");
  return closed ? `${d} Z` : d;
}

/** ArUco corner fiducial centres from backend/calibration/board.py; projector must leave these dark. */
export const FIDUCIAL_CORNERS: UV[] = [
  [0.04, 0.04],
  [0.96, 0.04],
  [0.96, 0.96],
  [0.04, 0.96],
];
