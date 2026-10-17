"""
Perceptron AI Adapter
Person 3 owns this file.

Normalizes Perceptron SDK responses and maps to our token types.
The SDK may return .boxes or .points depending on version - we handle both.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import os

# Lazy import perceptron - may not be installed
_perceptron = None


def _get_perceptron():
    global _perceptron
    if _perceptron is None:
        try:
            import perceptron
            _perceptron = perceptron
        except ImportError:
            raise ImportError(
                "perceptron package not installed. "
                "Install with: pip install perceptron"
            )
    return _perceptron


# =============================================================================
# CONFIGURATION
# =============================================================================

# Perceptron class descriptions for detection
# These should match the physical appearance of our 3D printed tokens
PERCEPTRON_CLASSES = {
    "hospital": "miniature medical field hospital building with cross symbol",
    "shelter": "miniature sleeping shelter tent with peaked roof",
    "food_shelter": "miniature food and water distribution canopy with bowl symbol",
    "bridge": "miniature emergency bridge span structure",
    "disaster_start": "miniature orange storm warning marker or button",
    "person": "miniature human figurine standing upright",
}

# Reverse mapping from Perceptron mention text to our token types
# We'll fuzzy match against these
MENTION_TO_TOKEN = {
    "hospital": "hospital",
    "medical": "hospital",
    "cross": "hospital",
    "shelter": "shelter",
    "tent": "shelter",
    "sleeping": "shelter",
    "food": "food_shelter",
    "water": "food_shelter",
    "canopy": "food_shelter",
    "distribution": "food_shelter",
    "bridge": "bridge",
    "span": "bridge",
    "crossing": "bridge",
    "storm": "disaster_start",
    "warning": "disaster_start",
    "start": "disaster_start",
    "orange": "disaster_start",
    "person": "person",
    "human": "person",
    "figurine": "person",
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SemanticBox:
    """Normalized bounding box from Perceptron."""
    mention: str  # Raw text from model
    token_type: str | None  # Mapped token type
    x1: float  # Left edge in pixels
    y1: float  # Top edge in pixels
    x2: float  # Right edge in pixels
    y2: float  # Bottom edge in pixels
    confidence: float | None = None

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1


class PerceptronStatus(str, Enum):
    CONNECTED = "connected"
    NOT_CONNECTED = "not_connected"
    ERROR = "error"
    MOCK = "mock"


# =============================================================================
# ADAPTER
# =============================================================================

class PerceptronAdapter:
    """
    Adapter for Perceptron AI semantic detection.

    Handles:
    - SDK version differences (.boxes vs .points)
    - Coordinate normalization (0-1000 scale to pixels)
    - Mention text to token type mapping
    - Error handling and mock mode
    """

    def __init__(self, model: str = "perceptron-mk1.5", mock_mode: bool = False):
        self.model = model
        self.mock_mode = mock_mode

        if mock_mode:
            self._status = PerceptronStatus.MOCK
        else:
            self._status = PerceptronStatus.NOT_CONNECTED
            # Verify API key is available
            api_key = os.environ.get("PERCEPTRON_API_KEY")
            if not api_key:
                print("WARNING: PERCEPTRON_API_KEY not set, using mock mode")
                self.mock_mode = True
                self._status = PerceptronStatus.MOCK

    @property
    def status(self) -> PerceptronStatus:
        return self._status

    def recognize_board(
        self,
        frame_path: str | Path,
        frame_width: int,
        frame_height: int
    ) -> list[SemanticBox]:
        """
        Detect objects in a board frame using Perceptron.

        Args:
            frame_path: Path to saved frame image
            frame_width: Width of frame in pixels
            frame_height: Height of frame in pixels

        Returns:
            List of detected semantic boxes with token types
        """
        if self.mock_mode:
            return self._mock_recognize(frame_path)

        try:
            perceptron = _get_perceptron()

            # Call Perceptron detect
            response = perceptron.detect(
                str(frame_path),
                classes=list(PERCEPTRON_CLASSES.values()),
                model=self.model,
            )

            self._status = PerceptronStatus.CONNECTED

            # Handle different SDK versions
            detections = getattr(response, "boxes", None)
            if detections is None:
                detections = getattr(response, "points", None)
            if detections is None:
                detections = []

            # Normalize results
            boxes = []
            for det in detections:
                box = self._normalize_detection(det, frame_width, frame_height)
                if box:
                    boxes.append(box)

            return boxes

        except Exception as e:
            print(f"Perceptron error: {e}")
            self._status = PerceptronStatus.ERROR
            return []

    def _normalize_detection(
        self,
        detection,
        width: int,
        height: int
    ) -> SemanticBox | None:
        """Normalize a single detection from Perceptron format."""
        try:
            mention = str(getattr(detection, "mention", ""))

            # Get coordinates - may be in 0-1000 normalized format
            top_left = getattr(detection, "top_left", None)
            bottom_right = getattr(detection, "bottom_right", None)

            if top_left is None or bottom_right is None:
                return None

            # Convert from 0-1000 scale to pixels
            x1 = float(getattr(top_left, "x", 0)) / 1000 * width
            y1 = float(getattr(top_left, "y", 0)) / 1000 * height
            x2 = float(getattr(bottom_right, "x", 0)) / 1000 * width
            y2 = float(getattr(bottom_right, "y", 0)) / 1000 * height

            # Map mention to token type
            token_type = self._mention_to_token_type(mention)

            return SemanticBox(
                mention=mention,
                token_type=token_type,
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2
            )

        except Exception as e:
            print(f"Error normalizing detection: {e}")
            return None

    def _mention_to_token_type(self, mention: str) -> str | None:
        """Map Perceptron mention text to our token type."""
        mention_lower = mention.lower()

        # Check each keyword
        for keyword, token_type in MENTION_TO_TOKEN.items():
            if keyword in mention_lower:
                return token_type

        return None

    def _mock_recognize(self, frame_path: str | Path) -> list[SemanticBox]:
        """Return mock detections for testing without API."""
        self._status = PerceptronStatus.MOCK

        # Return a mock bridge detection
        return [
            SemanticBox(
                mention="miniature emergency bridge span structure",
                token_type="bridge",
                x1=400,
                y1=300,
                x2=500,
                y2=400
            )
        ]


# =============================================================================
# SMOKE TEST
# =============================================================================

def smoke_test(image_path: str) -> None:
    """
    Run a smoke test against Perceptron API.
    Requires PERCEPTRON_API_KEY environment variable.

    Usage:
        python -c "from backend.perception.perceptron_adapter import smoke_test; smoke_test('path/to/image.jpg')"
    """
    import json

    adapter = PerceptronAdapter(mock_mode=False)

    if adapter.mock_mode:
        print("ERROR: No API key, cannot run smoke test")
        return

    path = Path(image_path)
    if not path.exists():
        print(f"ERROR: Image not found: {path}")
        return

    # Assume standard HD frame
    boxes = adapter.recognize_board(path, 1280, 720)

    print(f"Status: {adapter.status}")
    print(f"Detections: {len(boxes)}")
    for box in boxes:
        print(json.dumps({
            "mention": box.mention,
            "token_type": box.token_type,
            "center": box.center,
            "size": (box.width, box.height)
        }, indent=2))
