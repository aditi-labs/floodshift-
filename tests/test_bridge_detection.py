"""The printed bridge: local detector, classifier fallback, and the camera path end to end."""
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend.perception.bridge_detector import PROFILE_PATH, detect_bridges, load_profile
from backend.perception.perceptron_adapter import PerceptronAdapter, PERCEPTRON_CLASSES
from backend.world.service import WorldService
from backend.world.demo import place, staged_world

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / 'tests/fixtures/board_frames'
HOT = ROOT / 'scenarios/nepal_rasuwa_hot_v1'


def camera_frame():
    return cv2.imread(str(FRAMES / 'bridge_camera_1280x720.jpg'))


def test_profile_is_fitted_from_the_committed_photo():
    profile = load_profile()
    assert PROFILE_PATH.is_file() and profile['fitted_on']
    assert 'hardware/tokens/bridge/photo_top.jpg' in profile['fitted_from']


def test_detects_the_piece_in_the_photo_and_at_camera_scale():
    photo = detect_bridges(cv2.imread(str(ROOT / 'hardware/tokens/bridge/photo_top.jpg')))
    assert len(photo) == 1 and photo[0].rung_count >= 4
    cam = detect_bridges(camera_frame())
    assert len(cam) == 1
    assert abs(cam[0].center[0] - 640) < 20 and abs(cam[0].center[1] - 360) < 20
    assert 1.3 <= cam[0].aspect <= 2.9


@pytest.mark.parametrize('angle', [30, 90, 150])
def test_detects_at_any_rotation_and_reports_orientation(angle):
    frame = camera_frame()
    matrix = cv2.getRotationMatrix2D((640, 360), angle, 1.0)
    rotated = cv2.warpAffine(frame, matrix, (1280, 720), borderValue=(180, 180, 180))
    hits = detect_bridges(rotated)
    assert len(hits) == 1
    assert abs(((hits[0].rotation_deg + angle) % 180 + 90) % 180 - 90) < 8  # orientation tracks the piece


def test_half_size_piece_still_detected():
    small = cv2.resize(camera_frame(), None, fx=0.5, fy=0.5)
    padded = cv2.copyMakeBorder(small, 180, 180, 320, 320, cv2.BORDER_CONSTANT, value=(180, 180, 180))
    assert len(detect_bridges(padded)) == 1


def test_rejects_blank_frames_yellow_blobs_without_slats_and_other_colours():
    blank = np.full((720, 1280, 3), 180, np.uint8)
    assert detect_bridges(blank) == []
    square = blank.copy()
    cv2.rectangle(square, (600, 300), (700, 420), (0, 220, 230), -1)
    assert detect_bridges(square) == []
    blue = camera_frame()
    hsv = cv2.cvtColor(blue, cv2.COLOR_BGR2HSV)
    hsv[..., 0] = (hsv[..., 0].astype(int) + 90) % 180  # same shape, wrong filament colour
    assert detect_bridges(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)) == []


def test_two_pieces_are_two_detections():
    frame = camera_frame()
    piece = frame[300:440, 600:690].copy()
    frame[100:240, 200:290] = piece
    assert len(detect_bridges(frame)) == 2


def test_adapter_without_key_never_fabricates_and_falls_back_to_local_rule(monkeypatch):
    monkeypatch.delenv('PERCEPTRON_API_KEY', raising=False)
    adapter = PerceptronAdapter(mock_mode=False)
    assert not adapter.available and adapter.unavailable_reason == 'missing_api_key'
    assert adapter.recognize_board('nonexistent.jpg', 1280, 720) == []
    boxes = adapter.classify_frame(camera_frame())
    assert [(b.token_type, b.source) for b in boxes] == [('bridge', 'local_cv')]
    assert adapter.classify_frame(np.full((720, 1280, 3), 180, np.uint8)) == []
    assert PerceptronAdapter(mock_mode=False, local_fallback=False).classify_frame(camera_frame()) == []


def test_mention_mapping_uses_whole_words_and_catalog_prompts():
    adapter = PerceptronAdapter(mock_mode=True)
    assert adapter._mention_to_token_type('small yellow bridge crossing with slats') == 'bridge'
    assert adapter._mention_to_token_type('building with a medical cross') == 'hospital'
    assert adapter._mention_to_token_type('a ladder-like deck') == 'bridge'
    assert adapter._mention_to_token_type('something else') is None
    catalog = json.loads((ROOT / 'contracts/token_catalog.json').read_text())['tokens']
    assert catalog['bridge']['perceptron_hint'] in PERCEPTRON_CLASSES['bridge']
    assert PERCEPTRON_CLASSES['bridge'].startswith('small yellow')


