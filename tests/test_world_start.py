from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.world import WorldService
from backend.world.demo import place, staged_world


def control(service, kind, **kwargs):
    return service.apply({'action_id': f'{kind}-{service.snapshot()["world_version"]}',
                          'type': kind, 'source': 'manual',
                          'expected_world_version': service.snapshot()['world_version'], **kwargs})


def test_start_once_and_no_duplicate_spending():
    service = WorldService()
    assert place(service, 'person', 'people_east')['reason'] == 'start_first'
    assert place(service, 'disaster_start', 'start_pad')['accepted']
    baseline = service.snapshot()
    action = service.event_log()[0]['action']
    assert service.apply(action)['reason'] == 'duplicate'
    assert place(service, 'disaster_start', 'start_pad', 'second-start')['reason'] == 'already_started'
    assert control(service, 'remove_token', token_id='disaster_start')['reason'] == 'start_is_latched'
    assert service.snapshot() == baseline


@pytest.mark.parametrize('changes,reason', [
    ({'expected_world_version': 99}, 'stale_version'),
    ({'board_uv': [float('nan'), .5]}, 'invalid_board_uv'),
    ({'board_uv': [1.1, .5]}, 'invalid_board_uv'),
    ({'board_uv': [True, .5]}, 'invalid_board_uv'),
    ({'board_uv': [0, 0]}, 'outside_site'),
    ({'site_id': 'unknown'}, 'invalid_site'),
    ({'source': 'unconfirmed_camera'}, 'invalid_source'),
    ({'token_type': 'helicopter'}, 'unsupported_token'),
])
def test_bad_input_is_atomic(changes, reason):
    service = staged_world()
    baseline = service.snapshot()
    assert place(service, 'bridge', 'crossing_east', **changes)['reason'] == reason
    assert service.snapshot() == baseline


def test_reset_monotonic_version_and_old_action_cannot_replay():
    service = staged_world()
    old = service.event_log()[0]['action']
    assert control(service, 'reset')['accepted']
    snapshot = service.snapshot()
    assert snapshot['world_version'] == 6
    assert snapshot['phase'] == 'ready' and snapshot['tokens'] == []
    assert snapshot['token_inventory'] == WorldService().snapshot()['token_inventory']
    assert service.apply(old)['reason'] == 'duplicate'


def test_concurrent_duplicate_spends_once():
    service = staged_world()
    action = {'action_id': 'same', 'type': 'place_token', 'token_type': 'bridge',
              'site_id': 'crossing_east', 'board_uv': [.475, .5], 'source': 'manual',
              'expected_world_version': 5}
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(service.apply, [action] * 8))
    assert sum(r['accepted'] for r in results) == 1
    assert service.snapshot()['world_version'] == 6
    assert service.snapshot()['budget_remaining_model'] == 0


def test_event_replay_is_deterministic_and_copies_are_detached():
    service = staged_world()
    place(service, 'bridge', 'crossing_east')
    replay = WorldService()
    for event in service.event_log():
        assert replay.apply(event['action'])['accepted']
    assert replay.snapshot() == service.snapshot()
    exposed = service.snapshot()
    exposed['tokens'].clear()
    service.scenario()['sites'].clear()
    service.event_log().clear()
    assert len(service.snapshot()['tokens']) == 6
    assert len(service.event_log()) == 6
