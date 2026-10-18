"""Real-data promotion gates, independent of API/UI/camera and GIS installs."""
import json
from math import dist
from pathlib import Path

import pytest

from backend.world import WorldService
from backend.world.demo import place, staged_world
from backend.simulation.routing import route_geometry
from scripts.geodata.build_hot_scenario import build, CONTEXT

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / 'scenarios/nepal_rasuwa_hot_v1'


def test_hot_build_is_reproducible_and_preserves_all_crossing_states(tmp_path):
    audit = build(output=tmp_path)
    proof = audit['topology_validation']
    assert proof['crossing_states_tested'] == 8
    assert proof['terminal_pair_comparisons'] == 440
    assert proof['connectivity_preserved'] and proof['no_added_road_connections']
    for path in tmp_path.glob('*.json'):
        assert path.read_bytes() == (BUNDLE / 'data' / path.name).read_bytes()


def test_hot_crossing_is_matching_source_geometry_and_pads_do_not_overlap():
    world = WorldService.from_bundle(BUNDLE)
    bundle = world.scenario()
    assert bundle['data_mode'] == 'HOT_DERIVED'
    assert bundle['source_manifest']['historical_geometry_used']
    left, top, right, bottom = bundle['board']['control_inset_uv']
    for site in bundle['sites']:
        u, v = site['board_uv']
        inside = left <= u <= right and top <= v <= bottom
        assert inside == (site['id'] == 'start_pad')
    assert all(not (left <= u <= right and top <= v <= bottom)
               for e in bundle['roads']['edges'] for u, v in e['board_uv'])
    features = json.loads((BUNDLE / 'data/bridges_board.json').read_text())['features']
    for site in bundle['sites']:
        assert site['origin'] == 'scenario_synthetic'
        if site['kind'] == 'bridge_crossing':
            source = next(f for f in features if f['properties']['source_id'] == site['source_refs'][0])
            a, b = source['geometry']['coordinates']
            assert dist(site['board_uv'], [(x+y)/2 for x, y in zip(a, b)]) < 1e-7
    for i, a in enumerate(bundle['sites']):
        for b in bundle['sites'][i+1:]:
            assert dist(a['board_uv'], b['board_uv']) > a['tolerance_uv'] + b['tolerance_uv']


def test_every_compacted_segment_retains_source_trace_and_curves():
    bundle = WorldService.from_bundle(BUNDLE).scenario()
    candidate = json.loads((CONTEXT / 'candidate_graph.json').read_text())
    source_edges = {e['id']: e for e in candidate['edges']}
    source_nodes = {n['id']: n['board_uv'] for n in candidate['nodes']}
    for edge in bundle['roads']['edges']:
        segments = [source_edges[id_] for id_ in edge['source_segment_ids']]
        assert len(edge['board_uv']) == len(segments) + 1
        assert edge['length_m'] == pytest.approx(sum(e['length_m'] for e in segments), abs=.001)
        assert edge['source_refs'] == sorted({e['source_id'] for e in segments})
        for i, segment in enumerate(segments):
            expected = {tuple(source_nodes[segment['from']]), tuple(source_nodes[segment['to']])}
            assert {tuple(edge['board_uv'][i]), tuple(edge['board_uv'][i+1])} == expected


@pytest.mark.parametrize('bundle_path', [None, BUNDLE])
def test_both_bundles_pass_six_token_replay_and_capacity_gate(bundle_path):
    world = staged_world(bundle_path)
    before = world.snapshot()
    assert [before['metrics'][f'unmet_{n}_model'] for n in ('food', 'medical', 'refuge')] == [8, 2, 8]
    suggestion = world.suggest()
    assert suggestion['site_id'] == 'crossing_east'
    assert place(world, 'bridge', suggestion['site_id'])['accepted']
    after = world.snapshot()
    assert after['metrics'] == suggestion['projected_metrics']
    assert [after['metrics'][f'unmet_{n}_model'] for n in ('food', 'medical', 'refuge')] == [0, 0, 0]
    assert place(world, 'person', 'people_west', 'person-west')['accepted']
    assert [world.snapshot()['metrics'][f'unmet_{n}_model'] for n in ('food', 'medical', 'refuge')] == [6, 1, 6]
    replay = WorldService.from_bundle(bundle_path) if bundle_path else WorldService()
    for event in world.event_log():
        assert replay.apply(event['action'])['accepted']
    assert replay.snapshot() == world.snapshot()


@pytest.mark.parametrize('site_id', ['crossing_west', 'crossing_south'])
def test_other_hot_bridges_do_not_fabricate_service_access(site_id):
    world = staged_world(BUNDLE)
    candidates = world.get_eligible_interventions()
    candidate = next(c for c in candidates if c['site_id'] == site_id)
    assert candidate['gain_model'] == 0
    assert place(world, 'bridge', site_id)['accepted']
    assert world.snapshot()['metrics']['unmet_food_model'] == 8


def test_hot_route_polylines_follow_road_bends_and_reverse_correctly():
    world = staged_world(BUNDLE)
    place(world, 'bridge', 'crossing_east')
    snapshot = world.snapshot()
    nodes = {n['id']: n for n in world.scenario()['roads']['nodes']}
    for route in snapshot['routes']:
        assert len(route['board_uv']) > len(route['path'])
        reversed_geometry = route_geometry(snapshot['edges'], list(reversed(route['path'])), nodes)
        assert reversed_geometry == list(reversed(route['board_uv']))
        assert route['board_uv'][0] == nodes[route['path'][0]]['board_uv']
        assert route['board_uv'][-1] == nodes[route['path'][-1]]['board_uv']


def test_hot_fixtures_match_real_reducer():
    service = WorldService.from_bundle(BUNDLE)
    actions = json.loads((BUNDLE / 'data/demo_actions.json').read_text())
    for action in actions[:6]:  # five pieces, then the suggest request
        assert service.apply(action)['accepted']
    assert service.snapshot() == json.loads((BUNDLE / 'data/fixture_world.json').read_text())
    service.apply(actions[6])
    assert service.snapshot() == json.loads((BUNDLE / 'data/fixture_after_bridge.json').read_text())


def test_bridge_geometry_mismatch_prevents_promotion(tmp_path):
    context = tmp_path / 'context'
    context.mkdir()
    for path in CONTEXT.glob('*.json'):
        (context / path.name).write_bytes(path.read_bytes())
    path = context / 'bridges_board.json'
    value = json.loads(path.read_text())
    for feature in value['features']:
        if feature['properties']['id'] == 'way/83925870':
            feature['geometry']['coordinates'][0][0] += .1
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='Bridge geometry'):
        build(context, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()
