"""End-to-end simulation flow against the real WorldService and API (no camera, keys or projector).

Covers the hardware-independent demo sequence: reset, flood, people, services, blocked
routes, suggestion, bridge, removal, comparison, plus the game layer built on top.
"""
import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend.world.game import SCORING, evaluate
from backend.world.service import WorldService

ROOT = Path(__file__).resolve().parents[1]
HOT = ROOT / 'scenarios/nepal_rasuwa_hot_v1'
REASONING = ROOT / 'scenarios/nepal_rasuwa_reasoning_v1'
SERVICES = ('hospital', 'medical_site_west'), ('food_shelter', 'food_site_west'), ('shelter', 'shelter_site_west')


class World:
    def __init__(self, bundle=HOT):
        self.service = WorldService.from_bundle(bundle)
        self.sites = {s['id']: s for s in self.service.scenario()['sites']}

    @property
    def snap(self):
        return self.service.snapshot()

    def act(self, kind, **fields):
        version = self.snap['world_version']
        return self.service.apply({'action_id': f'{kind}-{version}', 'type': kind, 'source': 'manual',
                                   'expected_world_version': version, **fields})

    def place(self, token_type, site_id, token_id=None, source='manual'):
        version = self.snap['world_version']
        return self.service.apply({'action_id': f'p-{version}', 'type': 'place_token', 'source': source,
                                   'token_type': token_type, 'site_id': site_id,
                                   'token_id': token_id or f'{token_type}-{site_id}',
                                   'board_uv': self.sites[site_id]['board_uv'], 'expected_world_version': version})

    def staged(self, people=('people_east',)):
        assert self.place('disaster_start', 'start_pad')['accepted']
        for site in people:
            assert self.place('person', site)['accepted']
        for token_type, site in SERVICES:
            assert self.place(token_type, site)['accepted']
        return self


def edge(snapshot, edge_id):
    return next(e for e in snapshot['edges'] if e['id'] == edge_id)


def routes(snapshot):
    return {(r['population_id'], r['service']): r for r in snapshot['service_routes']}


def test_real_backend_initialises_and_production_never_uses_scripted_world(monkeypatch):
    with TestClient(main.app):
        assert isinstance(main.world_service, WorldService)
    assert not (ROOT / 'backend/api/mock_world.py').exists()
    monkeypatch.setenv('FLOODSHIFT_USE_MOCK', 'true')
    with pytest.raises(RuntimeError, match='FLOODSHIFT_USE_MOCK was removed'):
        importlib.reload(main)
    monkeypatch.delenv('FLOODSHIFT_USE_MOCK')
    importlib.reload(main)


def test_backend_fails_loudly_when_world_cannot_initialise(monkeypatch):
    monkeypatch.setattr(main, 'SCENARIO_ID', 'no_such_bundle')
    with pytest.raises(RuntimeError, match='WorldService failed to initialise'):
        with TestClient(main.app):
            pass


def test_actions_modify_authoritative_state_and_flood_stage_recomputes_access():
    world = World()
    assert world.snap['simulation_stage'] == 0 and not any(e['blocked'] for e in world.snap['edges'])
    assert world.place('disaster_start', 'start_pad')['accepted']
    snap = world.snap
    assert snap['world_version'] == 1 and snap['simulation_stage'] == 1
    assert {e['id'] for e in snap['edges'] if e['blocked']} == {
        'crossing_east_road', 'crossing_south_road', 'crossing_west_road'}


def test_blocked_routes_and_unmet_demand_are_computed_not_scripted():
    snap = World().staged().snap
    east = routes(snap)
    assert all(not east[('people_east', s)]['reachable'] for s in ('medical', 'food', 'refuge'))
    assert snap['metrics']['unmet_food_model'] == 8 and snap['metrics']['reachable_communities'] == 0
    # The cut route is drawn on the mapped path it would use, through the closed crossing.
    assert 'crossing_east_road' in east[('people_east', 'food')]['edge_ids']


