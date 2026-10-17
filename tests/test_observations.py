"""
Observation/Perception Tests for FLOODSHIFT
Person 3 owns these tests.

Run with: pytest tests/test_observations.py -v
"""
import pytest
from backend.contracts import TokenType, VisionStatus, VisionSource


class TestPerceptronAdapter:
    """Tests for Perceptron API adapter."""

    def test_mock_mode_returns_detections(self):
        from backend.perception.perceptron_adapter import PerceptronAdapter, PerceptronStatus

        adapter = PerceptronAdapter(mock_mode=True)
        assert adapter.status == PerceptronStatus.MOCK

        boxes = adapter.recognize_board("fake/path.jpg", 1280, 720)
        assert len(boxes) > 0
        assert boxes[0].token_type == "bridge"

    def test_mention_to_token_mapping(self):
        from backend.perception.perceptron_adapter import PerceptronAdapter

        adapter = PerceptronAdapter(mock_mode=True)

        # Test various mention texts
        test_cases = [
            ("miniature medical field hospital", "hospital"),
            ("emergency bridge span", "bridge"),
            ("sleeping shelter tent", "shelter"),
            ("food distribution canopy", "food_shelter"),
            ("orange storm warning marker", "disaster_start"),
            ("human figurine standing", "person"),
        ]

        for mention, expected_type in test_cases:
            result = adapter._mention_to_token_type(mention)
            assert result == expected_type, f"Failed for: {mention}"

    def test_unknown_mention_returns_none(self):
        from backend.perception.perceptron_adapter import PerceptronAdapter

        adapter = PerceptronAdapter(mock_mode=True)
        result = adapter._mention_to_token_type("random unknown object")
        assert result is None


