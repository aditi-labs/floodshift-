"""Offline scenario loader. No camera, network, API keys or server imports."""
import json
import math
from pathlib import Path

DEFAULT_BUNDLE = Path(__file__).resolve().parents[2] / 'scenarios' / 'nepal_rasuwa_v1'


class BundleLoadError(Exception):
    """Error loading scenario bundle."""
    pass


def load_bundle(path=None):
    root = Path(path) if path else DEFAULT_BUNDLE
    if not root.exists():
        raise BundleLoadError(f"Scenario directory not found: {root}")

    data = root / 'data' if (root / 'data').is_dir() else root

    # Load main scenario file
    scenario_file = data / 'scenario.json'
    if not scenario_file.exists():
        raise BundleLoadError(f"scenario.json not found in {data}")

    try:
        bundle = json.loads(scenario_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise BundleLoadError(f"Invalid JSON in scenario.json: {e}")

    # Load required component files
    for key in ('roads', 'sites', 'hazard', 'source_manifest'):
        component_file = data / (key + '.json')
        if not component_file.exists():
            raise BundleLoadError(f"{key}.json not found in {data}")
        try:
            bundle[key] = json.loads(component_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise BundleLoadError(f"Invalid JSON in {key}.json: {e}")

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
    if 'routing_policy' in bundle:
        policy = bundle['routing_policy']
        assert set(policy['edge_capacity_model']) == edge_ids, 'missing edge capacity'
        assert set(policy['node_capacity_model']) == node_ids, 'missing node capacity'
        assert all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1000 for capacities in
                   (policy['edge_capacity_model'], policy['node_capacity_model']) for v in capacities.values())
        assert type(policy['paths_per_shelter']) is int and 1 <= policy['paths_per_shelter'] <= 32
        assert 0 < policy['snap_tolerance_uv'] <= .05
        assert 0 < policy['snapped_node_capacity_groups'] <= 1000
        assert set(policy['shelter_capacity_groups']) == {s['id'] for s in bundle['sites'] if s['kind'] == 'shelter_site'}
        assert all(type(v) in (int,float) and math.isfinite(v) and v >= 0 for v in policy['shelter_capacity_groups'].values())
        assert 1 <= bundle['token_inventory']['person'] <= 6, 'bounded group search'
        assert sum(s['kind'] == 'shelter_site' for s in bundle['sites']) <= 2, 'bounded shelter search'
        assert isinstance(policy['assumptions'], list) and policy['assumptions']
