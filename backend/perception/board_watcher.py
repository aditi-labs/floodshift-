"""Board-only piece tracking for the live demo.

Design (operator-proposed): calibrate with an empty board, keep that view as the
reference, and treat only what appears *inside the board* afterwards as a candidate.

- Board polygon: the UV unit square mapped back through the camera homography. Pixels
  outside it (carpet, hands at the edge, the laptop) are never candidates.
- Candidates come from two sources: (1) the printed-bridge colour+shape rule, which
  runs every frame and needs no reference; (2) change against the reference view,
  gain-matched so auto-exposure drift does not light up the whole board, and bounded
  in area so sensor noise (too small) and hands (too large) are ignored.
- Each track is classified at most once: by the bridge rule, or by one Perceptron call
  per track when Perceptron is configured. No background subtraction, no per-frame API calls.
- Optional colour filter (color_filter=True): change candidates must also fall inside the
  yellow mask of the printed pieces (bridge_profile.json), so shadows, hands, cables and the
  projector's own overlay never become tracks or cost a Perceptron call. While it is on, a
  piece printed in another colour is invisible to the watcher - toggle it off for those.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import time

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

from backend.perception.bridge_detector import (
    detect_bridges,
    isolate_yellow,
    load_profile,
    yellow_mask,
)

UNIT_SQUARE = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)


@dataclass
class Track:
    track_id: int
    center: tuple[float, float]
    bbox: tuple[int, int, int, int]
    first_frame: int
    last_frame: int
    stable_frames: int = 0
    missing: int = 0
    token_type: str | None = None
    class_source: str | None = None
    rotation_deg: float = 0.0
    queried: bool = False  # classifier consulted (once per track)
    sent: bool = False
    note: str = ''
    history: list = field(default_factory=list, repr=False)

    @property
    def identified(self) -> bool:
        return self.token_type is not None


class BoardWatcher:
    def __init__(self, classifier=None, *, stability_frames: int = 20, match_px: float = 40,
                 move_px: float = 8, grace_frames: int = 15, min_area_fraction: float = 0.002,
                 max_area_fraction: float = 0.06, diff_threshold: int = 35, cooldown_s: float = 2.0,
                 color_filter: bool = False, profile: dict | None = None, clock=time.monotonic):
        if cv2 is None:
            raise ImportError('opencv-contrib-python required')
        self.classifier = classifier
        self.color_filter = color_filter  # may be toggled at runtime (live demo: Y key)
        self.profile = profile or load_profile()
        self.color_mask: np.ndarray | None = None  # yellow pixels of the current frame, when filtering
        self.color_fraction = 0.0  # fraction of the board that is yellow (HUD / status)
        self.stability_frames = stability_frames
        self.match_px = match_px
        self.move_px = move_px
        self.grace_frames = grace_frames
        self.min_area_fraction = min_area_fraction
        self.max_area_fraction = max_area_fraction
        self.diff_threshold = diff_threshold
        self.cooldown_s = cooldown_s
        self.clock = clock
        self.homography = None
        self.quad_px: np.ndarray | None = None
        self._mask: np.ndarray | None = None
        self._board_area: float = 0.0
        self.reference: np.ndarray | None = None
        self.tracks: dict[int, Track] = {}
        self._next_id = 1
        self._sent_positions: list[tuple[float, float]] = []
        self._last_query = -1e9
        self.changed_fraction = 0.0
        self.classifier_calls = 0

    # ------------------------------------------------------------------ board
    def set_board(self, homography, frame_shape) -> None:
        """Board polygon in pixels from the camera->UV homography (None = whole frame)."""
        self.homography = homography
        h, w = frame_shape[:2]
        if homography is None:
            self.quad_px = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
        else:
            inverse = np.linalg.inv(homography)
            self.quad_px = cv2.perspectiveTransform(UNIT_SQUARE.reshape(-1, 1, 2), inverse).reshape(4, 2)
        self._mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillConvexPoly(self._mask, self.quad_px.astype(np.int32), 255)
        self._board_area = float(cv2.countNonZero(self._mask))

    @property
    def calibrated(self) -> bool:
        return self.homography is not None

    def inside(self, point) -> bool:
        if self.quad_px is None:
            return True
        return cv2.pointPolygonTest(self.quad_px.astype(np.float32), (float(point[0]), float(point[1])), False) >= 0

    def board_uv(self, point) -> tuple[float, float] | None:
        if self.homography is None:
            return None
        uv = cv2.perspectiveTransform(np.array([[[point[0], point[1]]]], dtype=np.float32), self.homography)[0, 0]
        return float(uv[0]), float(uv[1])

    def capture_reference(self, frames: list[np.ndarray]) -> None:
        """Median of several frames of the EMPTY board; call right after calibration."""
        grays = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]).astype(np.float32)
        self.reference = cv2.GaussianBlur(np.median(grays, axis=0).astype(np.uint8), (5, 5), 0)
        if self._mask is None:
            self.set_board(None, frames[0].shape)

    @property
    def reference_ready(self) -> bool:
        return self.reference is not None and self._mask is not None

    # ------------------------------------------------------------- candidates
    def _change_candidates(self, frame: np.ndarray) -> list[dict]:
        if not self.reference_ready:
            return []
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0).astype(np.float32)
        # Gain match on the board so exposure drift is not read as change.
        now_mean = cv2.mean(gray, mask=self._mask)[0]
        ref_mean = cv2.mean(self.reference.astype(np.float32), mask=self._mask)[0]
        gain = float(np.clip(ref_mean / max(now_mean, 1.0), 0.7, 1.4))
        diff = cv2.absdiff(np.clip(gray * gain, 0, 255).astype(np.uint8), self.reference)
        _, changed = cv2.threshold(diff, self.diff_threshold, 255, cv2.THRESH_BINARY)
        changed = cv2.bitwise_and(changed, self._mask)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        changed = cv2.morphologyEx(changed, cv2.MORPH_OPEN, kernel)
        changed = cv2.morphologyEx(changed, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
        # Measured before the colour gate so a lighting change still shows as "whole board changed".
        self.changed_fraction = cv2.countNonZero(changed) / max(self._board_area, 1.0)
        if self.color_filter and self.color_mask is not None:
            changed = cv2.bitwise_and(changed, self.color_mask)
        contours, _ = cv2.findContours(changed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        out = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if not self.min_area_fraction * self._board_area <= area <= self.max_area_fraction * self._board_area:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            out.append({'center': (x + w / 2, y + h / 2), 'bbox': (x, y, w, h), 'kind': 'change'})
        return out

    def _bridge_candidates(self, frame: np.ndarray) -> list[dict]:
        out = []
        for d in detect_bridges(frame, region_mask=self._mask):
            if self.inside(d.center):
                out.append({'center': d.center, 'bbox': (int(d.x1), int(d.y1), int(d.x2 - d.x1), int(d.y2 - d.y1)),
                            'kind': 'bridge', 'rotation_deg': d.rotation_deg})
        return out

    # ----------------------------------------------------------------- update
    def update(self, frame: np.ndarray, frame_id: int) -> list[Track]:
        """Process one frame; returns tracks that are identified, stable and not yet sent."""
        if self._mask is None:
            self.set_board(None, frame.shape)
        self._update_color_mask(frame)
        candidates = self._bridge_candidates(frame)
        for blob in self._change_candidates(frame):
            # A change blob under a bridge detection is the same object.
            if all(np.hypot(blob['center'][0] - b['center'][0], blob['center'][1] - b['center'][1]) > self.match_px
                   for b in candidates):
                candidates.append(blob)

        matched = set()
        for cand in candidates:
            best, best_d = None, self.match_px
            for track in self.tracks.values():
                if track.track_id in matched:
                    continue
                d = np.hypot(cand['center'][0] - track.center[0], cand['center'][1] - track.center[1])
                if d < best_d:
                    best, best_d = track, d
            if best is None:
                best = Track(self._next_id, cand['center'], cand['bbox'], frame_id, frame_id)
                self._next_id += 1
                self.tracks[best.track_id] = best
                # A piece that was already deployed and briefly lost must not be sent again.
                if any(np.hypot(cand['center'][0] - p[0], cand['center'][1] - p[1]) < self.match_px
                       for p in self._sent_positions):
                    best.sent = True
                    best.note = 'already deployed'
            else:
                best.stable_frames = best.stable_frames + 1 if best_d < self.move_px else 0
                best.center, best.bbox = cand['center'], cand['bbox']
            best.last_frame, best.missing = frame_id, 0
            matched.add(best.track_id)
            if cand['kind'] == 'bridge':
                best.rotation_deg = cand['rotation_deg']
                if best.token_type is None and (self.classifier is None or not getattr(self.classifier, 'available', False)):
                    best.token_type, best.class_source = 'bridge', 'local_cv'
                    best.queried = True
                else:
                    best.note = best.note or 'bridge rule'

        for track in list(self.tracks.values()):
            if track.track_id not in matched:
                track.missing += 1
                if track.missing > self.grace_frames:
                    if track.sent:
                        self._sent_positions.append(track.center)
                    del self.tracks[track.track_id]

        self._classify_stable()
        return [t for t in self.tracks.values()
                if t.identified and t.stable_frames >= self.stability_frames and not t.sent]

    def _update_color_mask(self, frame: np.ndarray) -> None:
        """Yellow mask of this frame, restricted to the board; None when the filter is off."""
        if not self.color_filter:
            self.color_mask, self.color_fraction = None, 0.0
            return
        mask = yellow_mask(frame, self.profile)
        if self._mask is not None:
            mask = cv2.bitwise_and(mask, self._mask)
        self.color_mask = mask
        self.color_fraction = cv2.countNonZero(mask) / max(self._board_area, 1.0)

    def _classify_stable(self) -> None:
        """One classifier call covers every stable, unqueried track in the frame."""
        pending = [t for t in self.tracks.values()
                   if t.stable_frames >= self.stability_frames and not t.queried]
        if not pending:
            return
        available = self.classifier is not None and getattr(self.classifier, 'available', False)
        if not available:
            for track in pending:
                track.queried = True
                if track.token_type is None:
                    track.note = 'unknown: Perceptron unavailable, not the bridge'
            return
        if self.clock() - self._last_query < self.cooldown_s:
            return
        self._last_query = self.clock()
        self.classifier_calls += 1
        boxes = self.classifier.classify_frame(self._last_frame) if hasattr(self, '_last_frame') else []
        for track in pending:
            track.queried = True
            near = [b for b in boxes if b.token_type and
                    np.hypot(b.center[0] - track.center[0], b.center[1] - track.center[1]) < 100]
            if near:
                box = min(near, key=lambda b: np.hypot(b.center[0] - track.center[0], b.center[1] - track.center[1]))
                if track.note == 'bridge rule' and box.token_type != 'bridge':
                    track.note = f'bridge rule disagrees with Perceptron ({box.token_type}); using Perceptron'
                track.token_type, track.class_source = box.token_type, box.source
            elif track.note == 'bridge rule':
                track.token_type, track.class_source = 'bridge', 'local_cv'
                track.note = 'Perceptron returned nothing here; bridge rule used'
            else:
                track.note = 'unknown: Perceptron returned nothing here'

    def observe(self, frame: np.ndarray, frame_id: int) -> list[Track]:
        self._last_frame = frame
        return self.update(frame, frame_id)

    def mark_sent(self, track_id: int, note: str) -> None:
        if track_id in self.tracks:
            self.tracks[track_id].sent = True
            self.tracks[track_id].note = note

    # ------------------------------------------------------------------- draw
    def draw(self, frame: np.ndarray, status: str = '', isolate: bool = False) -> np.ndarray:
        """Debug view. isolate=True shows the colour-filtered feed: only yellow keeps its colour."""
        if isolate:
            mask = self.color_mask if self.color_filter and self.color_mask is not None else None
            out = isolate_yellow(frame, self.profile, mask)
        else:
            out = frame.copy()
        if self.quad_px is not None:
            cv2.polylines(out, [self.quad_px.astype(np.int32)], True, (255, 200, 0), 2)
        for t in self.tracks.values():
            x, y, w, h = t.bbox
            color = (0, 200, 0) if t.sent else (0, 255, 255) if t.identified else (160, 160, 160)
            cv2.rectangle(out, (x, y), (x + w, y + h), color, 2)
            label = f"#{t.track_id} {t.token_type or '?'}"
            if t.class_source:
                label += f" [{t.class_source}]"
            label += f" {t.stable_frames}" if not t.sent else ' SENT'
            cv2.putText(out, label, (x, max(15, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
            if t.note:
                cv2.putText(out, t.note[:48], (x, y + h + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
        if status:
            cv2.putText(out, status, (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        return out