def test_bridge_restores_only_its_eligible_edge_and_removal_reverses_it():
    world = World().staged()
    before = world.snap
    assert world.place('bridge', 'crossing_east', 'bridge-1')['accepted']
    after = world.snap
    assert not edge(after, 'crossing_east_road')['blocked']
    assert edge(after, 'crossing_south_road')['blocked'] and edge(after, 'crossing_west_road')['blocked']
    assert all(r['reachable'] for r in after['service_routes'])
    assert after['metrics']['unmet_food_model'] < before['metrics']['unmet_food_model']
    assert world.act('remove_token', token_id='bridge-1')['accepted']
    removed = world.snap
    assert edge(removed, 'crossing_east_road')['blocked']
    for key in ('edges', 'service_routes', 'metrics', 'facilities', 'population_demand'):
        assert removed[key] == {**before, 'metrics': {**before['metrics']}}[key], key
    assert removed['game']['score'] == before['game']['score']


def test_bridge_on_an_open_crossing_or_unrelated_crossing_cannot_fake_access():
    world = World().staged()
    assert world.place('bridge', 'crossing_south', 'bridge-s')['accepted']
    snap = world.snap
    # Restored crossing does not lie on the east community's path: it stays unreachable.
    assert not routes(snap)[('people_east', 'food')]['reachable']
    bridge = next(i for i in snap['game']['interventions'] if i['type'] == 'bridge')
    assert bridge['effective'] is False and snap['game']['score_parts']['ineffective_penalty'] < 0


def test_unreachable_paths_stay_unreachable_without_an_open_route():
    world = World()
    assert world.place('disaster_start', 'start_pad')['accepted']
    assert world.place('person', 'people_east')['accepted']
    assert world.place('hospital', 'medical_site_west')['accepted']
    status = world.service.get_route_status('336740.745:3116467.408', world.snap['population_demand'][0]['node_id'])
    assert status['reachable'] is False and status['path'] == []


def test_capacity_constraints_are_respected():
    world = World().staged(people=('people_east', 'people_west'))
    assert world.place('bridge', 'crossing_east')['accepted']
    snap = world.snap
    for facility in snap['facilities']:
        assert 0 <= facility['used_capacity_model'] <= facility['capacity_model']
    hospital = next(f for f in snap['facilities'] if f['type'] == 'hospital')
    assert hospital['used_capacity_model'] == hospital['capacity_model'] == 3
    assert snap['metrics']['unmet_medical_model'] == 4 - 3


def test_route_geometry_follows_the_same_mapped_edges_the_projector_draws():
    world = World().staged()
    assert world.place('bridge', 'crossing_east')['accepted']
    geometry = {r['id']: r['path'] for r in world.service.scenario_geometry()['roads']}
    for route in world.snap['service_routes']:
        assert set(route['edge_ids']) <= set(geometry)
        polyline = [tuple(p) for p in route['board_uv']]
        # Every vertex of every mapped edge is on the drawn line, in order: no shortcuts.
        cursor = 0
        for edge_id in route['edge_ids']:
            path = [tuple(p) for p in geometry[edge_id]]
            forward = path if path[0] == polyline[cursor] else list(reversed(path))
            assert polyline[cursor:cursor + len(forward)] == forward, edge_id
            cursor += len(forward) - 1
        assert cursor == len(polyline) - 1


def test_scoring_is_deterministic_and_cannot_be_farmed():
    first, second = World().staged(), World().staged()
    assert first.snap['game'] == second.snap['game']
    score = first.snap['game']['score']
    for _ in range(3):
        assert first.place('bridge', 'crossing_east', 'b')['accepted']
        assert first.act('remove_token', token_id='b')['accepted']
    assert first.snap['game']['score'] == score
    assert first.place('bridge', 'crossing_east', 'b')['accepted']
    game = first.snap['game']
    assert game['score'] > score and sum(game['score_parts'].values()) == game['score']
    assert game['score_parts']['spend_penalty'] == -SCORING['spend_penalty_per_unit'] * game['budget_spent_model']
    assert 'not a real outcome metric' in game['label']


