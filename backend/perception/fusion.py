"""
Vision Fusion - Combines Perceptron semantics with ArUco poses
Person 3 owns this file.

The key insight: ArUco markers provide stable instance identity and precise position,
while Perceptron provides semantic classification (what type of token it is).
We fuse them by matching semantic boxes to nearby marker positions.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
import math

from backend.contracts import ObjectObservation, TokenType, VisionStatus, VisionSource


# =============================================================================
# DATA TYPES
# =============================================================================

@dataclass
class MarkerPose:
    """Tracked marker with position and movement history."""
    marker_id: int
    center_px: tuple[float, float]
    board_uv: tuple[float, float] | None = None
    rotation_deg: float = 0.0
    last_seen_frame: int = 0
    stable_since_ms: int = 0


@dataclass
class SemanticLabel:
    """Semantic classification for a marker."""
    token_type: TokenType
    confidence: float
    source: VisionSource
    last_updated_frame: int


@dataclass
class FusedObservation:
    """Combined marker pose + semantic label."""
    marker_id: int
    token_type: TokenType
    board_uv: tuple[float, float]
    rotation_deg: float
    stable_ms: int
    vision_status: VisionStatus
    class_source: VisionSource
    perceptron_box: tuple[int, int, int, int] | None = None


# =============================================================================
# FUSION ENGINE
# =============================================================================

class VisionFusion:
    """
    Fuses Perceptron semantic detections with ArUco marker tracking.

    Workflow:
    1. ArUco gives us stable marker IDs and positions (every frame)
    2. When a marker is stable for ~600ms, we request Perceptron classification
    3. Perceptron returns semantic boxes (bridge, hospital, etc.)
    4. We match boxes to markers by spatial proximity
    5. We cache the semantic label for each marker until it leaves view

    This means:
    - Perceptron runs infrequently (on stable placement)
    - Marker ID tracks the same physical object continuously
    - Classification persists until object moves significantly
    """

    def __init__(
        self,
        stability_threshold_ms: int = 600,
        match_distance_px: float = 100.0,
        label_expiry_frames: int = 300  # ~10 seconds at 30fps
    ):
        self.stability_threshold_ms = stability_threshold_ms
        self.match_distance_px = match_distance_px
        self.label_expiry_frames = label_expiry_frames

        # State
        self._marker_poses: dict[int, MarkerPose] = {}
        self._semantic_labels: dict[int, SemanticLabel] = {}
        self._frame_counter: int = 0
        self._observation_counter: int = 0

    def update_markers(
        self,
        detections: list[dict],
        frame_id: int,
        homography_fn: callable | None = None
    ) -> None:
        """
        Update tracked markers from ArUco detections.

        Args:
            detections: List of {"marker_id": int, "center_px": (x, y)}
            frame_id: Current frame number
            homography_fn: Optional function to convert px to board UV
        """
        self._frame_counter = frame_id
        seen_ids = set()

        for det in detections:
            marker_id = det["marker_id"]
            center_px = det["center_px"]
            seen_ids.add(marker_id)

            # Convert to board UV if homography available
            board_uv = None
            if homography_fn:
                try:
                    board_uv = homography_fn(center_px[0], center_px[1])
                except:
                    pass

            if marker_id in self._marker_poses:
                pose = self._marker_poses[marker_id]
                # Check if marker moved significantly
                dist = math.sqrt(
                    (center_px[0] - pose.center_px[0]) ** 2 +
                    (center_px[1] - pose.center_px[1]) ** 2
                )
                if dist < 10:  # Less than 10px movement
                    pose.stable_since_ms += 33  # Assume ~30fps
                else:
                    pose.stable_since_ms = 0
                    # Invalidate cached label on significant movement
                    if marker_id in self._semantic_labels:
                        del self._semantic_labels[marker_id]

                pose.center_px = center_px
                pose.board_uv = board_uv
                pose.last_seen_frame = frame_id
            else:
                # New marker
                self._marker_poses[marker_id] = MarkerPose(
                    marker_id=marker_id,
                    center_px=center_px,
                    board_uv=board_uv,
                    last_seen_frame=frame_id,
                    stable_since_ms=0
                )

        # Remove stale markers
        stale = [
            mid for mid, pose in self._marker_poses.items()
            if frame_id - pose.last_seen_frame > 30  # Not seen for ~1 second
        ]
        for mid in stale:
            del self._marker_poses[mid]
            if mid in self._semantic_labels:
                del self._semantic_labels[mid]

    def apply_semantic_detections(
        self,
        boxes: list[dict],
        frame_id: int
    ) -> None:
        """
        Apply Perceptron semantic detections to tracked markers.

        Args:
            boxes: List of {"token_type": str, "center": (x, y), "box": (x1,y1,x2,y2)}
            frame_id: Frame when detection was made
        """
        for box in boxes:
            token_type = box.get("token_type")
            if not token_type:
                continue

            center = box.get("center", (0, 0))

            # Find nearest marker
            best_marker = None
            best_dist = float("inf")

            for marker_id, pose in self._marker_poses.items():
                dist = math.sqrt(
                    (center[0] - pose.center_px[0]) ** 2 +
                    (center[1] - pose.center_px[1]) ** 2
                )
                if dist < best_dist and dist < self.match_distance_px:
                    best_dist = dist
                    best_marker = marker_id

            if best_marker is not None:
                # Assign semantic label to marker
                self._semantic_labels[best_marker] = SemanticLabel(
                    token_type=TokenType(token_type),
                    confidence=1.0,
                    source=VisionSource.PERCEPTRON,
                    last_updated_frame=frame_id
                )

    def get_stable_markers(self) -> list[int]:
        """Get marker IDs that are stable enough for semantic classification."""
        return [
            mid for mid, pose in self._marker_poses.items()
            if pose.stable_since_ms >= self.stability_threshold_ms
            and mid not in self._semantic_labels  # Not yet classified
        ]

    def get_classified_markers(self) -> list[int]:
        """Get marker IDs that have semantic classification."""
        return list(self._semantic_labels.keys())

    def get_fused_observations(self) -> list[FusedObservation]:
        """
        Get all markers that have both position and semantic classification.
        These are ready to be sent as ObjectObservations.
        """
        observations = []

        for marker_id, pose in self._marker_poses.items():
            label = self._semantic_labels.get(marker_id)
            if label is None:
                continue

            # Check if label is expired
            if self._frame_counter - label.last_updated_frame > self.label_expiry_frames:
                continue

            if pose.board_uv is None:
                continue

            observations.append(FusedObservation(
                marker_id=marker_id,
                token_type=label.token_type,
                board_uv=pose.board_uv,
                rotation_deg=pose.rotation_deg,
                stable_ms=pose.stable_since_ms,
                vision_status=VisionStatus.CONFIRMED,
                class_source=label.source
            ))

        return observations

    def create_object_observation(
        self,
        fused: FusedObservation,
        frame_provenance: str
    ) -> ObjectObservation:
        """Convert FusedObservation to ObjectObservation contract."""
        self._observation_counter += 1

        return ObjectObservation(
            event_type="object_observed",
            event_id=f"obs-{self._observation_counter:04d}",
            frame_id=self._frame_counter,
            token_id=f"fiducial-{fused.marker_id}",
            object_type=fused.token_type,
            class_source=fused.class_source,
            perceptron_box_1000=None,  # Could add if needed
            board_uv=fused.board_uv,
            rotation_deg=fused.rotation_deg,
            stable_ms=fused.stable_ms,
            vision_status=fused.vision_status,
            frame_provenance=frame_provenance
        )

    def needs_classification(self) -> bool:
        """Check if there are stable markers waiting for classification."""
        return len(self.get_stable_markers()) > 0

    def clear(self) -> None:
        """Clear all tracking state."""
        self._marker_poses.clear()
        self._semantic_labels.clear()
        self._frame_counter = 0
