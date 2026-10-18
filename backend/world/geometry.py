"""Static board geometry for the UI (GET /scenario); no world state, no network.

Shape mirrors frontend/src/types/scenario.ts. Road ids equal WorldSnapshot edge ids.
"""
import json
from math import dist
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
            return json.loads(path.read_text(encoding='utf-8'))['features']
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


# Flood art for bundles without measured footprints: mapped river reaches near the
# scenario's own simulated closures. Illustrative placement, not a flood measurement.
CORRIDOR_RADIUS_UV = 0.2
CORRIDOR_WIDTH_UV = {'river': 0.05, 'stream': 0.026}
CORRIDOR_DERIVATION = ('illustrative: mapped OSM river reaches within '
                       f"{CORRIDOR_RADIUS_UV} board units of the scenario's simulated road closures")


def _runs(line, anchors):
    """Contiguous stretches of ``line`` near any anchor, plus one point either side."""
    inside = [any(dist(p, a) <= CORRIDOR_RADIUS_UV for a in anchors) for p in line]
    runs, run = [], []
    for i, point in enumerate(line):
        if inside[i] or (i and inside[i - 1]) or (i + 1 < len(line) and inside[i + 1]):
            run.append(point)
        elif run:
            runs.append(run)
            run = []
    return runs + [run] if run else runs


def flood_corridors(bundle, waterways):
    """Per stage, the reaches of each mapped waterway that pass near that stage's closures."""
    paths = {e['id']: e.get('board_uv') or [] for e in bundle['roads']['edges']}
    corridors = []
    for stage, blocked in enumerate(bundle['hazard']['stages']):
        anchors = [p for edge_id in blocked for p in paths.get(edge_id, [])]
        for feature in waterways if anchors else []:
            props = feature['properties']
            if props.get('waterway') not in CORRIDOR_WIDTH_UV:
                continue
            for line in _lines(feature['geometry']):
                for run in _runs(line, anchors):
                    if len(run) >= 2:
                        corridors.append({'id': f"corridor-{stage}-{props.get('id', 'w')}-{len(corridors)}",
                                          'stage': stage, 'path': run,
                                          'width_uv': CORRIDOR_WIDTH_UV[props['waterway']],
                                          'waterway': props.get('name_en') or props['waterway']})
    return corridors


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
    corridors = [] if hazard_zones else flood_corridors(bundle, _read_layer(data_dirs, 'waterways_board.json'))
    board = bundle.get('board', {})
    return {'scenario_id': bundle['scenario_id'], 'name': bundle.get('name', bundle['scenario_id']),
            'data_label': bundle['data_mode'], 'board': board,
            'aspect_ratio': board.get('width_mm', 1) / board.get('height_mm', 1),
            'rivers': rivers, 'hazard_zones': hazard_zones, 'roads': roads, 'sites': sites,
            'flood_corridors': corridors, 'stage_count': len(bundle['hazard']['stages']),
            'hazard': {'method': bundle['hazard'].get('method'),
                       'kind': 'simulated_hazard',
                       'geometry_source': ('scenario_flood_footprints' if hazard_zones else
                                           CORRIDOR_DERIVATION if corridors else 'none'),
                       'limitations': bundle['hazard'].get('limitations', [])},
            'labels': labels, 'provenance_label': bundle['provenance_label']}
