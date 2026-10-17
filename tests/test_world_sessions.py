import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from backend.world import WorldService
from backend.world.demo import place
from backend.world.session_store import SessionError, SessionStore

HOT = Path(__file__).resolve().parents[1] / 'scenarios/nepal_rasuwa_hot_v1'


def control(world, kind, **fields):
    return world.apply({'action_id': f'{kind}-{world.snapshot()["world_version"]}',
        'type': kind, 'source': 'manual', 'expected_world_version': world.snapshot()['world_version'], **fields})


def prepare(world):
    for kind, site in [('disaster_start', 'start_pad'), ('person', 'people_east'),
                       ('hospital', 'medical_site_west'), ('food_shelter', 'food_site_west'),
                       ('shelter', 'shelter_site_west')]:
        assert place(world, kind, site)['accepted']


@pytest.mark.parametrize('bundle', [None, HOT])
def test_restart_recovers_branches_history_budget_and_duplicate_protection(tmp_path, bundle):
    path = tmp_path / 'session.sqlite3'
    world = WorldService.open_session(path, bundle)
    prepare(world)
    baseline = world.snapshot()['snapshot_id']
    assert control(world, 'branch', branch_id='plan-a')['accepted']
    assert place(world, 'bridge', 'crossing_east')['accepted']
    expected = world.snapshot()
    comparison = world.compare(['main', 'plan-a'])
    restored = WorldService.open_session(path, bundle)
    assert restored.snapshot() == expected
    assert restored.compare(['main', 'plan-a']) == comparison
    assert restored.event_log() == world.event_log()
    assert restored.apply(world.event_log()[-1]['action'])['reason'] == 'duplicate'
    assert control(restored, 'branch', branch_id='plan-b', from_snapshot_id=baseline)['accepted']
    assert restored.snapshot()['token_inventory']['bridge'] == 1
    assert restored.compare(['main', 'plan-a']) == comparison


def test_reset_and_latched_start_survive_restart(tmp_path):
    path = tmp_path / 'session.sqlite3'
    world = WorldService.open_session(path)
    prepare(world)
    old = world.event_log()[0]['action']
    assert control(world, 'reset')['accepted']
    restored = WorldService.open_session(path)
    assert restored.snapshot()['phase'] == 'ready'
    assert restored.snapshot()['world_version'] == 6
    assert restored.apply(old)['reason'] == 'duplicate'
    assert place(restored, 'disaster_start', 'start_pad')['accepted']
    latest = WorldService.open_session(path)
    assert place(latest, 'disaster_start', 'start_pad', 'new-start')['reason'] == 'already_started'


def test_write_failure_never_acknowledges_or_mutates(tmp_path, monkeypatch):
    path = tmp_path / 'session.sqlite3'
    world = WorldService.open_session(path)
    before = world.snapshot()
    def fail(*args):
        raise SessionError('simulated_disk_full')
    monkeypatch.setattr(world._store, 'save', fail)
    result = place(world, 'disaster_start', 'start_pad')
    assert not result['accepted'] and result['reason'] == 'persistence_unavailable'
    assert world.snapshot() == before and world.event_log() == []
    assert WorldService.open_session(path).snapshot() == before


def test_second_writer_cannot_overwrite_newer_session(tmp_path):
    path = tmp_path / 'session.sqlite3'
    first = WorldService.open_session(path)
    stale = WorldService.open_session(path)
    assert place(first, 'disaster_start', 'start_pad')['accepted']
    assert place(stale, 'disaster_start', 'start_pad')['reason'] == 'session_conflict'
    assert stale.snapshot()['phase'] == 'ready'
    assert WorldService.open_session(path).snapshot() == first.snapshot()


def test_rejected_action_does_not_write_checkpoint(tmp_path):
    path = tmp_path / 'session.sqlite3'
    world = WorldService.open_session(path)
    store = SessionStore(path)
    initial = store.read()
    revision = store.revision
    assert place(world, 'person', 'people_east')['reason'] == 'start_first'
    assert store.read() == initial and store.revision == revision


