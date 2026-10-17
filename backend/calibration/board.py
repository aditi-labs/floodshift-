"""
Board Calibration - Camera to Board Homography
Person 3 owns this file.

Uses ArUco markers at board corners to compute camera-to-board transform.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None  # Allow import without opencv for testing


# =============================================================================
# CONFIGURATION
# =============================================================================

# ArUco dictionary - 4x4 with 100 markers
ARUCO_DICT_TYPE = cv2.aruco.DICT_4X4_100 if cv2 else None

# Board corner marker IDs and their UV positions
# IDs 10-13 are reserved for corners, positioned slightly inward from edges
BOARD_CORNER_MARKERS = {
    10: (0.04, 0.04),  # Top-left
    11: (0.96, 0.04),  # Top-right
    12: (0.96, 0.96),  # Bottom-right
    13: (0.04, 0.96),  # Bottom-left
}

# Token marker IDs (30-39) - instance identity only, NOT semantic type
TOKEN_MARKER_IDS = list(range(30, 40))

# Minimum corners needed for homography
MIN_CORNERS_FOR_HOMOGRAPHY = 3


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class MarkerDetection:
    """Single detected ArUco marker."""
    marker_id: int
    corners_px: np.ndarray  # Shape (4, 2) - four corners in pixel coords
    center_px: tuple[float, float]

    @property
    def is_corner_marker(self) -> bool:
        return self.marker_id in BOARD_CORNER_MARKERS

    @property
    def is_token_marker(self) -> bool:
        return self.marker_id in TOKEN_MARKER_IDS


@dataclass
class CalibrationResult:
    """Result of board calibration attempt."""
    valid: bool
    homography: np.ndarray | None  # 3x3 matrix
    corners_found: list[int]
    error_estimate_mm: float | None
    timestamp: datetime


# =============================================================================
# DETECTOR
# =============================================================================

class BoardCalibrator:
    """
    Detects ArUco markers and computes camera-to-board homography.

    Usage:
        calibrator = BoardCalibrator()
        detections = calibrator.detect_markers(frame)
        result = calibrator.compute_homography(detections)
        if result.valid:
            board_uv = calibrator.pixel_to_board(result.homography, px_x, px_y)
    """

    def __init__(self):
        if cv2 is None:
            raise ImportError("opencv-contrib-python is required for calibration")

        self.aruco_dict = cv2.aruco.getPredefinedDictionary(ARUCO_DICT_TYPE)
        self.aruco_params = cv2.aruco.DetectorParameters()
        self.detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)

        self._last_valid_homography: np.ndarray | None = None
        self._last_calibration_time: datetime | None = None

    def detect_markers(self, frame: np.ndarray) -> list[MarkerDetection]:
        """
        Detect all ArUco markers in a camera frame.

        Args:
            frame: BGR image from camera (numpy array)

        Returns:
            List of detected markers with their corners and centers
        """
        # Convert to grayscale if needed
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        # Detect markers
        corners, ids, rejected = self.detector.detectMarkers(gray)

        detections = []
        if ids is not None:
            for corner, marker_id in zip(corners, ids.flatten()):
                # corner shape is (1, 4, 2), reshape to (4, 2)
                corner_pts = corner.reshape(4, 2)
                center = corner_pts.mean(axis=0)

                detections.append(MarkerDetection(
                    marker_id=int(marker_id),
                    corners_px=corner_pts,
                    center_px=(float(center[0]), float(center[1]))
                ))

        return detections

    def compute_homography(
        self,
        detections: list[MarkerDetection]
    ) -> CalibrationResult:
        """
        Compute camera-to-board homography from corner markers.

        Args:
            detections: List of detected markers

        Returns:
            CalibrationResult with homography matrix if successful
        """
        # Filter to corner markers only
        corner_detections = [d for d in detections if d.is_corner_marker]

        if len(corner_detections) < MIN_CORNERS_FOR_HOMOGRAPHY:
            return CalibrationResult(
                valid=False,
                homography=None,
                corners_found=[d.marker_id for d in corner_detections],
                error_estimate_mm=None,
                timestamp=datetime.utcnow()
            )

        # Build point correspondences
        src_points = []  # Camera pixels
        dst_points = []  # Board UV coordinates

        for det in corner_detections:
            src_points.append(det.center_px)
            dst_points.append(BOARD_CORNER_MARKERS[det.marker_id])

        src = np.array(src_points, dtype=np.float32)
        dst = np.array(dst_points, dtype=np.float32)

        # Compute homography
        # method=0 uses all points, good for 4 correspondences
        H, inliers = cv2.findHomography(src, dst, method=0)

        if H is None:
            return CalibrationResult(
                valid=False,
                homography=None,
                corners_found=[d.marker_id for d in corner_detections],
                error_estimate_mm=None,
                timestamp=datetime.utcnow()
            )

        # Estimate reprojection error
        error = self._estimate_error(src, dst, H)

        # Cache valid homography
        self._last_valid_homography = H.copy()
        self._last_calibration_time = datetime.utcnow()

        return CalibrationResult(
            valid=True,
            homography=H,
            corners_found=[d.marker_id for d in corner_detections],
            error_estimate_mm=error,
            timestamp=datetime.utcnow()
        )

    def _estimate_error(
        self,
        src: np.ndarray,
        dst: np.ndarray,
        H: np.ndarray
    ) -> float:
        """Estimate reprojection error in UV units."""
        # Transform source points
        src_h = np.hstack([src, np.ones((len(src), 1))])
        projected = (H @ src_h.T).T
        projected = projected[:, :2] / projected[:, 2:3]

        # Compute mean error
        error = np.sqrt(((projected - dst) ** 2).sum(axis=1)).mean()
        return float(error)

    def pixel_to_board(
        self,
        H: np.ndarray,
        px_x: float,
        px_y: float
    ) -> tuple[float, float]:
        """
        Transform camera pixel coordinates to board UV coordinates.

        Args:
            H: 3x3 homography matrix
            px_x, px_y: Pixel coordinates in camera frame

        Returns:
            (u, v) normalized board coordinates where (0,0) is top-left
        """
        point = np.array([[[px_x, px_y]]], dtype=np.float32)
        transformed = cv2.perspectiveTransform(point, H)
        u, v = transformed[0, 0]
        return (float(u), float(v))

    def get_token_positions(
        self,
        detections: list[MarkerDetection],
        H: np.ndarray
    ) -> dict[int, tuple[float, float]]:
        """
        Get board UV positions for all token markers.

        Args:
            detections: All detected markers
            H: Valid homography matrix

        Returns:
            Dict mapping marker_id to (u, v) board position
        """
        positions = {}
        for det in detections:
            if det.is_token_marker:
                u, v = self.pixel_to_board(H, *det.center_px)
                # Clamp to valid board range
                u = max(0.0, min(1.0, u))
                v = max(0.0, min(1.0, v))
                positions[det.marker_id] = (u, v)
        return positions

    @property
    def last_valid_homography(self) -> np.ndarray | None:
        """Return cached homography from last successful calibration."""
        return self._last_valid_homography

    @property
    def is_calibrated(self) -> bool:
        """Check if we have a valid cached homography."""
        return self._last_valid_homography is not None


# =============================================================================
# SYNTHETIC TEST DATA
# =============================================================================

def create_synthetic_frame(
    width: int = 1280,
    height: int = 720,
    marker_size: int = 50
) -> tuple[np.ndarray, dict[int, tuple[int, int]]]:
    """
    Create a synthetic test frame with ArUco markers.
    Used for testing without real camera.

    Returns:
        (frame, marker_positions) where marker_positions maps ID to center pixel
    """
    if cv2 is None:
        raise ImportError("opencv-contrib-python required")

    # Create white background
    frame = np.ones((height, width, 3), dtype=np.uint8) * 255

    aruco_dict = cv2.aruco.getPredefinedDictionary(ARUCO_DICT_TYPE)
    marker_positions = {}

    # Draw corner markers at expected positions
    corner_pixels = {
        10: (100, 100),
        11: (width - 100, 100),
        12: (width - 100, height - 100),
        13: (100, height - 100),
    }

    for marker_id, (cx, cy) in corner_pixels.items():
        marker_img = cv2.aruco.generateImageMarker(aruco_dict, marker_id, marker_size)
        # Convert to 3-channel
        marker_img = cv2.cvtColor(marker_img, cv2.COLOR_GRAY2BGR)

        # Place marker
        x1, y1 = cx - marker_size // 2, cy - marker_size // 2
        x2, y2 = x1 + marker_size, y1 + marker_size
        frame[y1:y2, x1:x2] = marker_img
        marker_positions[marker_id] = (cx, cy)

    # Add a token marker in the middle
    token_id = 31
    tx, ty = width // 2, height // 2
    token_marker = cv2.aruco.generateImageMarker(aruco_dict, token_id, marker_size)
    token_marker = cv2.cvtColor(token_marker, cv2.COLOR_GRAY2BGR)
    frame[ty - marker_size//2:ty + marker_size//2,
          tx - marker_size//2:tx + marker_size//2] = token_marker
    marker_positions[token_id] = (tx, ty)

    return frame, marker_positions
