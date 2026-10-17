"""Offline scenario loader. No camera, network, API keys or server imports."""
import json
import math
from pathlib import Path

DEFAULT_BUNDLE = Path(__file__).resolve().parents[2] / 'scenarios' / 'nepal_rasuwa_v1'


def load_bundle(path=None):
    root = Path(path) if path else DEFAULT_BUNDLE
    data = root / 'data' if (root / 'data').is_dir() else root
    bundle = json.loads((data / 'scenario.json').read_text())
    for key in ('roads', 'sites', 'hazard', 'source_manifest'):
        bundle[key] = json.loads((data / (key + '.json')).read_text())
    validate_bundle(bundle)
    return bundle


def valid_uv(value):
    return isinstance(value, (list, tuple)) and len(value) == 2 and all(
        type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in value)


def validate_bundle(bundle):
    nodes = bundle['roads']['nodes']
    node_ids = {n['id'] for n in nodes}
    edges = bundle['roads']['edges']
    edge_ids = {e['id'] for e in edges}
    assert len(node_ids) == len(nodes), 'duplicate node'
    assert len(edge_ids) == len(edges), 'duplicate edge'
    assert bundle['depot_node'] in node_ids
    assert all(valid_uv(n['board_uv']) for n in nodes)
    assert all(e['from'] in node_ids and e['to'] in node_ids and
               math.isfinite(e['weight_min']) and e['weight_min'] > 0 for e in edges)
    assert len({s['id'] for s in bundle['sites']}) == len(bundle['sites'])
    for site in bundle['sites']:
        assert valid_uv(site['board_uv']) and 0 < site['tolerance_uv'] <= 1
        assert site['node_id'] in node_ids
        assert site['resource_cost'] >= 0
        if site['kind'] == 'bridge_crossing':
            assert site['edge_id'] in edge_ids
        if 'capacity_model' in site:
            assert site['capacity_model'] >= 0
        if 'demand' in site:
            assert all(type(v) is int and v >= 0 for v in site['demand'].values())
    assert bundle['hazard']['stages'][0] == []
    assert all(set(stage) <= edge_ids for stage in bundle['hazard']['stages'])
