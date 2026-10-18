"""World outputs the UI renders: ghost on request, saved branches, routes, geometry."""
from pathlib import Path

import pytest

from backend.world import WorldService
from backend.world.demo import place, staged_world

ROOT = Path(__file__).resolve().parents[1]
HOT = ROOT / 'scenarios/nepal_rasuwa_hot_v1'
BUNDLES = [ROOT / 'scenarios/nepal_rasuwa_v1', HOT, ROOT / 'scenarios/nepal_rasuwa_reasoning_v1']


def test_ghost_appears_only_when_requested_and_clears_after_bridge_or_reset():
    world = staged_world(HOT)
    assert world.snapshot()['ghost_suggestion'] is None
    version = world.snapshot()['world_version']
    result = world.request_suggestion()
    assert result['accepted'] and result['world_version'] == version + 1
    ghost = world.snapshot()['ghost_suggestion']
    assert ghost['site_id'] == 'crossing_east' and ghost == result['suggestion']
    assert world.snapshot()['narration_event']['event_type'] == 'bridge_suggested'
    assert place(world, 'bridge', 'crossing_east')['accepted']
    assert world.snapshot()['ghost_suggestion'] is None
    assert world.request_suggestion()['reason'] == 'no_suggestion'
    world = staged_world(HOT)
    world.request_suggestion()
    world.apply({'action_id': 'reset', 'type': 'reset', 'source': 'manual',
                 'expected_world_version': world.snapshot()['world_version']})
    assert world.snapshot()['ghost_suggestion'] is None


def test_unknown_goal_is_rejected_without_mutation():
    world = staged_world(HOT)
    before = world.snapshot()
    assert world.request_suggestion('people_east')['reason'] == 'unsupported_goal'
    assert world.snapshot() == before


def test_preview_route_is_a_contiguous_path_through_the_suggested_crossing():
    world = staged_world(HOT)
    ghost = world.request_suggestion()['suggestion']
    edges = {e['id']: e for e in world.scenario()['roads']['edges']}
    ids = ghost['preview_edge_ids']
    assert 'crossing_east_road' in ids
    for a, b in zip(ids, ids[1:]):
        assert {edges[a]['from'], edges[a]['to']} & {edges[b]['from'], edges[b]['to']}


def test_saved_branches_are_immutable_bookmarks_and_compare_from_one_baseline():
    world = staged_world(HOT)
    assert world.save_branch('baseline')['accepted']
    assert place(world, 'bridge', 'crossing_east')['accepted']
    assert world.save_branch('A')['accepted']
    loaded = world.load_branch('baseline')
    assert loaded['accepted'] and loaded['snapshot']['branch_id'] == 'baseline'
    assert loaded['snapshot']['metrics']['unmet_food_model'] == 8
    assert place(world, 'bridge', 'crossing_west')['accepted']
    assert world.save_branch('B')['accepted']
    # Playing on after loading never rewrites the bookmark.
    assert world.load_branch('baseline')['snapshot']['metrics']['unmet_food_model'] == 8
    comparison = world.compare(['A', 'B'])
    a, b = comparison['branches']
    assert a['metrics']['unmet_food_model'] == 0 and b['metrics']['unmet_food_model'] == 8
    assert 'bridge' in a['placed'] and comparison['delta_from_first']['B']['unmet_food_model'] == 8
    assert world.load_branch('missing')['reason'] == 'unknown_branch'
    assert world.save_branch('bad name!')['reason'] == 'invalid_branch_id'


def test_saved_branches_survive_session_restart(tmp_path):
    path = tmp_path / 'session.sqlite3'
    world = WorldService.open_session(path, HOT)
    for kind, site in [('disaster_start', 'start_pad'), ('person', 'people_east')]:
        assert place(world, kind, site)['accepted']
    world.save_branch('baseline')
    world.request_suggestion()
    recovered = WorldService.open_session(path, HOT)
    assert recovered.snapshot() == world.snapshot()
    assert recovered.has_branch('baseline')
    assert recovered.load_branch('baseline')['accepted']


@pytest.mark.parametrize('bundle', BUNDLES[:2])
def test_service_routes_and_per_node_unmet_agree_with_metrics(bundle):
    world = staged_world(bundle)
    assert place(world, 'person', 'people_west', 'person-west')['accepted']
    snapshot = world.snapshot()
    for need in ('food', 'medical', 'refuge'):
        assert sum(p['unmet_' + need] for p in snapshot['population_demand']) == snapshot['metrics'][f'unmet_{need}_model']
    routes = {(r['population_id'], r['service']): r for r in snapshot['service_routes']}
    assert not routes[('people_east', 'food')]['reachable']
    assert routes[('people_west', 'food')]['reachable']
    edge_ids = {e['id'] for e in snapshot['edges']}
    assert all(set(r['edge_ids']) <= edge_ids for r in snapshot['service_routes'])
    assert place(world, 'bridge', 'crossing_east')['accepted']
    assert all(r['reachable'] for r in world.snapshot()['service_routes'])


@pytest.mark.parametrize('bundle', BUNDLES)
def test_scenario_geometry_matches_snapshot_ids(bundle):
    world = WorldService.from_bundle(bundle)
    geometry = world.scenario_geometry()
    assert {r['id'] for r in geometry['roads']} == {e['id'] for e in world.snapshot()['edges']}
    assert {s['id'] for s in geometry['sites']} == {s['id'] for s in world.scenario()['sites']}
    assert all(s['label'] for s in geometry['sites'])
    assert all(len(r['path']) >= 2 for r in geometry['roads'])
    crossings = {r['id'] for r in geometry['roads'] if r['kind'] == 'crossing'}
    assert crossings == {s['edge_id'] for s in world.scenario()['sites'] if s['kind'] == 'bridge_crossing'}
    if world.scenario()['data_mode'] == 'HOT_DERIVED':
        assert geometry['aspect_ratio'] == 1.0 and geometry['rivers'] and geometry['labels']
    else:
        assert geometry['aspect_ratio'] == pytest.approx(420 / 297)
    if 'routing_policy' in world.scenario():
        assert {z['stage'] for z in geometry['hazard_zones']} == {1, 2}
