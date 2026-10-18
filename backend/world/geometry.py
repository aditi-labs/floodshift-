"""Static board geometry for the UI (GET /scenario); no world state, no network.

Shape mirrors frontend/src/types/scenario.ts. Road ids equal WorldSnapshot edge ids.
"""
import json
from pathlib import Path

KIND_LABELS = {'control_start_pad': 'START', 'population_node': 'People',
               'medical_site': 'Hospital', 'food_site': 'Food & Water',
               'shelter_site': 'Shelter', 'bridge_crossing': 'Bridge'}
SUFFIXES = ('east', 'west', 'north', 'south', 'southwest', 'junction', 'depot', 'exposed')


def site_label(site):
    base = KIND_LABELS.get(site['kind'], site['kind'])
    suffix = site['id'].rsplit('_', 1)[-1]
    return f'{base} {suffix}' if suffix in SUFFIXES else base


def _read_layer(data_dirs, name):
    for directory in data_dirs:
        path = directory / name
        if path.is_file():
            return json.loads(path.read_text())['features']
    return []


def _lines(geometry):
    if geometry['type'] == 'LineString':
        return [geometry['coordinates']]
    if geometry['type'] == 'MultiLineString':
        return list(geometry['coordinates'])
    return []


def _rings(geometry):
    if geometry['type'] == 'Polygon':
        return [geometry['coordinates'][0]]
    if geometry['type'] == 'MultiPolygon':
        return [polygon[0] for polygon in geometry['coordinates']]
    return []


def scenario_geometry(bundle, data_dir=None):
    data_dirs = []
    if data_dir is not None:
        data_dirs.append(Path(data_dir))
        # Derived bundles (reasoning) reuse their source bundle's mapped context layers.
        source = bundle.get('source_manifest', {}).get('reasoning_extension', {}).get('source_bundle')
        if source:
            data_dirs.append(Path(data_dir).parents[1] / source / 'data')
    nodes = {n['id']: n['board_uv'] for n in bundle['roads']['nodes']}
    crossing_edges = {s['edge_id'] for s in bundle['sites'] if s['kind'] == 'bridge_crossing'}
    roads = [{'id': e['id'], 'from': e['from'], 'to': e['to'],
              'kind': 'crossing' if e['id'] in crossing_edges else 'road',
              'path': e.get('board_uv') or [nodes[e['from']], nodes[e['to']]]}
             for e in bundle['roads']['edges']]
    sites = [{'id': s['id'], 'kind': s['kind'], 'label': site_label(s), 'board_uv': s['board_uv'],
              'tolerance_uv': s['tolerance_uv'], **({'rotation_deg': s['rotation_deg']} if 'rotation_deg' in s else {})}
             for s in bundle['sites']]
    rivers = [line for f in _read_layer(data_dirs, 'waterways_board.json') for line in _lines(f['geometry'])]
    labels = [{'text': f['properties']['name_en'], 'board_uv': f['geometry']['coordinates']}
              for f in _read_layer(data_dirs, 'settlements_board.json')
              if f['geometry']['type'] == 'Point' and f['properties'].get('name_en')]
    hazard_zones = [{'id': f"footprint-{f['stage']}-{i}", 'stage': f['stage'], 'polygon': ring}
                    for f in bundle['hazard'].get('footprints', []) for i, ring in enumerate(_rings(f['geometry']))]
    board = bundle.get('board', {})
    return {'scenario_id': bundle['scenario_id'], 'name': bundle.get('name', bundle['scenario_id']),
            'data_label': bundle['data_mode'], 'board': board,
            'aspect_ratio': board.get('width_mm', 1) / board.get('height_mm', 1),
            'rivers': rivers, 'hazard_zones': hazard_zones, 'roads': roads, 'sites': sites,
            'labels': labels, 'provenance_label': bundle['provenance_label']}
