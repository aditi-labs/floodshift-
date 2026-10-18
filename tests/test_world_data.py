import json
import math
from pathlib import Path

from backend.world import WorldService
from backend.world.scenarios import load_bundle, validate_bundle

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'scenarios/nepal_rasuwa_v1/data'


def test_published_fixtures_are_reproducible_from_actions():
    service = WorldService()
    actions = json.loads((DATA / 'demo_actions.json').read_text())
    for action in actions[:6]:  # five pieces, then the suggest request
        assert service.apply(action)['accepted']
    assert service.snapshot() == json.loads((ROOT / 'contracts/fixture_world.json').read_text())
    assert service.apply(actions[6])['accepted']
    assert service.snapshot() == json.loads((DATA / 'fixture_after_bridge.json').read_text())


def test_default_bundle_is_honestly_schematic():
    bundle = load_bundle()
    validate_bundle(bundle)
    assert bundle['data_mode'] == 'SCHEMATIC'
    assert bundle['source_manifest']['historical_geometry_used'] is False
    assert all(s['origin'] == 'scenario_synthetic' for s in bundle['sites'])


def coordinates(value):
    if isinstance(value[0], (int, float)):
        yield value
    else:
        for child in value:
            yield from coordinates(child)


def test_real_context_has_one_board_frame_and_source_identity():
    context = DATA / 'hot_context'
    manifest = json.loads((context / 'source_manifest.json').read_text())
    assert manifest['projected_crs'] == 'EPSG:32645'
    assert manifest['runtime_promoted'] is False
    assert 'ODbL' in manifest['license']
    for layer, audit in manifest['layers'].items():
        data = json.loads((context / (layer + '_board.json')).read_text())
        assert len(data['features']) == audit['clipped_count'] > 0
        for feature in data['features']:
            assert feature['properties']['origin'] == 'mapped_OSM'
            assert feature['properties']['source_id']
            for point in coordinates(feature['geometry']['coordinates']):
                assert all(math.isfinite(v) and -1e-8 <= v <= 1 + 1e-8 for v in point[:2])


def test_candidate_graph_never_claims_validated_routes():
    graph = json.loads((DATA / 'hot_context/candidate_graph.json').read_text())
    assert graph['validated_for_routing'] is False
    nodes = {n['id'] for n in graph['nodes']}
    assert nodes and graph['edges']
    for edge in graph['edges']:
        assert edge['from'] in nodes and edge['to'] in nodes
        assert edge['length_m'] > 0 and edge['source_id']
        assert 'weight_min' not in edge  # no invented real travel-time predictions
