"""
Calibration Tests for FLOODSHIFT
Person 3 owns these tests.

Run with: pytest tests/test_calibration.py -v
"""
import pytest
import numpy as np

# Try to import opencv, skip tests if not available
try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False


pytestmark = pytest.mark.skipif(
    not OPENCV_AVAILABLE,
    reason="opencv-contrib-python not installed"
)


class TestMarkerDetection:
    """Tests for ArUco marker detection."""

    def test_detect_markers_in_synthetic_frame(self):
        from backend.calibration.board import BoardCalibrator, create_synthetic_frame

        frame, expected_positions = create_synthetic_frame()
        calibrator = BoardCalibrator()
        detections = calibrator.detect_markers(frame)

        # Should detect all 5 markers (4 corners + 1 token)
        assert len(detections) == 5

        # Check that we found corner markers
        corner_ids = {d.marker_id for d in detections if d.is_corner_marker}
        assert corner_ids == {10, 11, 12, 13}

        # Check that we found token marker
        token_markers = [d for d in detections if d.is_token_marker]
        assert len(token_markers) == 1
        assert token_markers[0].marker_id == 31

    def test_marker_center_accuracy(self):
        from backend.calibration.board import BoardCalibrator, create_synthetic_frame

        frame, expected_positions = create_synthetic_frame()
        calibrator = BoardCalibrator()
        detections = calibrator.detect_markers(frame)

        # Check detected centers are close to expected
        for det in detections:
            expected = expected_positions[det.marker_id]
            actual = det.center_px

            # Allow 5 pixel tolerance
            assert abs(actual[0] - expected[0]) < 5
            assert abs(actual[1] - expected[1]) < 5


class TestHomographyComputation:
    """Tests for camera-to-board homography."""

    def test_compute_homography_with_all_corners(self):
        from backend.calibration.board import BoardCalibrator, create_synthetic_frame

        frame, _ = create_synthetic_frame()
        calibrator = BoardCalibrator()
        detections = calibrator.detect_markers(frame)
        result = calibrator.compute_homography(detections)

        assert result.valid is True
        assert result.homography is not None
        assert result.homography.shape == (3, 3)
        assert len(result.corners_found) == 4

    def test_homography_fails_with_insufficient_corners(self):
        from backend.calibration.board import BoardCalibrator, MarkerDetection
        import numpy as np

        calibrator = BoardCalibrator()

        # Create detection with only 2 corners
        detections = [
            MarkerDetection(
                marker_id=10,
                corners_px=np.array([[0, 0], [50, 0], [50, 50], [0, 50]]),
                center_px=(25, 25)
            ),
            MarkerDetection(
                marker_id=11,
                corners_px=np.array([[1000, 0], [1050, 0], [1050, 50], [1000, 50]]),
                center_px=(1025, 25)
            ),
        ]

        result = calibrator.compute_homography(detections)
        assert result.valid is False
        assert result.homography is None


class TestCoordinateTransform:
    """Tests for pixel-to-board coordinate transformation."""

    def test_pixel_to_board_corners(self):
        from backend.calibration.board import BoardCalibrator, create_synthetic_frame

        frame, marker_positions = create_synthetic_frame()
        calibrator = BoardCalibrator()
        detections = calibrator.detect_markers(frame)
        result = calibrator.compute_homography(detections)

        assert result.valid

        # Test corner 10 (top-left) -> should be near (0.04, 0.04)
        px = marker_positions[10]
        u, v = calibrator.pixel_to_board(result.homography, px[0], px[1])
        assert abs(u - 0.04) < 0.02
        assert abs(v - 0.04) < 0.02

        # Test corner 12 (bottom-right) -> should be near (0.96, 0.96)
        px = marker_positions[12]
        u, v = calibrator.pixel_to_board(result.homography, px[0], px[1])
        assert abs(u - 0.96) < 0.02
        assert abs(v - 0.96) < 0.02

    def test_pixel_to_board_center(self):
        from backend.calibration.board import BoardCalibrator, create_synthetic_frame

        frame, marker_positions = create_synthetic_frame()
        calibrator = BoardCalibrator()
        detections = calibrator.detect_markers(frame)
        result = calibrator.compute_homography(detections)

        # Token at center pixel should map to ~(0.5, 0.5) board UV
        px = marker_positions[31]
        u, v = calibrator.pixel_to_board(result.homography, px[0], px[1])

        assert abs(u - 0.5) < 0.1
        assert abs(v - 0.5) < 0.1

    def test_get_token_positions(self):
        from backend.calibration.board import BoardCalibrator, create_synthetic_frame

        frame, _ = create_synthetic_frame()
        calibrator = BoardCalibrator()
        detections = calibrator.detect_markers(frame)
        result = calibrator.compute_homography(detections)

        positions = calibrator.get_token_positions(detections, result.homography)

        # Should have token 31
        assert 31 in positions
        u, v = positions[31]

        # Should be in valid range
        assert 0.0 <= u <= 1.0
        assert 0.0 <= v <= 1.0


class TestCalibrationState:
    """Tests for calibration state management."""

    def test_calibrator_caches_homography(self):
        from backend.calibration.board import BoardCalibrator, create_synthetic_frame

        frame, _ = create_synthetic_frame()
        calibrator = BoardCalibrator()

        # Initially not calibrated
        assert not calibrator.is_calibrated
        assert calibrator.last_valid_homography is None

        # After successful calibration
        detections = calibrator.detect_markers(frame)
        result = calibrator.compute_homography(detections)

        assert calibrator.is_calibrated
        assert calibrator.last_valid_homography is not None
        np.testing.assert_array_equal(
            calibrator.last_valid_homography,
            result.homography
        )


class TestErrorEstimation:
    """Tests for calibration error estimation."""

    def test_error_is_small_for_good_calibration(self):
        from backend.calibration.board import BoardCalibrator, create_synthetic_frame

        frame, _ = create_synthetic_frame()
        calibrator = BoardCalibrator()
        detections = calibrator.detect_markers(frame)
        result = calibrator.compute_homography(detections)

        # Error should be very small for synthetic perfect markers
        assert result.error_estimate_mm is not None
        assert result.error_estimate_mm < 0.01  # Less than 1% of UV unit
