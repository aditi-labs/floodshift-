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

from backend.perception.perceptron_adapter import PerceptronAdapter
from backend.perception.board_watcher import BoardWatcher

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
STABILITY_FRAMES = 20  # Frames a piece must sit still before it is classified/sent
PERCEPTRON_COOLDOWN = 2.0  # Seconds between Perceptron calls (one call covers all pending pieces)
REFERENCE_FRAMES = 15  # frames of the empty board averaged into the change reference
STATUS_SECONDS = 4  # how long a rejection reason stays on the HUD

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

CLASSIFIER = PerceptronAdapter(mock_mode=False)  # Perceptron when configured, local bridge rule otherwise


# =============================================================================
# BACKEND API
# =============================================================================

async def send_observation_to_backend(track, board_uv, frame_count):
    """Send a confirmed ObjectObservation; the gateway resolves the pad and world version."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BACKEND_URL}/perception/observe",
                json={
                    "event_type": "object_observed",
                    "event_id": f"live-{track.track_id}-{int(time.time()*1000)}",
                    "frame_id": frame_count,
                    "token_id": f"tracked-{track.track_id}",
                    "object_type": track.token_type,
                    "class_source": track.class_source or "perceptron",
                    "board_uv": list(board_uv),
                    "rotation_deg": track.rotation_deg,
                    "stable_ms": int(track.stable_frames * 1000 / 30),
                    "vision_status": "confirmed",
                    "frame_provenance": f"live:camera{CAMERA_INDEX}:frame-{frame_count}",
                    "latency_ms": CLASSIFIER.last_latency_ms,
                },
                timeout=5.0
            )
            return response.json()
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

    # Classifier: Perceptron when a key + SDK are present, otherwise the local bridge rule
    api_key = os.environ.get("PERCEPTRON_API_KEY")
    if CLASSIFIER.available:
        print("Perceptron: configured (sponsor model classifies all six pieces)")
    else:
        print(f"WARNING: Perceptron unavailable ({CLASSIFIER.unavailable_reason}).")
        print("Only the printed BRIDGE can be recognised, by the local colour+shape rule (shown as LOCAL_CV).")

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
        "perceptron": "ready" if CLASSIFIER.available else (CLASSIFIER.unavailable_reason or "not_connected"),
        "classifier": "perceptron" if CLASSIFIER.available else "local_cv_bridge_only",
        "mode": "live"
    })

    watcher = BoardWatcher(CLASSIFIER, stability_frames=STABILITY_FRAMES, cooldown_s=PERCEPTRON_COOLDOWN)
    ret, frame = cap.read()
    watcher.set_board(homography, frame.shape if ret else (CAMERA_HEIGHT, CAMERA_WIDTH))

    def capture_reference():
        """Average the EMPTY board into the change reference, after a visible countdown."""
        print("Clear the board (no hands, no pieces). Capturing the empty-board reference...")
        deadline = time.time() + 3
        while time.time() < deadline:
            ok, f = cap.read()
            if ok:
                cv2.putText(f, f"CLEAR THE BOARD - reference in {deadline - time.time():.0f}s", (20, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 200, 255), 2)
                cv2.imshow("FLOODSHIFT Camera", watcher.draw(f))
                cv2.waitKey(1)
        frames = []
        while len(frames) < REFERENCE_FRAMES:
            ok, f = cap.read()
            if ok:
                frames.append(f)
        watcher.capture_reference(frames)
        watcher.tracks.clear()
        print("Reference captured. Pieces placed inside the board from now on are candidates.")

    capture_reference()
    world_version = await get_world_version()
    frame_count = 0
    hud_message, hud_until = "", 0.0

    print("\n" + "="*50)
    print("LIVE DETECTION RUNNING")
    print("="*50)
    print("Place pieces inside the board - only the board area is watched.")
    print("Keys: Q quit | R re-capture empty-board reference | C re-calibrate")
    if homography is None:
        print("WARNING: not calibrated - placements cannot be matched to pads until the 4 ArUco corners are found.")
    print("="*50 + "\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        frame_count += 1

        ready = watcher.observe(frame, frame_count)
        for track in ready:
            board_uv = watcher.board_uv(track.center)
            if board_uv is None:
                watcher.mark_sent(track.track_id, "not calibrated: no board coordinates")
                hud_message, hud_until = "NOT CALIBRATED - press C with all 4 corners visible", time.time() + STATUS_SECONDS
                continue
            print(f"Sending {track.token_type} ({track.class_source}) at uv=({board_uv[0]:.3f}, {board_uv[1]:.3f})...")
            result = await send_observation_to_backend(track, board_uv, frame_count)
            if result.get('accepted'):
                world_version = result.get('world_version', world_version)
                watcher.mark_sent(track.track_id, f"accepted @ {result.get('site_id')}")
                hud_message, hud_until = f"{track.token_type.upper()} ACCEPTED at {result.get('site_id')}", time.time() + STATUS_SECONDS
                print(f"  -> ACCEPTED at {result.get('site_id')}, world v{world_version}")
            else:
                reason = result.get('rejection_reason') or result.get('error') or 'rejected'
                watcher.mark_sent(track.track_id, f"rejected: {reason}")  # do not retry the same placement
                hud_message, hud_until = f"{track.token_type.upper()} REJECTED: {reason}", time.time() + STATUS_SECONDS
                print(f"  -> REJECTED: {reason}")

        if frame_count % 30 == 0:
            await update_perception_status({
                "objects_tracked": len(watcher.tracks),
                "last_detection": time.strftime("%H:%M:%S"),
                "changed_board_fraction": round(watcher.changed_fraction, 3),
            })
            if watcher.changed_fraction > 0.4:
                print("Most of the board differs from the reference (lighting changed?). Press R to re-capture.")

        status = f"World v{world_version} | tracks {len(watcher.tracks)} | {'calibrated' if watcher.calibrated else 'NOT CALIBRATED'}"
        debug_frame = watcher.draw(frame, status)
        if time.time() < hud_until:
            cv2.putText(debug_frame, hud_message, (20, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)
        cv2.putText(debug_frame, "Q quit | R reference | C calibrate",
                    (20, frame.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
        cv2.imshow("FLOODSHIFT Camera", debug_frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        if key == ord('r'):
            capture_reference()
        if key == ord('c'):
            homography = calibrate_camera(cap)
            watcher.set_board(homography, frame.shape)
            capture_reference()
            await update_perception_status({"calibration": "calibrated" if homography is not None else "uncalibrated"})

        await asyncio.sleep(0.005)

    cap.release()
    cv2.destroyAllWindows()
    print("\nDemo stopped.")


if __name__ == "__main__":
    asyncio.run(main())
