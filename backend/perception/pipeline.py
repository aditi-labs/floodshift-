"""
Perception Pipeline - Main runtime loop
Person 3 owns this file.

Connects: Camera → Tracker → Perceptron → API

This is the "brain" that runs during the demo:
1. Reads camera frames
2. Tracks objects (no markers needed!)
3. Identifies new objects with Perceptron
4. Sends confirmed placements to World Service
"""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol
import tempfile
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

from backend.contracts import (
    ObjectObservation, WorldAction, ActionType,
    TokenType, VisionStatus, VisionSource
)
from backend.perception.tracker import MarkerlessTracker, TrackerState
from backend.perception.perceptron_adapter import PerceptronAdapter


class CameraProtocol(Protocol):
    """Interface for camera sources."""
    def read(self) -> tuple[bool, np.ndarray]: ...
    def release(self) -> None: ...
    @property
    def width(self) -> int: ...
    @property
    def height(self) -> int: ...


class ActionSender(Protocol):
    """Interface for sending actions to the world service."""
    async def send_action(self, action: WorldAction) -> dict: ...


@dataclass
class PipelineConfig:
    """Configuration for the perception pipeline."""
    fps_target: int = 30
    perceptron_cooldown_ms: int = 2000  # Min time between API calls
    stability_required_ms: int = 600
    debug_window: bool = False
    save_debug_frames: bool = False
    debug_frame_dir: Path = Path("debug_frames")


