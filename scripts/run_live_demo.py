#!/usr/bin/env python3
"""
FLOODSHIFT Live Demo Runner
Connects: Camera -> Perceptron -> Backend -> Frontend

This script:
1. Opens camera feed with debug window (operator sees this)
2. Calibrates using ArUco markers
3. Detects tokens using Perceptron AI
4. Sends token placements to backend API
5. Backend broadcasts to frontend via WebSocket

Run: python scripts/run_live_demo.py
"""
import asyncio
import os
import sys
import time
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

import cv2
import numpy as np
import httpx

# =============================================================================
# CONFIGURATION
# =============================================================================

CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", 1))  # From .env or default to 1
CAMERA_WIDTH = int(os.environ.get("CAMERA_WIDTH", 1280))
CAMERA_HEIGHT = int(os.environ.get("CAMERA_HEIGHT", 720))

BACKEND_URL = "http://localhost:8000"

# ArUco corner markers
ARUCO_DICT = cv2.aruco.DICT_4X4_100
CORNER_MARKERS = {
    10: (0.04, 0.04),  # Top-left
    11: (0.96, 0.04),  # Top-right
    12: (0.96, 0.96),  # Bottom-right
    13: (0.04, 0.96),  # Bottom-left
}

# Token detection settings
STABILITY_FRAMES = 20  # Frames object must be stable before detection
PERCEPTRON_COOLDOWN = 2.0  # Seconds between API calls
MIN_OBJECT_AREA = 1000  # Minimum contour area to consider

# =============================================================================
# SIMPLE OBJECT TRACKER
# =============================================================================