def test_corrupt_checkpoint_and_wrong_bundle_never_reset(tmp_path):
    path = tmp_path / 'session.sqlite3'
    world = WorldService.open_session(path)
    prepare(world)
    with pytest.raises(SessionError, match='mismatch'):
        WorldService.open_session(path, HOT)
    assert WorldService.open_session(path).snapshot() == world.snapshot()
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE world_session SET payload='{}'")
    with pytest.raises(SessionError, match='checksum'):
        WorldService.open_session(path)


def test_replay_mismatch_rejects_even_a_valid_json_checkpoint(tmp_path):
    path = tmp_path / 'session.sqlite3'
    world = WorldService.open_session(path)
    prepare(world)
    store = SessionStore(path)
    payload = store.read()
    payload['snapshot']['metrics']['unmet_food_model'] = 999
    store.save(payload)
    with pytest.raises(SessionError, match='replay_mismatch'):
        WorldService.open_session(path)


def test_non_database_file_preserved(tmp_path):
    path = tmp_path / 'broken.sqlite3'
    path.write_bytes(b'not a database')
    with pytest.raises(SessionError):
        WorldService.open_session(path)
    assert path.read_bytes() == b'not a database'


def test_returned_action_snapshot_cannot_mutate_bundle_or_saved_state(tmp_path):
    path = tmp_path / 'session.sqlite3'
    world = WorldService.open_session(path)
    result = place(world, 'disaster_start', 'start_pad')
    expected = world.snapshot()
    result['snapshot']['edges'][0]['board_uv'][0][0] = 999
    result['snapshot']['metrics']['blocked_roads'] = 999
    assert world.snapshot() == expected
    assert WorldService.open_session(path).snapshot() == expected


def test_frozen_view_stays_consistent_and_never_writes(tmp_path):
    path = tmp_path / 'session.sqlite3'
    world = WorldService.open_session(path)
    prepare(world)
    frozen = world.frozen_copy()
    before = frozen.snapshot()
    place(world, 'bridge', 'crossing_east')
    assert frozen.snapshot() == before
    assert frozen._store is None
    control(frozen, 'reset')
    assert world.snapshot()['world_version'] == 6
    assert WorldService.open_session(path).snapshot() == world.snapshot()


def test_sqlite_transaction_rolls_back_when_commit_fails(tmp_path, monkeypatch):
    import backend.world.session_store as module
    path = tmp_path / 'session.sqlite3'
    world = WorldService.open_session(path)
    before = world.snapshot()
    real_connect = sqlite3.connect
    class FailedCommit:
        def __init__(self, *args, **kwargs):
            self.connection = real_connect(*args, **kwargs)
        def execute(self, *args, **kwargs):
            return self.connection.execute(*args, **kwargs)
        def commit(self):
            raise sqlite3.OperationalError('simulated I/O failure')
        def close(self):
            self.connection.close()
    with monkeypatch.context() as patch:
        patch.setattr(module.sqlite3, 'connect', FailedCommit)
        result = place(world, 'disaster_start', 'start_pad')
    assert result['reason'] == 'persistence_unavailable'
    assert world.snapshot() == before
    assert WorldService.open_session(path).snapshot() == before


def test_demo_recovers_in_a_different_process(tmp_path):
    command = [sys.executable, '-m', 'backend.world.session_demo', '--session', str(tmp_path / 'demo.sqlite3')]
    root = Path(__file__).resolve().parents[1]
    first = json.loads(subprocess.check_output(command, cwd=root, text=True))
    second = json.loads(subprocess.check_output(command, cwd=root, text=True))
    assert first['recovered'] is False and second['recovered'] is True
    assert first['world_version'] == second['world_version'] == 6
    assert first['metrics'] == second['metrics']
    assert second['metrics']['unmet_food_model'] == 0