def test_objectives_complete_only_when_state_supports_them():
    world = World().staged(people=('people_east', 'people_west'))
    objectives = {o['id']: o['complete'] for o in world.snap['game']['objectives']}
    assert not objectives['restore_access'] and not objectives['connect_communities']
    assert world.place('bridge', 'crossing_east')['accepted']
    objectives = {o['id']: o['complete'] for o in world.snap['game']['objectives']}
    assert objectives['restore_access'] and objectives['connect_communities'] and objectives['service_coverage']
    summary = world.snap['game']['summary']
    assert any('Temporary bridge' in line for line in summary['improved'])
    # Two communities need 4 medical units; the hospital pad holds 3: reported, not hidden.
    assert any('medical' in line and 'capacity' in line for line in summary['unresolved'])


def test_reset_restores_the_baseline():
    world = World()
    pristine = world.snap
    world.staged()
    assert world.place('bridge', 'crossing_east')['accepted']
    assert world.act('reset')['accepted']
    snap = world.snap
    for key in ('phase', 'simulation_stage', 'tokens', 'edges', 'metrics', 'token_inventory',
                'budget_remaining_model', 'service_routes', 'game'):
        assert snap[key] == pristine[key], key


def test_branch_comparison_reflects_genuinely_different_states():
    world = World().staged()
    assert world.service.save_branch('A')['accepted']
    assert world.place('bridge', 'crossing_east')['accepted']
    assert world.service.save_branch('B')['accepted']
    comparison = world.service.compare(['A', 'B'])
    a, b = comparison['branches']
    assert a['metrics'] != b['metrics'] and b['game']['score'] > a['game']['score']
    assert 'bridge' in b['placed'] and 'bridge' not in a['placed']
    assert comparison['delta_from_first']['B']['reachable_communities'] == 1


def test_stage_advance_recomputes_reasoning_bundle_and_game_layer_runs_there():
    world = World(REASONING)
    assert world.place('disaster_start', 'start_pad')['accepted']
    stage_one = world.snap
    assert world.act('advance_stage')['accepted']
    assert world.snap['simulation_stage'] == 2 and world.snap['world_version'] == stage_one['world_version'] + 1
    assert world.snap['game']['status'] == 'active'
    assert world.act('advance_stage')['reason'] == 'last_stage'


def test_flood_art_geometry_is_derived_from_scenario_hazard():
    hot = WorldService.from_bundle(HOT).scenario_geometry()
    assert hot['hazard_zones'] == [] and hot['flood_corridors']
    assert {c['stage'] for c in hot['flood_corridors']} == {1}
    assert hot['hazard']['geometry_source'].startswith('illustrative')
    reasoning = WorldService.from_bundle(REASONING).scenario_geometry()
    assert reasoning['hazard_zones'] and reasoning['flood_corridors'] == []
    assert reasoning['hazard']['geometry_source'] == 'scenario_flood_footprints'


def test_ui_receives_recomputed_snapshot_over_websocket(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    with TestClient(main.app) as api:
        monkeypatch.setattr(main, 'world_service', WorldService.from_bundle(HOT))
        with api.websocket_connect('/ws') as ws:
            ws.receive_json()
            assert ws.receive_json()['payload']['world_version'] == 0
            result = api.post('/action', json={
                'action_id': 'ws-start', 'type': 'place_token', 'source': 'physical_local_cv',
                'token_type': 'disaster_start', 'token_id': 'start', 'site_id': 'start_pad',
                'board_uv': [0.92, 0.92], 'expected_world_version': 0}).json()
            assert result['accepted']
            event = ws.receive_json()
            assert event['type'] == 'world.snapshot' and event['payload']['world_version'] == 1
            assert event['payload']['game']['status'] == 'active'
            assert all('board_uv' in r for r in event['payload']['service_routes'])


def test_evaluate_is_pure():
    world = World().staged()
    state = world.service._state
    bundle = world.service.scenario()
    assert evaluate(bundle, state) == evaluate(bundle, state) == world.snap['game']