class TestVisionFusion:
    """Tests for vision fusion logic."""

    def test_marker_tracking(self):
        from backend.perception.fusion import VisionFusion

        fusion = VisionFusion()

        # Add some markers
        detections = [
            {"marker_id": 31, "center_px": (400, 300)},
            {"marker_id": 32, "center_px": (600, 400)},
        ]
        fusion.update_markers(detections, frame_id=1)

        assert 31 in fusion._marker_poses
        assert 32 in fusion._marker_poses

    def test_marker_stability_tracking(self):
        from backend.perception.fusion import VisionFusion

        fusion = VisionFusion(stability_threshold_ms=100)

        # Same position for multiple frames
        for i in range(10):
            fusion.update_markers(
                [{"marker_id": 31, "center_px": (400, 300)}],
                frame_id=i
            )

        pose = fusion._marker_poses[31]
        assert pose.stable_since_ms >= 100

        # Should be ready for classification
        assert 31 in fusion.get_stable_markers()

    def test_marker_movement_resets_stability(self):
        from backend.perception.fusion import VisionFusion

        fusion = VisionFusion()

        # Make marker stable
        for i in range(20):
            fusion.update_markers(
                [{"marker_id": 31, "center_px": (400, 300)}],
                frame_id=i
            )

        # Move it significantly
        fusion.update_markers(
            [{"marker_id": 31, "center_px": (500, 400)}],
            frame_id=20
        )

        pose = fusion._marker_poses[31]
        assert pose.stable_since_ms == 0

    def test_semantic_label_assignment(self):
        from backend.perception.fusion import VisionFusion

        fusion = VisionFusion()

        # Add marker
        fusion.update_markers(
            [{"marker_id": 31, "center_px": (400, 300)}],
            frame_id=1
        )

        # Apply semantic detection nearby
        fusion.apply_semantic_detections(
            [{"token_type": "bridge", "center": (410, 310)}],
            frame_id=1
        )

        assert 31 in fusion._semantic_labels
        assert fusion._semantic_labels[31].token_type == TokenType.BRIDGE

    def test_semantic_box_matching_distance(self):
        from backend.perception.fusion import VisionFusion

        fusion = VisionFusion(match_distance_px=50)

        # Add marker
        fusion.update_markers(
            [{"marker_id": 31, "center_px": (400, 300)}],
            frame_id=1
        )

        # Apply detection too far away
        fusion.apply_semantic_detections(
            [{"token_type": "bridge", "center": (600, 500)}],  # >50px away
            frame_id=1
        )

        # Should not be assigned
        assert 31 not in fusion._semantic_labels

    def test_fused_observation_generation(self):
        from backend.perception.fusion import VisionFusion

        def mock_homography(x, y):
            return (x / 1280, y / 720)

        fusion = VisionFusion(stability_threshold_ms=0)

        # Add and classify marker
        fusion.update_markers(
            [{"marker_id": 31, "center_px": (640, 360)}],
            frame_id=1,
            homography_fn=mock_homography
        )
        fusion.apply_semantic_detections(
            [{"token_type": "bridge", "center": (640, 360)}],
            frame_id=1
        )

        observations = fusion.get_fused_observations()
        assert len(observations) == 1

        obs = observations[0]
        assert obs.marker_id == 31
        assert obs.token_type == TokenType.BRIDGE
        assert 0.4 < obs.board_uv[0] < 0.6
        assert 0.4 < obs.board_uv[1] < 0.6

    def test_object_observation_creation(self):
        from backend.perception.fusion import VisionFusion, FusedObservation

        fusion = VisionFusion()

        fused = FusedObservation(
            marker_id=31,
            token_type=TokenType.BRIDGE,
            board_uv=(0.47, 0.61),
            rotation_deg=0.0,
            stable_ms=850,
            vision_status=VisionStatus.CONFIRMED,
            class_source=VisionSource.PERCEPTRON
        )

        obs = fusion.create_object_observation(fused, "test:frame001.png")

        assert obs.event_type == "object_observed"
        assert obs.token_id == "fiducial-31"
        assert obs.object_type == TokenType.BRIDGE
        assert obs.board_uv == (0.47, 0.61)
        assert obs.vision_status == VisionStatus.CONFIRMED

    def test_stale_marker_removal(self):
        from backend.perception.fusion import VisionFusion

        fusion = VisionFusion()

        # Add marker
        fusion.update_markers(
            [{"marker_id": 31, "center_px": (400, 300)}],
            frame_id=1
        )

        # Update without marker for many frames
        for i in range(50):
            fusion.update_markers([], frame_id=i + 10)

        # Should be removed
        assert 31 not in fusion._marker_poses


class TestObjectObservationContract:
    """Tests for ObjectObservation Pydantic model."""

    def test_observation_serialization(self):
        from backend.contracts import ObjectObservation

        obs = ObjectObservation(
            event_type="object_observed",
            event_id="obs-0001",
            frame_id=100,
            token_id="fiducial-31",
            object_type=TokenType.BRIDGE,
            class_source=VisionSource.PERCEPTRON,
            perceptron_box_1000=[400, 300, 500, 400],
            board_uv=(0.47, 0.61),
            rotation_deg=3.0,
            stable_ms=850,
            vision_status=VisionStatus.CONFIRMED,
            frame_provenance="local:frame100.png"
        )

        data = obs.model_dump()

        assert data["event_type"] == "object_observed"
        assert data["token_id"] == "fiducial-31"
        assert data["object_type"] == "bridge"
        assert data["board_uv"] == (0.47, 0.61)

    def test_observation_from_dict(self):
        from backend.contracts import ObjectObservation

        data = {
            "event_type": "object_observed",
            "event_id": "obs-0001",
            "frame_id": 100,
            "token_id": "fiducial-31",
            "object_type": "bridge",
            "class_source": "perceptron",
            "board_uv": [0.47, 0.61],
            "rotation_deg": 0,
            "stable_ms": 850,
            "vision_status": "confirmed",
            "frame_provenance": "test"
        }

        obs = ObjectObservation(**data)
        assert obs.object_type == TokenType.BRIDGE
        assert obs.vision_status == VisionStatus.CONFIRMED
