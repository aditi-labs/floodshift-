"""Local OpenCV detector for the printed FLOODSHIFT bridge piece.

Perceptron remains the semantic classifier for every piece. This detector exists for
two jobs: (1) verify that a region Perceptron called "bridge" really looks like our
printed bridge, and (2) classify the bridge when Perceptron is unavailable, in which
case the observation is labelled class_source="local_cv", never "perceptron".

It is a fitted colour + shape rule, not a trained neural network: the thresholds in
bridge_profile.json come from photos of the actual piece (scripts/calibrate_bridge_detector.py).
Refit it after photographing the piece under venue light with the projector on.

Signature of the piece (top view): one saturated-yellow blob, elongated, with a ladder
deck - evenly spaced transverse slats between two raised rails - and flared end tabs.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import json
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover - import guard mirrors tracker.py
    cv2 = None

PROFILE_PATH = Path(__file__).with_name('bridge_profile.json')
DEFAULT_PROFILE = {
    # OpenCV hue is 0-180. Fitted range for the yellow filament with margin for lighting.
    'hue_min': 18, 'hue_max': 36, 'sat_min': 60, 'val_min': 50,
    # Yellow area as a fraction of the frame: rejects speckle and a yellow tablecloth.
    'min_area_fraction': 0.0004, 'max_area_fraction': 0.25,
    # Long side / short side of the minimum-area rectangle around the blob.
    'aspect_min': 1.3, 'aspect_max': 4.0,
    # Transverse slats counted along the deck (the piece has about nine).
    'rungs_min': 4, 'rungs_max': 16,
    'fitted_from': [], 'fitted_on': None,
}


def load_profile(path: Path | str = PROFILE_PATH) -> dict:
    profile = dict(DEFAULT_PROFILE)
    path = Path(path)
    if path.is_file():
        profile.update(json.loads(path.read_text()))
    return profile


@dataclass
class BridgeDetection:
    x1: float
    y1: float
    x2: float
    y2: float
    center: tuple[float, float]
    rotation_deg: float  # orientation of the long axis, image coordinates
    aspect: float
    rung_count: int
    area_px: int
    mention: str = 'yellow printed ladder-deck bridge piece (local colour+shape rule)'
    token_type: str = 'bridge'

    def to_dict(self) -> dict:
        return asdict(self)


def yellow_mask(frame_bgr: np.ndarray, profile: dict) -> np.ndarray:
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    lower = np.array([profile['hue_min'], profile['sat_min'], profile['val_min']], dtype=np.uint8)
    upper = np.array([profile['hue_max'], 255, 255], dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)
    # Close the gaps between slats so the whole piece is one blob, then drop speckle.
    size = max(3, int(round(min(frame_bgr.shape[:2]) / 120)) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return mask


def _upright_crop(gray: np.ndarray, rect) -> np.ndarray:
    """Rotate the min-area rectangle so the long axis is vertical; returns the deck crop."""
    (cx, cy), (w, h), angle = rect
    if w > h:
        angle += 90
        w, h = h, w
    matrix = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    rotated = cv2.warpAffine(gray, matrix, (gray.shape[1], gray.shape[0]), flags=cv2.INTER_LINEAR)
    return cv2.getRectSubPix(rotated, (max(3, int(w)), max(3, int(h))), (cx, cy))


def count_rungs(deck: np.ndarray) -> int:
    """Count transverse slats: brightness ridges along the long (vertical) axis.

    Only the middle of the short axis is used so the raised side rails and end tabs
    do not add edges. The profile is detrended and peaks closer than a plausible slat
    spacing are merged, so one slat never counts twice.
    """
    h, w = deck.shape[:2]
    if h < 12 or w < 4:
        return 0
    inner = deck[int(h * 0.12):int(h * 0.88), int(w * 0.3):int(w * 0.7) or w]
    if inner.size == 0:
        return 0
    profile = inner.astype(np.float32).mean(axis=1)
    smooth = cv2.GaussianBlur(profile.reshape(-1, 1), (1, 0), sigmaX=0, sigmaY=max(1.0, h / 120)).ravel()
    trend = cv2.blur(smooth.reshape(-1, 1), (1, max(3, int(h / 6)) | 1)).ravel()
    signal = smooth - trend
    if signal.std() < 1e-3:
        return 0
    threshold = 0.25 * signal.std()
    min_gap = max(2, int(h / 40))
    peaks, last = 0, -min_gap
    for i in range(1, len(signal) - 1):
        if signal[i] > threshold and signal[i] >= signal[i - 1] and signal[i] >= signal[i + 1] and i - last >= min_gap:
            peaks += 1
            last = i
    return peaks


def detect_bridges(frame_bgr: np.ndarray, profile: dict | None = None) -> list[BridgeDetection]:
    """Find printed bridge pieces in a BGR frame. Pixel coordinates of the input frame."""
    if cv2 is None:
        raise ImportError('opencv-contrib-python required')
    profile = profile or load_profile()
    frame_area = frame_bgr.shape[0] * frame_bgr.shape[1]
    mask = yellow_mask(frame_bgr, profile)
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    found = []
    for contour in contours:
        area = int(cv2.contourArea(contour))
        if not profile['min_area_fraction'] * frame_area <= area <= profile['max_area_fraction'] * frame_area:
            continue
        rect = cv2.minAreaRect(contour)
        (cx, cy), (w, h), angle = rect
        long_side, short_side = max(w, h), max(1.0, min(w, h))
        aspect = long_side / short_side
        if not profile['aspect_min'] <= aspect <= profile['aspect_max']:
            continue
        rungs = count_rungs(_upright_crop(gray, rect))
        if not profile['rungs_min'] <= rungs <= profile['rungs_max']:
            continue
        x, y, bw, bh = cv2.boundingRect(contour)
        rotation = angle + 90 if w > h else angle  # degrees of the long axis from vertical
        found.append(BridgeDetection(x1=float(x), y1=float(y), x2=float(x + bw), y2=float(y + bh),
                                     center=(float(cx), float(cy)), rotation_deg=float(rotation),
                                     aspect=round(aspect, 2), rung_count=rungs, area_px=area))
    return sorted(found, key=lambda d: -d.area_px)


def looks_like_bridge(frame_bgr: np.ndarray, center_px: tuple[float, float], radius_px: float = 80,
                      profile: dict | None = None) -> bool:
    """True when a detected bridge piece lies within radius_px of center_px."""
    return any(np.hypot(d.center[0] - center_px[0], d.center[1] - center_px[1]) <= radius_px
               for d in detect_bridges(frame_bgr, profile))
