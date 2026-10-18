"""Fit backend/perception/bridge_profile.json from photos of the printed bridge piece.

    python scripts/calibrate_bridge_detector.py hardware/tokens/bridge/photo_top.jpg [more.jpg ...]

Each photo must show exactly one bridge piece on a plain background (board paper is
fine). Shoot new photos at the final camera height, under venue light, with the
projector showing a typical overlay, then re-run; the fitted ranges widen to cover
every photo. This is the whole "training" step: no neural network is trained.
"""
import argparse
from datetime import date
import json
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.perception.bridge_detector import (  # noqa: E402
    DEFAULT_PROFILE, PROFILE_PATH, _upright_crop, count_rungs, detect_bridges)


def dominant_yellow(hsv: np.ndarray) -> np.ndarray:
    """Saturated pixels in the yellow band; the piece is the only such object in a photo."""
    h, s, v = cv2.split(hsv)
    return (s > 70) & (v > 50) & (h >= 10) & (h <= 45)


def fit(paths: list[Path]) -> dict:
    hues, sats, vals, aspects, rungs = [], [], [], [], []
    for path in paths:
        img = cv2.imread(str(path))
        if img is None:
            raise SystemExit(f'cannot read {path}')
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        mask = dominant_yellow(hsv)
        if mask.sum() < 500:
            raise SystemExit(f'{path}: no yellow piece found')
        hues.append(np.percentile(hsv[..., 0][mask], [2, 98]))
        sats.append(np.percentile(hsv[..., 1][mask], 5))
        vals.append(np.percentile(hsv[..., 2][mask], 5))
        contours, _ = cv2.findContours(mask.astype(np.uint8) * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contour = max(contours, key=cv2.contourArea)
        rect = cv2.minAreaRect(contour)
        (_, _), (w, h), _ = rect
        aspects.append(max(w, h) / max(1.0, min(w, h)))
        rungs.append(count_rungs(_upright_crop(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), rect)))
    profile = dict(DEFAULT_PROFILE)
    profile.update({
        'hue_min': int(max(0, min(h[0] for h in hues) - 7)),
        'hue_max': int(min(180, max(h[1] for h in hues) + 8)),
        'sat_min': int(max(40, min(sats) * 0.6)),
        'val_min': int(max(40, min(vals) * 0.5)),
        'aspect_min': round(max(1.1, min(aspects) * 0.75), 2),
        'aspect_max': round(max(aspects) * 1.6, 2),
        'rungs_min': int(max(3, min(rungs) - 2)),
        'rungs_max': int(max(rungs) + 6),
        'fitted_from': [str(p) for p in paths], 'fitted_on': date.today().isoformat(),
        'observed': {'hue_range': [float(min(h[0] for h in hues)), float(max(h[1] for h in hues))],
                     'aspect': [round(min(aspects), 2), round(max(aspects), 2)], 'rungs': sorted(set(rungs))},
    })
    return profile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('photos', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, default=PROFILE_PATH)
    args = parser.parse_args()
    profile = fit(args.photos)
    # Every training photo must be detected with the fitted profile before it is saved.
    for path in args.photos:
        hits = detect_bridges(cv2.imread(str(path)), profile)
        if len(hits) != 1:
            raise SystemExit(f'{path}: fitted profile finds {len(hits)} bridges, expected 1')
    args.output.write_text(json.dumps(profile, indent=2) + '\n')
    print(json.dumps(profile, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
