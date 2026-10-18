#!/usr/bin/env python3
"""
FLOODSHIFT Demo Setup Pipeline
Step-by-step setup for camera, calibration, and projection.

Run: python scripts/demo_setup.py
"""
import sys
import time

def print_header(step, title):
    print("\n" + "="*60)
    print(f"STEP {step}: {title}")
    print("="*60)

def wait_for_enter(message="Press ENTER to continue..."):
    input(f"\n>>> {message}")

def check_dependencies():
    """Step 0: Check all dependencies are installed."""
    print_header(0, "CHECKING DEPENDENCIES")

    missing = []

    # Check Python packages
    packages = ['cv2', 'numpy', 'fastapi', 'httpx', 'uvicorn']
    for pkg in packages:
        try:
            __import__(pkg)
            print(f"  [OK] {pkg}")
        except ImportError:
            print(f"  [MISSING] {pkg}")
            missing.append(pkg)

    if missing:
        print(f"\nMissing packages: {', '.join(missing)}")
        print("Install with: pip install opencv-contrib-python numpy fastapi httpx uvicorn")
        return False

    print("\nAll dependencies OK!")
    return True

def test_camera():
    """Step 1: Test camera connection."""
    print_header(1, "CAMERA TEST")

    print("""
Make sure:
  1. Camo app is running on iPhone
  2. Camo Studio is running on Windows
  3. iPhone is connected via USB
  4. You can see the camera feed in Camo Studio
""")
    wait_for_enter("Press ENTER when Camo is ready...")

    import cv2

    # Find cameras
    print("\nSearching for cameras...")
    working_cameras = []
    for i in range(5):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                h, w = frame.shape[:2]
                working_cameras.append((i, w, h))
                print(f"  Camera {i}: {w}x{h}")
            cap.release()

    if not working_cameras:
        print("\nNo cameras found! Check Camo connection.")
        return None

    # Use the highest resolution camera (likely iPhone)
    best = max(working_cameras, key=lambda x: x[1] * x[2])
    camera_index = best[0]
    print(f"\nUsing Camera {camera_index} ({best[1]}x{best[2]})")

    # Show preview
    print("\nOpening camera preview...")
    print("  - Position iPhone to look DOWN at your printed map")
    print("  - Make sure ALL 4 corners of map are visible")
    print("  - Press Q when ready")

    cap = cv2.VideoCapture(camera_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    while True:
        ret, frame = cap.read()
        if ret:
            cv2.putText(frame, "Position camera over map - Press Q when ready",
                       (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.imshow("Camera Setup", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

    print("\nCamera setup complete!")
    return camera_index

def calibrate_board(camera_index):
    """Step 2: Calibrate using ArUco markers."""
    print_header(2, "BOARD CALIBRATION")

    print("""
Your printed map needs 4 ArUco markers at the corners:

    [ID:10]─────────────────────[ID:11]
       │                           │
       │      YOUR PRINTED MAP     │
       │                           │
    [ID:13]─────────────────────[ID:12]

Generate markers at: https://chev.me/arucogen/
  - Dictionary: 4x4 (100 markers)
  - IDs: 10, 11, 12, 13
  - Size: 30mm
""")
    wait_for_enter("Press ENTER when markers are on the map...")

    import cv2
    import numpy as np

    # ArUco setup
    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_100)
    aruco_params = cv2.aruco.DetectorParameters()
    detector = cv2.aruco.ArucoDetector(aruco_dict, aruco_params)

    CORNER_MARKERS = {
        10: (0.04, 0.04),  # Top-left
        11: (0.96, 0.04),  # Top-right
        12: (0.96, 0.96),  # Bottom-right
        13: (0.04, 0.96),  # Bottom-left
    }

    cap = cv2.VideoCapture(camera_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    print("\nLooking for ArUco markers...")
    print("  - Make sure all 4 corner markers are visible")
    print("  - Keep camera steady")
    print("  - Press Q to skip (will use fallback)")

    homography = None

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        # Detect markers
        corners, ids, rejected = detector.detectMarkers(frame)

        found_corners = {}
        if ids is not None:
            for i, marker_id in enumerate(ids.flatten()):
                if marker_id in CORNER_MARKERS:
                    center = corners[i][0].mean(axis=0)
                    found_corners[marker_id] = center
                    # Draw marker
                    cv2.circle(frame, (int(center[0]), int(center[1])), 15, (0, 255, 0), -1)
                    cv2.putText(frame, f"ID:{marker_id}",
                               (int(center[0])+20, int(center[1])),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        # Status
        status = f"Found {len(found_corners)}/4 corners"
        color = (0, 255, 0) if len(found_corners) >= 3 else (0, 0, 255)
        cv2.putText(frame, status, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)

        if len(found_corners) >= 3:
            cv2.putText(frame, "CALIBRATION READY - Press C to calibrate",
                       (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        cv2.imshow("Calibration", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('c') and len(found_corners) >= 3:
            # Compute homography
            src_pts = []
            dst_pts = []
            for marker_id, center in found_corners.items():
                src_pts.append(center)
                dst_pts.append(CORNER_MARKERS[marker_id])

            src_pts = np.array(src_pts, dtype=np.float32)
            dst_pts = np.array(dst_pts, dtype=np.float32)

            homography, _ = cv2.findHomography(src_pts, dst_pts)
            print(f"\nCalibration successful! Found {len(found_corners)} corners.")
            break

    cap.release()
    cv2.destroyAllWindows()

    if homography is None:
        print("\nUsing fallback calibration (normalized pixel coordinates)")

    return homography

def start_backend():
    """Step 3: Start the backend server."""
    print_header(3, "BACKEND SERVER")

    print("""
Starting the FLOODSHIFT backend API server...
""")

    import subprocess
    import threading

    def run_server():
        subprocess.run([
            sys.executable, "-m", "uvicorn",
            "backend.main:app",
            "--host", "0.0.0.0",
            "--port", "8000"
        ], cwd="C:/code/floodshift/floodshift-")

    # Check if already running
    import httpx
    try:
        r = httpx.get("http://localhost:8000/health", timeout=2)
        if r.status_code == 200:
            print("Backend already running!")
            return True
    except:
        pass

    # Start in background
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()

    # Wait for startup
    print("Waiting for server to start...")
    for i in range(10):
        time.sleep(1)
        try:
            r = httpx.get("http://localhost:8000/health", timeout=2)
            if r.status_code == 200:
                print("Backend started!")
                print(f"  Health: {r.json()}")
                return True
        except:
            print(f"  Waiting... ({i+1}/10)")

    print("Backend failed to start!")
    return False

def start_frontend():
    """Step 4: Start frontend."""
    print_header(4, "FRONTEND")

    print("""
Open these URLs in your browser:

  OPERATOR DASHBOARD (your laptop):
    http://localhost:5173/

  PROJECTOR VIEW (drag to projector screen):
    http://localhost:5173/projector

Projector controls:
  F = Fullscreen
  M = Overlay mode (black background for projection)
  C = Calibration mode (align with printed map)
""")

    import subprocess
    import os

    # Check if already running
    import httpx
    try:
        r = httpx.get("http://localhost:5173/", timeout=2)
        print("Frontend already running!")
        return True
    except:
        pass

    # Start frontend
    print("Starting frontend...")
    subprocess.Popen(
        ["npm", "run", "dev"],
        cwd="C:/code/floodshift/floodshift-/frontend",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(3)
    print("Frontend should be starting...")
    return True

def calibrate_projector():
    """Step 5: Calibrate projector alignment."""
    print_header(5, "PROJECTOR CALIBRATION")

    print("""
Now align the projector with your printed map:

1. Open http://localhost:5173/projector in a browser
2. Drag that browser window to your PROJECTOR screen
3. Press F for fullscreen
4. Press M for overlay mode (black background)
5. Press C for calibration mode

CALIBRATION CONTROLS:
  Arrow keys  = Move the overlay
  [ ]         = Rotate
  - =         = Scale uniformly
  , .         = Scale X only
  ; '         = Scale Y only
  Shift       = 10x faster
  0           = Reset
  C           = Exit calibration

GOAL: Align the projected crosses with the printed registration marks.
""")
    wait_for_enter("Press ENTER when projector is calibrated...")

def run_perception():
    """Step 6: Run perception pipeline."""
    print_header(6, "TOKEN DETECTION")

    print("""
Now the system will detect physical tokens you place on the map!

The perception pipeline will:
  1. Watch the camera for new objects
  2. Track objects as they move
  3. Identify tokens using Perceptron AI
  4. Send placements to the backend
  5. Update the projection in real-time

Place your physical tokens on the map and watch the projection update!
""")
    wait_for_enter("Press ENTER to start token detection...")

    # This would run the full pipeline
    print("\nStarting perception pipeline...")
    print("(In a full setup, this connects camera -> Perceptron -> backend)")
    print("\nFor now, use keyboard shortcuts in the operator view:")
    print("  1 = Start disaster")
    print("  2 = Place person")
    print("  3 = Place hospital")
    print("  4 = Place food shelter")
    print("  5 = Place shelter")
    print("  6 = Place bridge")
    print("  G = Get AI suggestion")

def main():
    print("""
+---------------------------------------------------------------+
|           FLOODSHIFT DEMO SETUP PIPELINE                      |
|                                                               |
|  This script guides you through setting up:                   |
|    - iPhone camera via Camo                                   |
|    - Board calibration with ArUco markers                     |
|    - Backend API server                                       |
|    - Frontend projection                                      |
|    - Token detection                                          |
+---------------------------------------------------------------+
""")

    # Step 0: Dependencies
    if not check_dependencies():
        return

    # Step 1: Camera
    camera_index = test_camera()
    if camera_index is None:
        print("\nCamera setup failed. Exiting.")
        return

    # Step 2: Calibration
    homography = calibrate_board(camera_index)

    # Step 3: Backend
    if not start_backend():
        print("\nBackend failed to start. Exiting.")
        return

    # Step 4: Frontend
    start_frontend()
    wait_for_enter("Press ENTER when frontend is open in browser...")

    # Step 5: Projector calibration
    calibrate_projector()

    # Step 6: Perception
    run_perception()

    print("\n" + "="*60)
    print("SETUP COMPLETE!")
    print("="*60)
    print("""
Your FLOODSHIFT demo is ready!

URLS:
  Operator: http://localhost:5173/
  Projector: http://localhost:5173/projector
  API: http://localhost:8000/health

KEYBOARD SHORTCUTS (Operator view):
  1-6 = Place tokens
  G = Get suggestion
  Shift+R = Reset

Enjoy your demo!
""")

if __name__ == "__main__":
    main()