def test_reducer_resolves_pad_from_board_uv_for_camera_placements():
    world = staged_world(HOT)
    pad = next(s for s in world.scenario()['sites'] if s['id'] == 'crossing_east')
    off = [pad['board_uv'][0] + 0.015, pad['board_uv'][1] - 0.01]  # inside 0.025 tolerance
    result = world.apply({'action_id': 'cam-1', 'type': 'place_token', 'source': 'physical_local_cv',
                          'token_id': 'tracked-7', 'token_type': 'bridge', 'board_uv': off,
                          'expected_world_version': world.snapshot()['world_version']})
    assert result['accepted'], result['reason']
    token = next(t for t in result['snapshot']['tokens'] if t['id'] == 'tracked-7')
    assert token['site_id'] == 'crossing_east' and token['vision_source'] == 'local_cv'
    assert result['snapshot']['metrics']['unmet_food_model'] == 0
    far = world.apply({'action_id': 'cam-2', 'type': 'place_token', 'source': 'physical_perceptron',
                       'token_id': 'tracked-8', 'token_type': 'hospital', 'board_uv': [0.7, 0.9],
                       'expected_world_version': world.snapshot()['world_version']})
    assert far['reason'] == 'outside_site'


@pytest.fixture
def api(monkeypatch):
    with TestClient(main.app) as client:
        monkeypatch.setattr(main, 'world_service', WorldService.from_bundle(HOT))
        yield client


def test_observe_endpoint_runs_the_whole_camera_path(api):
    world = main.world_service
    for kind, site in [('disaster_start', 'start_pad'), ('person', 'people_east'),
                       ('hospital', 'medical_site_west'), ('food_shelter', 'food_site_west'),
                       ('shelter', 'shelter_site_west')]:
        assert place(world, kind, site)['accepted']
    frame = camera_frame()
    detection = PerceptronAdapter(mock_mode=False).classify_frame(frame)[0]
    pad = next(s for s in world.scenario()['sites'] if s['id'] == 'crossing_east')
    observation = {
        'event_type': 'object_observed', 'event_id': 'live-1-1', 'frame_id': 1,
        'token_id': 'tracked-1', 'object_type': detection.token_type, 'class_source': detection.source,
        'board_uv': pad['board_uv'], 'rotation_deg': detection.rotation_deg, 'stable_ms': 700,
        'vision_status': 'confirmed', 'frame_provenance': 'local:tests/fixtures/board_frames/bridge_camera_1280x720.jpg',
        'latency_ms': 6}
    with api.websocket_connect('/ws') as ws:
        ws.receive_json(); ws.receive_json()
        result = api.post('/perception/observe', json=observation).json()
        vision = ws.receive_json()
        snapshot = ws.receive_json()['payload']
    assert result['accepted'] and result['site_id'] == 'crossing_east' and result['applied']
    assert vision['type'] == 'vision.status' and vision['payload']['observations'][0]['class_source'] == 'local_cv'
    token = next(t for t in snapshot['tokens'] if t['id'] == 'tracked-1')
    assert token['vision_source'] == 'local_cv' and snapshot['metrics']['unmet_refuge_model'] == 0
    assert all(r['reachable'] for r in snapshot['service_routes'])
    # Same piece seen again a few frames later: no second deployment.
    again = api.post('/perception/observe', json={**observation, 'event_id': 'live-1-9', 'frame_id': 9}).json()
    assert not again['accepted'] and again['rejection_reason'] == 'token_already_placed'
    pending = api.post('/perception/observe', json={**observation, 'event_id': 'p', 'token_id': 'tracked-2',
                                                     'vision_status': 'pending'}).json()
    assert not pending['applied'] and pending['rejection_reason'] == 'vision_pending'


def test_live_runner_tracker_keeps_a_motionless_piece_until_it_is_stable(monkeypatch):
    """Regression: MOG2's automatic rate dropped a still piece after ~12 frames early in a run."""
    import sys
    monkeypatch.setattr(sys, 'argv', ['x'])
    import scripts.run_live_demo as live
    frame = camera_frame()
    empty = frame.copy()
    empty[300:440, 600:690] = frame[50:190, 50:140]
    tracker = live.SimpleTracker()
    for _ in range(40):
        tracker.update(empty)
    stable = []
    for _ in range(live.STABILITY_FRAMES + 5):
        stable = tracker.update(frame)
    assert len(stable) == 1
    (oid, obj), = stable
    assert abs(obj['center'][0] - 644) < 15 and abs(obj['center'][1] - 373) < 15
    for _ in range(live.MISSING_FRAMES_GRACE):
        tracker.update(empty)  # hand covers the piece briefly
    assert oid in tracker.tracked_objects
    for _ in range(live.MISSING_FRAMES_GRACE + 1):
        tracker.update(empty)  # piece really removed
    assert oid not in tracker.tracked_objects
    detection = live.classify_frame(frame)[0]
    assert detection['token_type'] == 'bridge' and detection['class_source'] == 'local_cv'
