import type { UV } from "./contracts";

// A3 landscape (420 x 297 mm). board_uv (0,0) = printed-map top-left on ALL screens.
export const BOARD_WIDTH = 1000;
export const BOARD_HEIGHT = 707.14; // 1000 * 297 / 420

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
