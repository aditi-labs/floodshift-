"""
Perceptron AI Adapter
Person 3 owns this file.

Normalizes Perceptron SDK responses and maps to our token types.
The SDK may return .boxes or .points depending on version - we handle both.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
import os
import re
import tempfile
import time

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

from backend.perception.bridge_detector import detect_bridges, looks_like_bridge

CATALOG_PATH = Path(__file__).resolve().parents[2] / 'contracts' / 'token_catalog.json'
# Filament colours of the printed pieces we have photographed (hardware/tokens/<type>/photo_top.jpg).
PIECE_COLORS = {'bridge': 'yellow'}

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

# Fallback class descriptions; the catalog (P1's top-view descriptions) overrides these.
FALLBACK_CLASSES = {
    "hospital": "miniature medical field hospital building with cross symbol",
    "shelter": "miniature sleeping shelter tent with peaked roof",
    "food_shelter": "miniature food and water distribution canopy with bowl symbol",
    "bridge": "yellow 3D-printed ladder-like bridge: long narrow deck with evenly spaced "
              "transverse slats between two raised side rails and flared tabs at both ends",
    "disaster_start": "miniature orange storm warning marker or button",
    "person": "miniature human figurine standing upright",
}


def load_classes(catalog_path: Path = CATALOG_PATH) -> dict[str, str]:
    """Perceptron class prompts: one per printed piece, from contracts/token_catalog.json."""
    classes = dict(FALLBACK_CLASSES)
    try:
        tokens = json.loads(catalog_path.read_text(encoding="utf-8"))['tokens']
    except (OSError, ValueError, KeyError):
        return classes
    for token_type, entry in tokens.items():
        hint = entry.get('perceptron_hint')
        if hint:
            color = PIECE_COLORS.get(token_type)
            classes[token_type] = f"small {color + ' ' if color else ''}3D-printed game piece, {hint}"
    return classes


PERCEPTRON_CLASSES = load_classes()

# Keywords in Perceptron's mention text, scored per token type. Whole-word matching, so
# "crossing" cannot count as the hospital's "cross". The first group has weight 3.
MENTION_KEYWORDS = {
    "hospital": (("hospital",), ("medical", "cross", "clinic")),
    "shelter": (("shelter", "tent"), ("sleeping", "refuge", "pitched")),
    "food_shelter": (("food", "canopy"), ("water", "distribution", "bowl", "supplies")),
    "bridge": (("bridge", "ladder"), ("span", "crossing", "slats", "slat", "deck", "rails")),
    "disaster_start": (("storm", "warning"), ("start", "orange", "triangle", "button")),
    "person": (("person", "figurine"), ("human", "people", "silhouette", "figure")),
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
    source: str = "perceptron"  # "perceptron" | "local_cv" | "mock"
    rotation_deg: float | None = None
    verified_by_local_cv: bool | None = None  # bridge boxes only: local rule agreed

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

    def __init__(self, model: str = "perceptron-mk1.5", mock_mode: bool = False,
                 local_fallback: bool = True):
        self.model = model
        self.mock_mode = mock_mode
        self.local_fallback = local_fallback
        self.unavailable_reason: str | None = None
        self.last_latency_ms: int | None = None

        if mock_mode:
            self._status = PerceptronStatus.MOCK
        else:
            # Without a key the adapter reports NOT_CONNECTED and returns no boxes. It never
            # fabricates a detection in live mode; classify_frame may use the local rule.
            self._status = PerceptronStatus.NOT_CONNECTED
            if not os.environ.get("PERCEPTRON_API_KEY"):
                self.unavailable_reason = "missing_api_key"
                print("WARNING: PERCEPTRON_API_KEY not set; Perceptron classification disabled")
            else:
                try:
                    _get_perceptron()
                except ImportError:
                    self.unavailable_reason = "sdk_not_installed"
                    print("WARNING: perceptron SDK not installed; Perceptron classification disabled")

    @property
    def available(self) -> bool:
        return self.mock_mode or self.unavailable_reason is None

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
        if self.unavailable_reason:
            return []

        try:
            perceptron = _get_perceptron()

            # Call Perceptron detect
            started = time.perf_counter()
            response = perceptron.detect(
                str(frame_path),
                classes=list(PERCEPTRON_CLASSES.values()),
                model=self.model,
            )
            self.last_latency_ms = int((time.perf_counter() - started) * 1000)

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
        """Map Perceptron mention text to our token type by scored whole-word keywords."""
        words = set(re.findall(r"[a-z]+", mention.lower()))
        if not words:
            return None
        scores = {token: 3 * len(words & set(strong)) + len(words & set(weak))
                  for token, (strong, weak) in MENTION_KEYWORDS.items()}
        best = max(scores, key=lambda t: (scores[t], t))
        if scores[best] == 0:
            return None
        return best

    def classify_frame(self, frame_bgr: np.ndarray) -> list[SemanticBox]:
        """Classify every piece visible in a BGR frame.

        Perceptron first (sponsor model). Its bridge boxes are cross-checked with the
        local printed-bridge rule and annotated, never overruled. When Perceptron is
        unavailable or returns nothing, the local rule may classify bridges only,
        with source="local_cv" so the UI shows LOCAL_CV rather than a model call.
        """
        if cv2 is None:
            raise ImportError("opencv-contrib-python required")
        height, width = frame_bgr.shape[:2]
        boxes: list[SemanticBox] = []
        if self.available:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
                temp_path = handle.name
            try:
                cv2.imwrite(temp_path, frame_bgr)
                boxes = self.recognize_board(temp_path, width, height)
            finally:
                Path(temp_path).unlink(missing_ok=True)
            for box in boxes:
                if box.token_type == "bridge":
                    box.verified_by_local_cv = looks_like_bridge(frame_bgr, box.center, max(box.width, box.height))
        if boxes or not self.local_fallback:
            return boxes
        started = time.perf_counter()
        local = [SemanticBox(mention=d.mention, token_type="bridge", x1=d.x1, y1=d.y1, x2=d.x2, y2=d.y2,
                             source="local_cv", rotation_deg=d.rotation_deg, verified_by_local_cv=True)
                 for d in detect_bridges(frame_bgr)]
        self.last_latency_ms = int((time.perf_counter() - started) * 1000)
        return local

    def _mock_recognize(self, frame_path: str | Path) -> list[SemanticBox]:
        """Return mock detections for testing without API."""
        self._status = PerceptronStatus.MOCK

        # Return a mock bridge detection (explicit mock mode only; tests)
        return [
            SemanticBox(
                mention="miniature emergency bridge span structure",
                token_type="bridge",
                x1=400,
                y1=300,
                x2=500,
                y2=400,
                source="mock",
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
