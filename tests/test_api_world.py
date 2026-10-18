"""API gateway against P4's real WorldService (the rest of test_api.py uses the mock)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend.world.service import WorldService

HOT = Path(__file__).resolve().parents[1] / 'scenarios/nepal_rasuwa_hot_v1'


@pytest.fixture
def api(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    with TestClient(main.app) as client:
        monkeypatch.setattr(main, 'world_service', WorldService.from_bundle(HOT))
        yield client


def place(api, token_type, site_id, token_id=None):
    sites = {s['id']: s for s in api.get('/scenario').json()['sites']}
    version = api.get('/world').json()['world_version']
    return api.post('/action', json={
        'action_id': f'{token_type}-{site_id}-{version}', 'type': 'place_token', 'source': 'manual',
        'token_type': token_type, 'site_id': site_id, 'token_id': token_id or f'manual-{token_type}-{site_id}',
        'board_uv': sites[site_id]['board_uv'], 'expected_world_version': version}).json()


def stage(api):
    for kind, site in [('disaster_start', 'start_pad'), ('person', 'people_east'),
                       ('hospital', 'medical_site_west'), ('food_shelter', 'food_site_west'),
                       ('shelter', 'shelter_site_west')]:
        assert place(api, kind, site)['accepted'], kind


def test_scenario_geometry_ids_match_world_edges(api):
    geometry = api.get('/scenario').json()
    world = api.get('/world').json()
    assert geometry['scenario_id'] == world['scenario_id'] == 'nepal_rasuwa_hot_v1'
    assert {r['id'] for r in geometry['roads']} == {e['id'] for e in world['edges']}
    assert geometry['data_label'] == world['data_mode'] == 'HOT_DERIVED'


def test_full_demo_through_the_gateway_keeps_every_computed_field(api):
    stage(api)
    world = api.get('/world').json()
    assert {f['site_id'] for f in world['facilities']} == {'medical_site_west', 'food_site_west', 'shelter_site_west'}
    assert world['population_demand'][0]['unmet_food'] == 8
    assert world['service_routes'] and not any(r['reachable'] for r in world['service_routes'])
    assert world['ghost_suggestion'] is None and world['narration_event']['event_type'] == 'shelter_placed'
    # Measured prevention zones (WorldPop/Copernicus) sit on this map's own nodes.
    node_ids = {n['id'] for n in main.world_service.scenario()['roads']['nodes']}
    assert world['risk_zones'] and {z['node_id'] for z in world['risk_zones']} <= node_ids

    assert api.post('/plan/suggest', json={'goal_id': 'people_east'}).status_code == 400
    suggestion = api.post('/plan/suggest', json={'goal_id': 'needs_served'}).json()
    assert suggestion['has_suggestion'] and suggestion['suggestion']['site_id'] == 'crossing_east'
    ghost = api.get('/world').json()['ghost_suggestion']
    assert ghost['site_id'] == 'crossing_east' and 'crossing_east_road' in ghost['preview_edge_ids']

    assert place(api, 'bridge', 'crossing_east')['accepted']
    world = api.get('/world').json()
    assert world['ghost_suggestion'] is None
    assert [world['metrics'][f'unmet_{n}_model'] for n in ('food', 'medical', 'refuge')] == [0, 0, 0]
    assert all(r['reachable'] for r in world['service_routes'])


def test_rejections_carry_reducer_reasons(api):
    stage(api)
    sites = {s['id']: s for s in api.get('/scenario').json()['sites']}
    version = api.get('/world').json()['world_version']
    result = api.post('/action', json={'action_id': 'far', 'type': 'place_token', 'source': 'manual',
        'token_type': 'bridge', 'token_id': 'b', 'site_id': 'crossing_east',
        'board_uv': [sites['crossing_east']['board_uv'][0] + 0.2, 0.1], 'expected_world_version': version}).json()
    assert result == {'accepted': False, 'action_id': 'far', 'world_version': version, 'rejection_reason': 'outside_site'}


def test_branch_endpoints_save_load_and_compare(api):
    stage(api)
    assert api.post('/branch/save', json={'name': 'baseline'}).json()['branch_id'] == 'baseline'
    assert place(api, 'bridge', 'crossing_east')['accepted']
    api.post('/branch/save', json={'name': 'A'})
    loaded = api.post('/branch/load', json={'branch_id': 'baseline'}).json()
    assert loaded['branch_id'] == 'baseline' and loaded['metrics']['unmet_food_model'] == 8
    assert place(api, 'bridge', 'crossing_west')['accepted']
    api.post('/branch/save', json={'name': 'B'})
    comparison = api.get('/branch/compare', params={'a': 'A', 'b': 'B'}).json()
    assert [b['id'] for b in comparison['branches']] == ['A', 'B']
    assert comparison['branches'][0]['unmet_food_model'] == 0 and comparison['branches'][1]['unmet_food_model'] == 8
    assert comparison['baseline_snapshot_id'] == 'baseline'
    assert api.post('/branch/load', json={'branch_id': 'nope'}).status_code == 404
    assert api.get('/branch/compare', params={'a': 'A', 'b': 'nope'}).status_code == 404


def test_narrate_is_grounded_and_labels_fallback_as_text(api):
    stage(api)
    world = api.get('/world').json()
    answer = api.post('/narrate', json={'question': 'Where should we put the bridge?'}).json()
    assert answer['mode'] == 'TEXT' and answer['reason'] == 'missing_api_key'
    assert answer['grounded_in_version'] == world['world_version']
    assert 'crossing_east' in answer['answer'] and '1,191' not in answer['answer']
    assert api.get('/world').json() == world  # narration never mutates


def test_websocket_broadcasts_suggestion_and_reset(api):
    stage(api)
    with api.websocket_connect('/ws') as ws:
        assert ws.receive_json()['type'] == 'server.hello'
        assert ws.receive_json()['payload']['ghost_suggestion'] is None
        api.post('/plan/suggest', json={})
        assert ws.receive_json()['payload']['ghost_suggestion']['site_id'] == 'crossing_east'
        assert api.post('/reset').json()['reset'] is True
        snapshot = ws.receive_json()['payload']
        assert snapshot['phase'] == 'ready' and snapshot['tokens'] == []


def test_prevention_uses_measured_data_for_the_real_map(api):
    risk = api.get('/prevention/risk-map').json()
    assert risk['available'] and risk['provenance']['data_mode'] == 'MEASURED_OPEN_DATA'
    assert {source['id'] for source in risk['provenance']['data_sources']} >= {'copernicus_glo30', 'worldpop_2020_constrained'}
    assert set(risk['scenarios']) == {'rp10', 'rp100'}
    sites = {s['id'] for s in main.world_service.scenario()['sites']}
    suggestion = api.get('/prevention/suggestions').json()['suggestion']
    assert suggestion['site_id'] in sites
    comparison = api.post('/prevention/compare').json()
    assert comparison['ai_analysis']['mode'] == 'TEXT' and comparison['ai_analysis']['model_only']


def test_prevention_refuses_a_bundle_without_matching_terrain(api, monkeypatch, tmp_path):
    from backend.planning import prevention
    bundle = main.world_service.scenario()
    bundle['scenario_id'] = 'no_such_bundle'
    monkeypatch.setattr(main.world_service, 'scenario', lambda: bundle)
    assert prevention.supports_bundle(bundle) is False
    assert api.get('/prevention/risk-map').json()['available'] is False
    assert api.get('/prevention/suggestions').status_code == 409
