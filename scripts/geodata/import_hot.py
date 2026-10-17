"""Clip audited HOT layers around a source settlement and export one board frame.

Produces mapped context and a candidate road graph, NOT a validated game scenario.
Intersection noding/bridge-to-edge matching and approved intervention sites require
review before promotion. Never overwrite the schematic runtime bundle implicitly.
"""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import geopandas as gpd
import pandas as pd
from shapely.geometry import box, mapping
from shapely.affinity import affine_transform


def uv_point(x, y, bounds):
    xmin, ymin, xmax, ymax = bounds
    return [round((x - xmin) / (xmax - xmin), 8), round((ymax - y) / (ymax - ymin), 8)]


def board_geometry(geometry, bounds):
    xmin, ymin, xmax, ymax = bounds
    return mapping(affine_transform(geometry, [1/(xmax-xmin), 0, 0, -1/(ymax-ymin),
                                              -xmin/(xmax-xmin), ymax/(ymax-ymin)]))


def read_layer(path):
    location = path
    if path.suffix == '.zip':
        with ZipFile(path) as archive:
            members = [n for n in archive.namelist() if n.endswith('.gpkg')]
        if len(members) != 1:
            raise ValueError('Expected exactly one GeoPackage in archive')
        location = 'zip://' + str(path.resolve()) + '!' + members[0]
    frame = gpd.read_file(location)
    if frame.crs is None:
        raise ValueError('Source CRS is missing')
    return frame


def import_bundle(raw, output, settlement_id, radius_m=1200):
    if radius_m <= 0:
        raise ValueError('radius_m must be positive')
    raw, output = Path(raw), Path(output)
    inventory = json.loads((raw / 'download_manifest.json').read_text())
    frames, resources = {}, {}
    for resource in inventory['resources']:
        path = raw / resource['filename']
        if hashlib.sha256(path.read_bytes()).hexdigest() != resource['sha256']:
            raise ValueError('Source hash mismatch: ' + resource['layer'])
        frames[resource['layer']] = read_layer(path)
        resources[resource['layer']] = resource
    places = frames['settlements'].to_crs('EPSG:4326')
    selected = places[places['id'] == settlement_id]
    if len(selected) != 1 or selected.geometry.iloc[0].geom_type != 'Point':
        raise ValueError('Choose one point settlement ID from the actual source')
    crs = selected.estimate_utm_crs()
    center = selected.to_crs(crs).geometry.iloc[0]
    bounds = [center.x-radius_m, center.y-radius_m, center.x+radius_m, center.y+radius_m]
    aoi = box(*bounds)
    output.mkdir(parents=True, exist_ok=True)
    audit = dict(inventory, anchor_source_id=settlement_id,
                 anchor_lonlat=list(selected.geometry.iloc[0].coords)[0],
                 projected_crs=crs.to_string(), projected_bounds=bounds,
                 aoi_wgs84_bounds=list(gpd.GeoSeries([aoi], crs=crs).to_crs('EPSG:4326').total_bounds),
                 board_transform={'origin': 'top_left', 'bounds_projected': bounds,
                                  'u': '(x-xmin)/(xmax-xmin)', 'v': '(ymax-y)/(ymax-ymin)'},
                 runtime_promoted=False, layers={},
                 caveats=['Mapped status is source metadata, not field-verified operability.',
                          'Candidate graph connects coincident source vertices only; topology requires review.',
                          'No damage, population demand, travel speed or service suitability is inferred.'])
    graph_nodes, graph_edges = {}, []
    for layer, frame in frames.items():
        projected = frame.to_crs(crs)
        valid = projected.geometry.notna() & ~projected.geometry.is_empty & projected.geometry.is_valid
        clipped = gpd.clip(projected.loc[valid], aoi)
        clipped = clipped[~clipped.geometry.is_empty].sort_values('id')
        features = []
        for _, record in clipped.iterrows():
            props = {k: (None if pd.isna(v) else v) for k, v in record.items() if k != 'geometry'}
            props.update(origin='mapped_OSM', source_id=props['id'])
            features.append({'type': 'Feature', 'properties': props,
                             'geometry': board_geometry(record.geometry, bounds)})
            if layer == 'roads':
                parts = list(record.geometry.geoms) if record.geometry.geom_type == 'MultiLineString' else [record.geometry]
                for part_index, part in enumerate(parts):
                    if part.geom_type != 'LineString':
                        continue
                    coords = list(part.coords)
                    for index, (a, b) in enumerate(zip(coords, coords[1:])):
                        length = ((a[0]-b[0])**2 + (a[1]-b[1])**2)**.5
                        if length < .01:
                            continue
                        ids = []
                        for x, y, *_ in (a, b):
                            node_id = f'{x:.3f}:{y:.3f}'
                            graph_nodes[node_id] = {'id': node_id, 'board_uv': uv_point(x, y, bounds)}
                            ids.append(node_id)
                        graph_edges.append({'id': f'{props["id"]}:{part_index}:{index}',
                            'from': ids[0], 'to': ids[1], 'length_m': round(length, 3),
                            'source_id': props['id'], 'origin': 'mapped_OSM',
                            'mapped_status': props.get('status')})
        (output / (layer + '_board.json')).write_text(json.dumps(
            {'type': 'FeatureCollection', 'coordinate_space': 'board_uv', 'features': features},
            ensure_ascii=False, separators=(',', ':')) + '\n')
        audit['layers'][layer] = {'input_count': len(frame), 'invalid_geometry_count': int((~valid).sum()),
            'clipped_count': len(features), 'fields': sorted(c for c in frame.columns if c != 'geometry'),
            'source_crs': str(frame.crs), 'geometry_types': frame.geom_type.value_counts().to_dict(),
            'source_resource': resources[layer]['url']}
    (output / 'candidate_graph.json').write_text(json.dumps({'nodes': list(graph_nodes.values()),
        'edges': graph_edges, 'validated_for_routing': False}, separators=(',', ':')) + '\n')
    (output / 'source_manifest.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    return audit


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--settlement-id', required=True)
    parser.add_argument('--radius-m', type=float, default=1200)
    args = parser.parse_args()
    audit = import_bundle(args.raw, args.output, args.settlement_id, args.radius_m)
    print(json.dumps({'projected_crs': audit['projected_crs'],
                      'layers': {k: v['clipped_count'] for k, v in audit['layers'].items()}}, indent=2))
