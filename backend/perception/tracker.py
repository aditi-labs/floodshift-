"""
Markerless Object Tracker
Person 3 owns this file.

Uses OpenCV object tracking to follow tokens WITHOUT QR codes.
Perceptron identifies objects once, then tracker follows them smoothly.

Flow:
1. Detect motion/new object in frame
2. Call Perceptron to identify what it is
3. Initialize OpenCV tracker on that region
4. Tracker follows object at 30fps (no more API calls needed)
5. If object lost, re-detect with Perceptron
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import numpy as np
from typing import Callable

try:
    import cv2
except ImportError:
    cv2 = None


class TrackerState(str, Enum):
    """State of a tracked object."""
    DETECTING = "detecting"      # Waiting for Perceptron to identify
    TRACKING = "tracking"        # Actively tracking with OpenCV
    LOST = "lost"               # Tracker lost the object
    STABLE = "stable"           # Object hasn't moved, confirmed position


@dataclass
class TrackedObject:
    """A single tracked object on the board."""
    track_id: int
    token_type: str | None = None  # Set by Perceptron
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, w, h
    center_px: tuple[float, float] = (0.0, 0.0)
    board_uv: tuple[float, float] | None = None
    state: TrackerState = TrackerState.DETECTING
    confidence: float = 0.0
    last_seen_frame: int = 0
    stable_frames: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)

    # Internal OpenCV tracker
    _cv_tracker: object = field(default=None, repr=False)


class MarkerlessTracker:
    """
    Tracks objects without markers using motion detection + Perceptron + OpenCV trackers.

    Usage:
        tracker = MarkerlessTracker()

        while True:
            frame = camera.read()

            # Update all tracked objects
            events = tracker.update(frame, frame_id)

            # Check if we need to identify new objects
            if tracker.needs_identification():
                regions = tracker.get_unidentified_regions()
                # Call Perceptron on these regions
                results = perceptron.detect(frame, regions)
                tracker.apply_identifications(results)

            # Get confirmed observations
            for obj in tracker.get_stable_objects():
                send_to_world_service(obj)
    """

    def __init__(
        self,
        stability_threshold_frames: int = 18,  # ~600ms at 30fps
        lost_threshold_frames: int = 30,       # 1 second
        min_object_area: int = 1000,           # Minimum pixels to track
        max_objects: int = 10,
        tracker_type: str = "CSRT"             # CSRT is most accurate
    ):
        if cv2 is None:
            raise ImportError("opencv-contrib-python required")

        self.stability_threshold = stability_threshold_frames
        self.lost_threshold = lost_threshold_frames
        self.min_object_area = min_object_area
        self.max_objects = max_objects
        self.tracker_type = tracker_type

        # State
        self._objects: dict[int, TrackedObject] = {}
        self._next_id: int = 1
        self._frame_count: int = 0
        self._background: np.ndarray | None = None
        self._prev_frame: np.ndarray | None = None

    def _create_cv_tracker(self):
        """Create an OpenCV tracker instance."""
        trackers = {
            "CSRT": cv2.TrackerCSRT_create,
            "KCF": cv2.TrackerKCF_create,
            "MIL": cv2.TrackerMIL_create,
        }
        creator = trackers.get(self.tracker_type, cv2.TrackerCSRT_create)
        return creator()

    def update(self, frame: np.ndarray, frame_id: int) -> list[dict]:
        """
        Update all tracked objects with new frame.

        Returns list of events (new_object, object_lost, object_stable, etc.)
        """
        self._frame_count = frame_id
        events = []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Update existing trackers
        lost_ids = []
        for track_id, obj in self._objects.items():
            if obj._cv_tracker is not None:
                success, bbox = obj._cv_tracker.update(frame)

                if success:
                    x, y, w, h = [int(v) for v in bbox]
                    old_center = obj.center_px
                    new_center = (x + w/2, y + h/2)

                    # Check if object moved
                    movement = np.sqrt(
                        (new_center[0] - old_center[0])**2 +
                        (new_center[1] - old_center[1])**2
                    )

                    obj.bbox = (x, y, w, h)
                    obj.center_px = new_center
                    obj.last_seen_frame = frame_id

                    if movement < 5:  # Less than 5 pixels = stable
                        obj.stable_frames += 1
                        if obj.stable_frames >= self.stability_threshold:
                            if obj.state != TrackerState.STABLE:
                                obj.state = TrackerState.STABLE
                                events.append({
                                    "type": "object_stable",
                                    "track_id": track_id,
                                    "token_type": obj.token_type,
                                    "center": obj.center_px
                                })
                    else:
                        obj.stable_frames = 0
                        obj.state = TrackerState.TRACKING
                else:
                    obj.state = TrackerState.LOST
                    lost_ids.append(track_id)
                    events.append({
                        "type": "object_lost",
                        "track_id": track_id
                    })

        # Remove lost objects after threshold
        for track_id in list(self._objects.keys()):
            obj = self._objects[track_id]
            if frame_id - obj.last_seen_frame > self.lost_threshold:
                del self._objects[track_id]
                events.append({
                    "type": "object_removed",
                    "track_id": track_id
                })

        # Detect new objects via motion/background subtraction
        if self._prev_frame is not None and len(self._objects) < self.max_objects:
            new_regions = self._detect_new_objects(gray, frame)
            for region in new_regions:
                if not self._region_overlaps_existing(region):
                    track_id = self._next_id
                    self._next_id += 1

                    x, y, w, h = region
                    obj = TrackedObject(
                        track_id=track_id,
                        bbox=region,
                        center_px=(x + w/2, y + h/2),
                        state=TrackerState.DETECTING,
                        last_seen_frame=frame_id
                    )

                    # Initialize tracker
                    obj._cv_tracker = self._create_cv_tracker()
                    obj._cv_tracker.init(frame, region)

                    self._objects[track_id] = obj
                    events.append({
                        "type": "new_object",
                        "track_id": track_id,
                        "bbox": region
                    })

        self._prev_frame = gray.copy()
        return events

    def _detect_new_objects(
        self,
        gray: np.ndarray,
        frame: np.ndarray
    ) -> list[tuple[int, int, int, int]]:
        """Detect new objects using frame differencing."""
        if self._background is None:
            self._background = gray.astype(np.float32)
            return []

        # Update background model slowly
        cv2.accumulateWeighted(gray, self._background, 0.02)

        # Compute difference from background
        diff = cv2.absdiff(gray, cv2.convertScaleAbs(self._background))
        _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)

        # Clean up noise
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

        # Find contours
        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        regions = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > self.min_object_area:
                x, y, w, h = cv2.boundingRect(contour)
                # Add padding
                pad = 20
                x = max(0, x - pad)
                y = max(0, y - pad)
                w = min(frame.shape[1] - x, w + 2*pad)
                h = min(frame.shape[0] - y, h + 2*pad)
                regions.append((x, y, w, h))

        return regions

    def _region_overlaps_existing(
        self,
        region: tuple[int, int, int, int]
    ) -> bool:
        """Check if region overlaps with any existing tracked object."""
        x1, y1, w1, h1 = region
        cx1, cy1 = x1 + w1/2, y1 + h1/2

        for obj in self._objects.values():
            x2, y2, w2, h2 = obj.bbox
            cx2, cy2 = x2 + w2/2, y2 + h2/2

            # Check center distance
            dist = np.sqrt((cx1 - cx2)**2 + (cy1 - cy2)**2)
            if dist < max(w1, w2, h1, h2):
                return True

        return False

    def needs_identification(self) -> bool:
        """Check if any objects need Perceptron identification."""
        return any(
            obj.state == TrackerState.DETECTING and obj.token_type is None
            for obj in self._objects.values()
        )

    def get_unidentified_regions(self) -> list[dict]:
        """Get regions that need Perceptron identification."""
        return [
            {
                "track_id": obj.track_id,
                "bbox": obj.bbox,
                "center": obj.center_px
            }
            for obj in self._objects.values()
            if obj.state == TrackerState.DETECTING and obj.token_type is None
        ]

    def apply_identification(
        self,
        track_id: int,
        token_type: str,
        confidence: float = 1.0
    ) -> None:
        """Apply Perceptron identification to a tracked object."""
        if track_id in self._objects:
            obj = self._objects[track_id]
            obj.token_type = token_type
            obj.confidence = confidence
            obj.state = TrackerState.TRACKING

    def get_stable_objects(self) -> list[TrackedObject]:
        """Get objects that are stable and identified."""
        return [
            obj for obj in self._objects.values()
            if obj.state == TrackerState.STABLE and obj.token_type is not None
        ]

    def get_all_objects(self) -> list[TrackedObject]:
        """Get all tracked objects."""
        return list(self._objects.values())

    def set_board_uv(
        self,
        track_id: int,
        board_uv: tuple[float, float]
    ) -> None:
        """Set board UV coordinates for a tracked object."""
        if track_id in self._objects:
            self._objects[track_id].board_uv = board_uv

    def remove_object(self, track_id: int) -> None:
        """Manually remove a tracked object."""
        if track_id in self._objects:
            del self._objects[track_id]

    def reset(self) -> None:
        """Reset all tracking state."""
        self._objects.clear()
        self._next_id = 1
        self._background = None
        self._prev_frame = None

    def get_debug_frame(self, frame: np.ndarray) -> np.ndarray:
        """Draw tracking visualization on frame."""
        debug = frame.copy()

        colors = {
            TrackerState.DETECTING: (0, 255, 255),  # Yellow
            TrackerState.TRACKING: (255, 165, 0),    # Orange
            TrackerState.STABLE: (0, 255, 0),        # Green
            TrackerState.LOST: (0, 0, 255),          # Red
        }

        for obj in self._objects.values():
            x, y, w, h = obj.bbox
            color = colors.get(obj.state, (255, 255, 255))

            # Draw bounding box
            cv2.rectangle(debug, (x, y), (x+w, y+h), color, 2)

            # Draw label
            label = f"#{obj.track_id}"
            if obj.token_type:
                label += f" {obj.token_type}"
            if obj.state == TrackerState.STABLE:
                label += " ✓"

            cv2.putText(
                debug, label, (x, y - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2
            )

            # Draw center point
            cx, cy = int(obj.center_px[0]), int(obj.center_px[1])
            cv2.circle(debug, (cx, cy), 5, color, -1)

        return debug