class SimpleTracker:
    """Track objects without markers using contour detection."""

    def __init__(self):
        self.tracked_objects = {}  # id -> {center, frames_stable, identified, token_type}
        self.next_id = 1
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=500, varThreshold=50, detectShadows=False
        )

    def update(self, frame):
        """Update tracker with new frame, return list of stable unidentified objects."""
        # Apply background subtraction
        fg_mask = self.bg_subtractor.apply(frame)

        # Clean up mask
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)

        # Find contours
        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Get centers of significant contours
        current_centers = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > MIN_OBJECT_AREA:
                M = cv2.moments(contour)
                if M["m00"] > 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    current_centers.append((cx, cy, area))

        # Match to existing tracked objects
        matched_ids = set()
        for cx, cy, area in current_centers:
            best_id = None
            best_dist = 50  # Max distance to match

            for obj_id, obj in self.tracked_objects.items():
                if obj_id in matched_ids:
                    continue
                dist = np.sqrt((cx - obj['center'][0])**2 + (cy - obj['center'][1])**2)
                if dist < best_dist:
                    best_dist = dist
                    best_id = obj_id

            if best_id:
                # Update existing object
                self.tracked_objects[best_id]['center'] = (cx, cy)
                self.tracked_objects[best_id]['frames_stable'] += 1
                matched_ids.add(best_id)
            else:
                # New object
                self.tracked_objects[self.next_id] = {
                    'center': (cx, cy),
                    'frames_stable': 1,
                    'identified': False,
                    'token_type': None,
                    'sent_to_backend': False
                }
                self.next_id += 1

        # Remove lost objects
        lost_ids = [oid for oid in self.tracked_objects if oid not in matched_ids]
        for oid in lost_ids:
            del self.tracked_objects[oid]

        # Return stable unidentified objects
        return [
            (oid, obj) for oid, obj in self.tracked_objects.items()
            if obj['frames_stable'] >= STABILITY_FRAMES and not obj['identified']
        ]

    def mark_identified(self, obj_id, token_type):
        """Mark object as identified."""
        if obj_id in self.tracked_objects:
            self.tracked_objects[obj_id]['identified'] = True
            self.tracked_objects[obj_id]['token_type'] = token_type

    def mark_sent(self, obj_id):
        """Mark object as sent to backend."""
        if obj_id in self.tracked_objects:
            self.tracked_objects[obj_id]['sent_to_backend'] = True

    def get_unsent_objects(self):
        """Get identified objects not yet sent to backend."""
        return [
            (oid, obj) for oid, obj in self.tracked_objects.items()
            if obj['identified'] and not obj['sent_to_backend']
        ]

    def draw_debug(self, frame):
        """Draw debug visualization on frame."""
        for obj_id, obj in self.tracked_objects.items():
            cx, cy = obj['center']

            if obj['identified']:
                color = (0, 255, 0)  # Green for identified
                label = f"{obj['token_type']}"
                if obj['sent_to_backend']:
                    label += " [SENT]"
            else:
                color = (0, 255, 255)  # Yellow for tracking
                label = f"#{obj_id} ({obj['frames_stable']})"

            cv2.circle(frame, (cx, cy), 30, color, 3)
            cv2.putText(frame, label, (cx - 40, cy - 40),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        return frame


# =============================================================================
# CALIBRATION
# =============================================================================

def calibrate_camera(cap):
    """Run calibration to find ArUco corners and compute homography."""
    print("\n" + "="*50)
    print("CALIBRATION")
    print("="*50)
    print("Looking for ArUco markers (IDs 10, 11, 12, 13)...")
    print("Press C when all corners are visible, Q to skip")

    try:
        aruco_dict = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
        aruco_params = cv2.aruco.DetectorParameters()
        detector = cv2.aruco.ArucoDetector(aruco_dict, aruco_params)
    except Exception as e:
        print(f"ArUco setup error: {e}")
        return None

    homography = None

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        # Detect markers
        try:
            corners, ids, _ = detector.detectMarkers(frame)
        except Exception as e:
            print(f"Detection error: {e}")
            continue

        found_corners = {}
        if ids is not None:
            for i, marker_id in enumerate(ids.flatten()):
                if marker_id in CORNER_MARKERS:
                    center = corners[i][0].mean(axis=0)
                    found_corners[marker_id] = center
                    cv2.circle(frame, (int(center[0]), int(center[1])), 15, (0, 255, 0), -1)
                    cv2.putText(frame, f"ID:{marker_id}",
                               (int(center[0]) + 20, int(center[1])),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        # Status display
        status = f"Corners: {len(found_corners)}/4"
        color = (0, 255, 0) if len(found_corners) >= 4 else (0, 165, 255) if len(found_corners) >= 2 else (0, 0, 255)
        cv2.putText(frame, status, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)

        if len(found_corners) >= 4:
            cv2.putText(frame, "Press C to calibrate (4 corners found!)", (20, 80),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        elif len(found_corners) == 3:
            cv2.putText(frame, "Need 4 corners (have 3) - find 1 more", (20, 80),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        try:
            cv2.imshow("FLOODSHIFT Calibration", frame)
        except Exception as e:
            print(f"Display error: {e}")
            break

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            print("Skipping calibration - using pixel normalization")
            break
        elif key == ord('c') and len(found_corners) >= 4:
            # Compute homography (requires 4+ points)
            src_pts = np.array([found_corners[mid] for mid in found_corners], dtype=np.float32)
            dst_pts = np.array([CORNER_MARKERS[mid] for mid in found_corners], dtype=np.float32)
            homography, _ = cv2.findHomography(src_pts, dst_pts)
            print(f"Calibration successful with {len(found_corners)} corners!")
            break

    cv2.destroyWindow("FLOODSHIFT Calibration")
    return homography


def pixel_to_board(homography, px_x, px_y, frame_width, frame_height):
    """Convert pixel coordinates to board UV (0-1)."""
    if homography is not None:
        pt = np.array([[[px_x, px_y]]], dtype=np.float32)
        transformed = cv2.perspectiveTransform(pt, homography)
        return (float(transformed[0][0][0]), float(transformed[0][0][1]))
    else:
        # Fallback: simple normalization
        return (px_x / frame_width, px_y / frame_height)


# =============================================================================
# PERCEPTRON DETECTION
# =============================================================================

def detect_with_perceptron(frame, frame_path=None):
    """Use Perceptron AI to identify objects in frame."""
    try:
        import perceptron

        # Save frame to temp file if not provided
        if frame_path is None:
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
                frame_path = f.name
                cv2.imwrite(frame_path, frame)

        # Call Perceptron
        response = perceptron.detect(
            frame_path,
            classes=[
                "miniature emergency bridge span structure",
                "miniature medical field hospital building with cross symbol",
                "miniature food and water distribution station",
                "miniature sleeping shelter tent",
                "miniature orange storm warning marker",
                "miniature human figurine"
            ],
            model="perceptron-mk1.5"
        )

        # Parse response
        detections = []
        boxes = getattr(response, "boxes", None) or getattr(response, "points", None) or []

        for box in boxes:
            mention = str(getattr(box, "mention", "")).lower()

            # Map to token type
            token_type = None
            if "bridge" in mention or "span" in mention:
                token_type = "bridge"
            elif "hospital" in mention or "medical" in mention or "cross" in mention:
                token_type = "hospital"
            elif "food" in mention or "water" in mention or "distribution" in mention:
                token_type = "food_shelter"
            elif "shelter" in mention or "tent" in mention:
                token_type = "shelter"
            elif "storm" in mention or "warning" in mention or "orange" in mention:
                token_type = "disaster_start"
            elif "person" in mention or "human" in mention or "figurine" in mention:
                token_type = "person"

            if token_type:
                # Get center coordinates
                top_left = getattr(box, "top_left", None)
                bottom_right = getattr(box, "bottom_right", None)

                if top_left and bottom_right:
                    # Convert from 0-1000 scale to pixels
                    x1 = float(getattr(top_left, "x", 0)) / 1000 * CAMERA_WIDTH
                    y1 = float(getattr(top_left, "y", 0)) / 1000 * CAMERA_HEIGHT
                    x2 = float(getattr(bottom_right, "x", 0)) / 1000 * CAMERA_WIDTH
                    y2 = float(getattr(bottom_right, "y", 0)) / 1000 * CAMERA_HEIGHT

                    center = ((x1 + x2) / 2, (y1 + y2) / 2)
                    detections.append({
                        'token_type': token_type,
                        'center': center,
                        'mention': mention
                    })

        # Clean up temp file
        if frame_path and Path(frame_path).exists():
            Path(frame_path).unlink()

        return detections

    except Exception as e:
        print(f"Perceptron error: {e}")
        return []


# =============================================================================
# BACKEND API
# =============================================================================

async def send_token_to_backend(token_type, board_uv, world_version):
    """Send token placement to backend API."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BACKEND_URL}/action",
                json={
                    "action_id": f"perception-{int(time.time()*1000)}",
                    "type": "place_token",
                    "source": "physical_perceptron",
                    "token_type": token_type,
                    "board_uv": list(board_uv),
                    "expected_world_version": world_version
                },
                timeout=5.0
            )
            result = response.json()
            return result
    except Exception as e:
        print(f"Backend error: {e}")
        return {"accepted": False, "error": str(e)}


async def get_world_version():
    """Get current world version from backend."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{BACKEND_URL}/world", timeout=5.0)
            data = response.json()
            return data.get("world_version", 0)
    except:
        return 0


async def update_perception_status(status: dict):
    """Update perception status in backend."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{BACKEND_URL}/perception/status", json=status, timeout=2.0)
    except:
        pass  # Non-critical


# =============================================================================
# MAIN LOOP
# =============================================================================

async def main():
    print("""
+===========================================================+
|           FLOODSHIFT LIVE PERCEPTION DEMO                 |
|                                                           |
|  Camera Feed -> Perceptron AI -> Backend -> Frontend      |
+===========================================================+
""")

    # Check Perceptron API key
    api_key = os.environ.get("PERCEPTRON_API_KEY")
    if not api_key:
        print("WARNING: PERCEPTRON_API_KEY not set!")
        print("Token detection will not work without it.")
    else:
        print(f"Perceptron API key: {api_key[:10]}...")

    # Check backend
    print("\nChecking backend connection...")
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{BACKEND_URL}/health", timeout=5.0)
            print(f"Backend: {r.json()}")
    except Exception as e:
        print(f"ERROR: Backend not running! Start it first.")
        print(f"Run: python -m uvicorn backend.main:app --port 8000")
        return

    # Open camera
    print(f"\nOpening camera {CAMERA_INDEX}...")
    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)

    if not cap.isOpened():
        print("ERROR: Cannot open camera!")
        return

    print("Camera opened successfully!")

    # Calibrate
    try:
        homography = calibrate_camera(cap)
    except Exception as e:
        print(f"Calibration error: {e}")
        import traceback
        traceback.print_exc()
        homography = None

    # Update perception status
    await update_perception_status({
        "camera": "connected",
        "calibration": "calibrated" if homography is not None else "uncalibrated",
        "perceptron": "ready" if api_key else "no_api_key",
        "mode": "live"
    })

    # Initialize tracker
    tracker = SimpleTracker()
    last_perceptron_call = 0
    world_version = await get_world_version()
    frame_count = 0

    print("\n" + "="*50)
    print("LIVE DETECTION RUNNING")
    print("="*50)
    print("Place tokens on the map - they will be detected!")
    print("Press Q to quit")
    print("="*50 + "\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        frame_count += 1

        # Update tracker
        stable_objects = tracker.update(frame)

        # Check if we should call Perceptron
        now = time.time()
        if stable_objects and (now - last_perceptron_call) > PERCEPTRON_COOLDOWN:
            print(f"Calling Perceptron for {len(stable_objects)} object(s)...")
            last_perceptron_call = now

            # Detect with Perceptron
            detections = detect_with_perceptron(frame)
            print(f"Perceptron found: {detections}")

            # Match detections to tracked objects
            for detection in detections:
                det_center = detection['center']

                # Find closest tracked object
                for obj_id, obj in stable_objects:
                    obj_center = obj['center']
                    dist = np.sqrt((det_center[0] - obj_center[0])**2 +
                                   (det_center[1] - obj_center[1])**2)

                    if dist < 100:  # Within 100 pixels
                        tracker.mark_identified(obj_id, detection['token_type'])
                        print(f"Object #{obj_id} identified as: {detection['token_type']}")
                        break

        # Send identified objects to backend
        unsent = tracker.get_unsent_objects()
        for obj_id, obj in unsent:
            center = obj['center']
            board_uv = pixel_to_board(homography, center[0], center[1],
                                      CAMERA_WIDTH, CAMERA_HEIGHT)

            print(f"Sending {obj['token_type']} at {board_uv} to backend...")
            result = await send_token_to_backend(obj['token_type'], board_uv, world_version)

            if result.get('accepted'):
                print(f"  -> ACCEPTED! New world version: {result.get('world_version')}")
                world_version = result.get('world_version', world_version)
                tracker.mark_sent(obj_id)
            else:
                print(f"  -> REJECTED: {result.get('rejection_reason', result.get('error'))}")
                tracker.mark_sent(obj_id)  # Don't retry

        # Update perception status periodically
        if frame_count % 30 == 0:  # Every second at 30fps
            await update_perception_status({
                "objects_tracked": len(tracker.tracked_objects),
                "last_detection": time.strftime("%H:%M:%S")
            })

        # Draw debug visualization
        debug_frame = tracker.draw_debug(frame.copy())

        # Add status text
        cv2.putText(debug_frame, f"World v{world_version} | Objects: {len(tracker.tracked_objects)}",
                   (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(debug_frame, "Press Q to quit",
                   (20, CAMERA_HEIGHT - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)

        cv2.imshow("FLOODSHIFT Camera", debug_frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        # Small delay to prevent CPU overload
        await asyncio.sleep(0.01)

    cap.release()
    cv2.destroyAllWindows()
    print("\nDemo stopped.")


if __name__ == "__main__":
    asyncio.run(main())