class PerceptionPipeline:
    """
    Main perception pipeline for markerless tracking.

    Usage:
        pipeline = PerceptionPipeline(camera, config)
        pipeline.set_action_sender(api_client)

        # Run in async context
        await pipeline.run()
    """

    def __init__(
        self,
        camera: CameraProtocol,
        config: PipelineConfig | None = None,
        homography_fn: Callable[[float, float], tuple[float, float]] | None = None
    ):
        if cv2 is None:
            raise ImportError("opencv-contrib-python required")

        self.camera = camera
        self.config = config or PipelineConfig()
        self.homography_fn = homography_fn

        # Components
        self.tracker = MarkerlessTracker(
            stability_threshold_frames=int(
                self.config.stability_required_ms / 1000 * self.config.fps_target
            )
        )
        self.perceptron = PerceptronAdapter(mock_mode=False)

        # State
        self._running = False
        self._frame_count = 0
        self._last_perceptron_call = 0
        self._action_sender: ActionSender | None = None
        self._world_version = 1
        self._sent_observations: set[int] = set()  # track_ids we've sent

        # Callbacks
        self._on_frame_callbacks: list[Callable] = []
        self._on_detection_callbacks: list[Callable] = []

    def set_action_sender(self, sender: ActionSender) -> None:
        """Set the action sender for world updates."""
        self._action_sender = sender

    def set_world_version(self, version: int) -> None:
        """Update expected world version."""
        self._world_version = version

    def on_frame(self, callback: Callable[[np.ndarray, int], None]) -> None:
        """Register callback for each processed frame."""
        self._on_frame_callbacks.append(callback)

    def on_detection(self, callback: Callable[[ObjectObservation], None]) -> None:
        """Register callback for each confirmed detection."""
        self._on_detection_callbacks.append(callback)

    async def run(self) -> None:
        """Main pipeline loop."""
        self._running = True
        frame_interval = 1.0 / self.config.fps_target

        print(f"[Pipeline] Starting at {self.config.fps_target} fps")
        print(f"[Pipeline] Perceptron mode: {self.perceptron.status}")

        while self._running:
            loop_start = time.time()

            # Read frame
            success, frame = self.camera.read()
            if not success:
                await asyncio.sleep(0.01)
                continue

            self._frame_count += 1

            # Update tracker
            events = self.tracker.update(frame, self._frame_count)

            # Process events
            for event in events:
                if event["type"] == "new_object":
                    print(f"[Pipeline] New object detected: #{event['track_id']}")
                elif event["type"] == "object_stable":
                    print(f"[Pipeline] Object stable: #{event['track_id']} ({event.get('token_type', 'unknown')})")
                elif event["type"] == "object_lost":
                    print(f"[Pipeline] Object lost: #{event['track_id']}")
                    # Allow re-sending if object reappears
                    self._sent_observations.discard(event["track_id"])

            # Check if we need Perceptron identification
            if self.tracker.needs_identification():
                await self._identify_objects(frame)

            # Send stable objects to world service
            await self._send_stable_objects()

            # Debug visualization
            if self.config.debug_window:
                debug_frame = self.tracker.get_debug_frame(frame)
                cv2.imshow("FLOODSHIFT Tracker", debug_frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    self._running = False

            # Callbacks
            for callback in self._on_frame_callbacks:
                callback(frame, self._frame_count)

            # Maintain frame rate
            elapsed = time.time() - loop_start
            if elapsed < frame_interval:
                await asyncio.sleep(frame_interval - elapsed)

        print("[Pipeline] Stopped")

    async def _identify_objects(self, frame: np.ndarray) -> None:
        """Call Perceptron to identify unidentified objects."""
        now = time.time() * 1000
        if now - self._last_perceptron_call < self.config.perceptron_cooldown_ms:
            return  # Cooldown not elapsed

        regions = self.tracker.get_unidentified_regions()
        if not regions:
            return

        # Save frame temporarily for Perceptron
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            temp_path = f.name
            cv2.imwrite(temp_path, frame)

        try:
            print(f"[Pipeline] Calling Perceptron for {len(regions)} object(s)...")
            self._last_perceptron_call = now

            boxes = self.perceptron.recognize_board(
                temp_path,
                self.camera.width,
                self.camera.height
            )

            print(f"[Pipeline] Perceptron found {len(boxes)} object(s)")

            # Match Perceptron boxes to tracked regions
            for region in regions:
                track_id = region["track_id"]
                region_center = region["center"]

                # Find closest Perceptron detection
                best_match = None
                best_dist = float("inf")

                for box in boxes:
                    box_center = box.center
                    dist = np.sqrt(
                        (box_center[0] - region_center[0])**2 +
                        (box_center[1] - region_center[1])**2
                    )
                    if dist < best_dist and dist < 100:  # 100px threshold
                        best_dist = dist
                        best_match = box

                if best_match and best_match.token_type:
                    print(f"[Pipeline] Object #{track_id} identified as: {best_match.token_type}")
                    self.tracker.apply_identification(
                        track_id,
                        best_match.token_type,
                        confidence=1.0
                    )
                else:
                    print(f"[Pipeline] Object #{track_id} could not be identified")

        except Exception as e:
            print(f"[Pipeline] Perceptron error: {e}")
        finally:
            # Clean up temp file
            Path(temp_path).unlink(missing_ok=True)

    async def _send_stable_objects(self) -> None:
        """Send stable, identified objects to world service."""
        if self._action_sender is None:
            return

        for obj in self.tracker.get_stable_objects():
            # Skip if already sent
            if obj.track_id in self._sent_observations:
                continue

            # Calculate board UV if we have homography
            board_uv = None
            if self.homography_fn:
                try:
                    board_uv = self.homography_fn(obj.center_px[0], obj.center_px[1])
                    self.tracker.set_board_uv(obj.track_id, board_uv)
                except Exception as e:
                    print(f"[Pipeline] Homography error: {e}")
                    board_uv = (
                        obj.center_px[0] / self.camera.width,
                        obj.center_px[1] / self.camera.height
                    )
            else:
                # Fallback: normalize to 0-1
                board_uv = (
                    obj.center_px[0] / self.camera.width,
                    obj.center_px[1] / self.camera.height
                )

            # Create observation
            observation = ObjectObservation(
                event_type="object_observed",
                event_id=f"track-{obj.track_id}-{self._frame_count}",
                frame_id=self._frame_count,
                token_id=f"tracked-{obj.track_id}",
                object_type=TokenType(obj.token_type),
                class_source=VisionSource.PERCEPTRON,
                board_uv=board_uv,
                rotation_deg=0.0,
                stable_ms=int(obj.stable_frames * 1000 / self.config.fps_target),
                vision_status=VisionStatus.CONFIRMED,
                frame_provenance=f"live:frame-{self._frame_count}"
            )

            # Notify callbacks
            for callback in self._on_detection_callbacks:
                callback(observation)

            # Create world action
            action = WorldAction(
                action_id=f"perception-{obj.track_id}-{self._frame_count}",
                type=ActionType.PLACE_TOKEN,
                source="physical_perceptron",
                token_id=observation.token_id,
                token_type=TokenType(obj.token_type),
                board_uv=board_uv,
                expected_world_version=self._world_version
            )

            # Send to world service
            try:
                result = await self._action_sender.send_action(action)
                if result.get("accepted"):
                    print(f"[Pipeline] ✓ {obj.token_type} placed at {board_uv}")
                    self._sent_observations.add(obj.track_id)
                    self._world_version = result.get("world_version", self._world_version)
                else:
                    print(f"[Pipeline] ✗ Rejected: {result.get('rejection_reason')}")
            except Exception as e:
                print(f"[Pipeline] Action error: {e}")

    def stop(self) -> None:
        """Stop the pipeline."""
        self._running = False

    def reset(self) -> None:
        """Reset pipeline state."""
        self.tracker.reset()
        self._sent_observations.clear()
        self._frame_count = 0


# =============================================================================
# SIMPLE CAMERA WRAPPER
# =============================================================================

class SimpleCamera:
    """Simple OpenCV camera wrapper."""

    def __init__(self, index: int = 0, width: int = 1280, height: int = 720):
        if cv2 is None:
            raise ImportError("opencv-contrib-python required")

        self._cap = cv2.VideoCapture(index)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open camera {index}")

        print(f"[Camera] Opened camera {index} at {self._width}x{self._height}")

    def read(self) -> tuple[bool, np.ndarray]:
        return self._cap.read()

    def release(self) -> None:
        self._cap.release()

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height


# =============================================================================
# MOCK CAMERA FOR TESTING
# =============================================================================

class MockCamera:
    """Mock camera that returns test frames."""

    def __init__(self, width: int = 1280, height: int = 720):
        self._width = width
        self._height = height
        self._frame_count = 0

    def read(self) -> tuple[bool, np.ndarray]:
        # Create a simple test pattern
        frame = np.ones((self._height, self._width, 3), dtype=np.uint8) * 200

        # Add a moving "object"
        t = self._frame_count / 30  # Time in seconds
        x = int(400 + 100 * np.sin(t))
        y = int(300 + 50 * np.cos(t * 0.5))

        cv2.rectangle(frame, (x, y), (x + 80, y + 80), (50, 50, 200), -1)
        cv2.putText(frame, "TOKEN", (x + 5, y + 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

        self._frame_count += 1
        return True, frame

    def release(self) -> None:
        pass

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height


# =============================================================================
# STANDALONE TEST
# =============================================================================

async def test_pipeline():
    """Test the pipeline with mock camera."""
    print("=" * 50)
    print("FLOODSHIFT Pipeline Test (Mock Camera)")
    print("=" * 50)

    camera = MockCamera()
    config = PipelineConfig(
        fps_target=30,
        debug_window=True,
        perceptron_cooldown_ms=3000
    )

    pipeline = PerceptionPipeline(camera, config)

    # Run for 10 seconds
    async def run_with_timeout():
        try:
            await asyncio.wait_for(pipeline.run(), timeout=10.0)
        except asyncio.TimeoutError:
            pipeline.stop()

    await run_with_timeout()
    camera.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    asyncio.run(test_pipeline())
