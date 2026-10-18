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


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def synthetic_board(seed=0):
    """A 1280x720 'camera' frame: tilted paper board on noisy carpet, nothing on it."""
    rng = np.random.default_rng(seed)
    carpet = rng.integers(40, 120, (720, 1280, 3), dtype=np.uint8)
    board = cv2.imread(str(FRAMES / 'bridge_camera_1280x720.jpg'))
    board[300:440, 600:690] = board[50:190, 50:140]  # remove the bridge: empty board texture
    quad = np.array([[300, 120], [1000, 140], [980, 620], [280, 600]], dtype=np.float32)
    src = np.array([[0, 0], [1280, 0], [1280, 720], [0, 720]], dtype=np.float32)
    warp = cv2.getPerspectiveTransform(src, quad)
    frame = cv2.warpPerspective(board, warp, (1280, 720), dst=carpet.copy(), borderMode=cv2.BORDER_TRANSPARENT)
    homography = cv2.getPerspectiveTransform(quad, np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32))
    return frame, homography, quad


def carpet_noise(frame, quad, rng):
    """Carpet pixels outside the board change every frame (camera noise, shadows)."""
    out = frame.copy()
    mask = np.zeros((720, 1280), np.uint8)
    cv2.fillConvexPoly(mask, quad.astype(np.int32), 255)
    noise = rng.integers(40, 120, (720, 1280, 3), dtype=np.uint8)
    out[mask == 0] = noise[mask == 0]
    return out


def paste_bridge(frame, x, y):
    piece = cv2.imread(str(FRAMES / 'bridge_camera_1280x720.jpg'))[300:440, 600:690]
    out = frame.copy()
    out[y:y + 140, x:x + 90] = piece
    return out


def test_board_watcher_ignores_everything_outside_the_board_and_sends_the_bridge_once(monkeypatch):
    from backend.perception.board_watcher import BoardWatcher
    monkeypatch.delenv('PERCEPTRON_API_KEY', raising=False)
    rng = np.random.default_rng(1)
    empty, homography, quad = synthetic_board()
    watcher = BoardWatcher(PerceptronAdapter(mock_mode=False), stability_frames=20, clock=FakeClock())
    watcher.set_board(homography, empty.shape)
    watcher.capture_reference([carpet_noise(empty, quad, rng) for _ in range(15)])
    for i in range(40):  # nothing placed; carpet keeps changing; a bridge lies OUTSIDE the board
        assert watcher.observe(paste_bridge(carpet_noise(empty, quad, rng), 40, 500), i) == []
    assert watcher.tracks == {}
    ready = []
    for i in range(40, 70):  # bridge placed inside the board, with carpet noise and +15% exposure
        frame = cv2.convertScaleAbs(paste_bridge(carpet_noise(empty, quad, rng), 600, 330), alpha=1.15)
        ready = watcher.observe(frame, i)
    assert len(watcher.tracks) == 1 and len(ready) == 1
    track = ready[0]
    assert track.token_type == 'bridge' and track.class_source == 'local_cv' and watcher.inside(track.center)
    uv = watcher.board_uv(track.center)
    assert 0.3 < uv[0] < 0.7 and 0.2 < uv[1] < 0.7
    watcher.mark_sent(track.track_id, 'accepted')
    for i in range(70, 100):
        assert watcher.observe(paste_bridge(carpet_noise(empty, quad, rng), 600, 330), i) == []
    # A hand (large blob) over the board is never a candidate.
    hand = paste_bridge(carpet_noise(empty, quad, rng), 600, 330)
    cv2.rectangle(hand, (350, 200), (650, 560), (90, 110, 150), -1)
    for i in range(100, 130):
        watcher.observe(hand, i)
    assert [t.token_type for t in watcher.tracks.values() if not t.sent] == []
    assert watcher.classifier_calls == 0  # local rule; Perceptron never called


def test_board_watcher_queries_perceptron_once_per_piece_and_never_for_noise():
    from backend.perception.board_watcher import BoardWatcher
    from backend.perception.perceptron_adapter import SemanticBox

    class FakePerceptron:
        available = True
        last_latency_ms = 120

        def __init__(self):
            self.calls = 0

        def classify_frame(self, frame):
            self.calls += 1
            return [SemanticBox(mention='miniature hospital with cross', token_type='hospital',
                                x1=760, y1=380, x2=840, y2=460, source='perceptron')]

    rng = np.random.default_rng(2)
    empty, homography, quad = synthetic_board()
    clock = FakeClock()
    fake = FakePerceptron()
    watcher = BoardWatcher(fake, stability_frames=10, clock=clock)
    watcher.set_board(homography, empty.shape)
    watcher.capture_reference([carpet_noise(empty, quad, rng) for _ in range(15)])
    placed = carpet_noise(empty, quad, rng)
    cv2.rectangle(placed, (760, 380), (840, 460), (200, 60, 60), -1)  # an unknown piece
    ready = []
    for i in range(30):
        clock.t += 0.05
        ready = watcher.observe(carpet_noise(placed, quad, rng), i)
    assert fake.calls == 1
    assert len(ready) == 1 and ready[0].token_type == 'hospital' and ready[0].class_source == 'perceptron'
    for i in range(30, 60):  # still there, already classified: no further calls
        clock.t += 0.05
        watcher.observe(carpet_noise(placed, quad, rng), i)
    assert fake.calls == 1
