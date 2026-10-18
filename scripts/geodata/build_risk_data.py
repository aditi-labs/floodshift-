"""Measured terrain/population inputs for prevention mode on the HOT-derived map.

Replaces nothing in the schematic bundle. Sources (all open, recorded with hashes):
  * Copernicus DEM GLO-30 (AWS open data COG) — elevation, slope, height above river
  * WorldPop 2020 constrained 100 m population, Nepal — modeled residents per zone
  * Copernicus CEMS GloFAS v2.1.2 RP10/RP100 depth clips (already committed) — flood footprint
  * OSM waterways in the board frame (already committed) — river distance

  python -m scripts.geodata.build_risk_data --download --raw /tmp/floodshift-risk
  python -m scripts.geodata.build_risk_data            # rebuild from committed clips

Outputs: scenarios/nepal_rasuwa_hot_v1/data/{terrain,risk}.json + risk/ clips, and the
same JSON copied into the reasoning bundle (identical geography and board frame).
"""
import argparse
from datetime import date
from hashlib import sha256
import json
import math
from pathlib import Path
import shutil
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
HOT = ROOT / 'scenarios/nepal_rasuwa_hot_v1/data'
REASONING = ROOT / 'scenarios/nepal_rasuwa_reasoning_v1/data'
CLIPS = HOT / 'risk'
FLOOD = REASONING / 'flood'
DEM_URL = ('https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N28_00_E085_00_DEM/'
           'Copernicus_DSM_COG_10_N28_00_E085_00_DEM.tif')
POP_URL = ('https://data.worldpop.org/GIS/Population/Global_2000_2020_Constrained/2020/BSGM/NPL/'
           'npl_ppp_2020_constrained.tif')
DEM_CLIP, POP_CLIP = 'copernicus_glo30_dem_clip.tif', 'worldpop_2020_constrained_clip.tif'
MARGIN_DEG = 0.01  # ~1 km so river sampling near the frame edge still has terrain
ZONE_RADIUS_M = 400  # WorldPop cells farther than this from every zone node are not counted
FLOOD_SAMPLE_M = 100
# Authored weights for an educational exposure index. NOT a calibrated flood probability.
WEIGHTS = {'modeled_flood_footprint': 0.5, 'height_above_river': 0.3, 'river_proximity': 0.2}


def _sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def download(raw, bounds):
    """Window-read the DEM COG and clip WorldPop; raw files stay outside Git."""
    import rasterio
    from rasterio.windows import from_bounds
    raw = Path(raw)
    raw.mkdir(parents=True, exist_ok=True)
    west, south, east, north = bounds[0] - MARGIN_DEG, bounds[1] - MARGIN_DEG, bounds[2] + MARGIN_DEG, bounds[3] + MARGIN_DEG
    pop_full = raw / Path(POP_URL).name
    if not pop_full.exists():
        with urlopen(POP_URL, timeout=120) as response:
            pop_full.write_bytes(response.read())
    CLIPS.mkdir(parents=True, exist_ok=True)
    for source, name in [('/vsicurl/' + DEM_URL, DEM_CLIP), (str(pop_full), POP_CLIP)]:
        with rasterio.open(source) as src:
            window = from_bounds(west, south, east, north, src.transform).round_offsets().round_lengths()
            data = src.read(1, window=window)
            profile = src.profile | {'height': data.shape[0], 'width': data.shape[1], 'driver': 'GTiff',
                                     'transform': src.window_transform(window), 'compress': 'deflate',
                                     'tiled': False}
            profile.pop('blockxsize', None), profile.pop('blockysize', None)
        with rasterio.open(CLIPS / name, 'w', **profile) as dst:
            dst.write(data, 1)
    return {'worldpop_full_sha256': _sha(pop_full), 'retrieved_date': date.today().isoformat()}


class Raster:
    def __init__(self, path):
        import rasterio
        with rasterio.open(path) as src:
            self.data = src.read(1).astype(float)
            self.nodata = src.nodata
            self.transform = src.transform
            self.crs = str(src.crs)
            self.res = src.res

    def sample(self, lon, lat):
        """Bilinear sample in the raster's lon/lat grid; None outside or on no-data."""
        col, row = ~self.transform * (lon, lat)
        c0, r0 = math.floor(col - .5), math.floor(row - .5)
        fc, fr = col - .5 - c0, row - .5 - r0
        values = []
        for dr, dc, w in [(0, 0, (1-fr)*(1-fc)), (0, 1, (1-fr)*fc), (1, 0, fr*(1-fc)), (1, 1, fr*fc)]:
            r, c = r0 + dr, c0 + dc
            if not (0 <= r < self.data.shape[0] and 0 <= c < self.data.shape[1]):
                return None
            v = self.data[r, c]
            if self.nodata is not None and v == self.nodata:
                return None
            values.append(v * w)
        return float(sum(values))

    def cells(self):
        for r in range(self.data.shape[0]):
            for c in range(self.data.shape[1]):
                v = self.data[r, c]
                if self.nodata is not None and v == self.nodata:
                    continue
                lon, lat = self.transform * (c + .5, r + .5)
                yield lon, lat, float(v)


def build(retrieval=None):
    from pyproj import Transformer
    scenario = json.loads((HOT / 'scenario.json').read_text())
    manifest = json.loads((HOT / 'source_manifest.json').read_text())
    roads = json.loads((HOT / 'roads.json').read_text())
    sites = json.loads((HOT / 'sites.json').read_text())
    settlements = json.loads((HOT / 'settlements_board.json').read_text())['features']
    waterways = json.loads((HOT / 'waterways_board.json').read_text())['features']
    hazard = json.loads((REASONING / 'hazard.json').read_text())
    xmin, ymin, xmax, ymax = manifest['projected_bounds']
    size = xmax - xmin
    to_lonlat = Transformer.from_crs(manifest['projected_crs'], 'EPSG:4326', always_xy=True)
    to_xy = Transformer.from_crs('EPSG:4326', manifest['projected_crs'], always_xy=True)

    def uv_to_xy(uv):
        return xmin + uv[0] * size, ymax - uv[1] * size

    nodes = {n['id']: n for n in roads['nodes']}
    # Zones: every population pad node, plus the nearest node to each mapped settlement point.
    zone_nodes = {s['node_id']: s['id'] for s in sites if s['kind'] == 'population_node'}
    for feature in settlements:
        uv = feature['geometry']['coordinates']
        nearest = min(nodes, key=lambda n: math.dist(nodes[n]['board_uv'], uv))
        name = feature['properties'].get('name_en')
        if name or nearest not in zone_nodes:
            zone_nodes[nearest] = name or 'unnamed settlement ' + feature['properties']['source_id']

    dem, pop = Raster(CLIPS / DEM_CLIP), Raster(CLIPS / POP_CLIP)
    rp10, rp100 = (Raster(FLOOD / f'ID192_N30_E80_RP{rp}_depth.tif') for rp in (10, 100))
    quality = Raster(FLOOD / 'ID192_N30_E80_spurious_depth_areas.tif')
    river_points = []
    for feature in waterways:
        for line in ([feature['geometry']['coordinates']] if feature['geometry']['type'] == 'LineString'
                     else feature['geometry']['coordinates']):
            xy = [uv_to_xy(p) for p in line]
            for (ax, ay), (bx, by) in zip(xy, xy[1:]):
                steps = max(1, int(math.dist((ax, ay), (bx, by)) // 10))
                river_points += [(ax + (bx-ax)*t/steps, ay + (by-ay)*t/steps) for t in range(steps + 1)]

    def max_depth(raster, x, y):
        best, flagged = 0.0, False
        for dx in range(-FLOOD_SAMPLE_M, FLOOD_SAMPLE_M + 1, 25):
            for dy in range(-FLOOD_SAMPLE_M, FLOOD_SAMPLE_M + 1, 25):
                if dx*dx + dy*dy > FLOOD_SAMPLE_M**2:
                    continue
                lon, lat = to_lonlat.transform(x + dx, y + dy)
                col, row = ~raster.transform * (lon, lat)
                r, c = int(row), int(col)
                if 0 <= r < raster.data.shape[0] and 0 <= c < raster.data.shape[1]:
                    v = raster.data[r, c]
                    if v != raster.nodata and v > best:
                        best = float(v)
                        flagged = quality.data[r, c] == 1
        return round(best, 2), flagged

    node_terrain, populations = {}, {node: 0.0 for node in zone_nodes}
    for node_id in sorted(zone_nodes):
        x, y = uv_to_xy(nodes[node_id]['board_uv'])
        lon, lat = to_lonlat.transform(x, y)
        elevation = dem.sample(lon, lat)
        gradients = [dem.sample(*to_lonlat.transform(x + dx, y + dy)) for dx, dy in [(30, 0), (-30, 0), (0, 30), (0, -30)]]
        slope = math.hypot((gradients[0] - gradients[1]) / 60, (gradients[2] - gradients[3]) / 60) * 100
        rx, ry = min(river_points, key=lambda p: math.dist(p, (x, y)))
        river_elevation = dem.sample(*to_lonlat.transform(rx, ry))
        d10, q10 = max_depth(rp10, x, y)
        d100, q100 = max_depth(rp100, x, y)
        node_terrain[node_id] = {
            'zone_label': zone_nodes[node_id], 'elevation_m': round(elevation, 1),
            'slope_percent': round(slope, 1), 'distance_to_river_m': round(math.dist((rx, ry), (x, y)), 1),
            'height_above_river_m': round(elevation - river_elevation, 1),
            'flood_depth_rp10_m': d10, 'flood_depth_rp100_m': d100,
            'flood_depth_quality_flagged': bool(q10 or q100),
            'terrain_type': 'measured', 'flood_history_events': None}
    for lon, lat, value in pop.cells():
        x, y = to_xy.transform(lon, lat)
        if not (xmin <= x <= xmax and ymin <= y <= ymax) or value <= 0:
            continue
        nearest = min(zone_nodes, key=lambda n: math.dist(uv_to_xy(nodes[n]['board_uv']), (x, y)))
        if math.dist(uv_to_xy(nodes[nearest]['board_uv']), (x, y)) <= ZONE_RADIUS_M:
            populations[nearest] += value
    population_nodes = {n: {'population': round(v), 'households': None, 'vulnerable_pct': None}
                        for n, v in sorted(populations.items())}
    frame_total = sum(v for lon, lat, v in pop.cells() if v > 0 and
                      xmin <= to_xy.transform(lon, lat)[0] <= xmax and ymin <= to_xy.transform(lon, lat)[1] <= ymax)
    sources = [
        {'id': 'copernicus_glo30', 'url': DEM_URL, 'clip_file': 'risk/' + DEM_CLIP, 'clip_sha256': _sha(CLIPS / DEM_CLIP),
         'license': 'Copernicus DEM GLO-30, free and open (© DLR e.V. 2010-2014 and © Airbus 2014-2018, provided under COPERNICUS by the EU and ESA)',
         'used_for': 'elevation, slope, height above nearest mapped river point'},
        {'id': 'worldpop_2020_constrained', 'url': POP_URL, 'clip_file': 'risk/' + POP_CLIP, 'clip_sha256': _sha(CLIPS / POP_CLIP),
         'license': 'CC BY 4.0, WorldPop (www.worldpop.org), University of Southampton',
         'used_for': f'modeled residents within {ZONE_RADIUS_M} m of each zone node (nearest-node assignment, no double counting)'},
        {'id': 'copernicus_glofas_v2.1.2', 'url': hazard['sources'][0]['url'].rsplit('/RP10/', 1)[0],
         'clip_file': '../../nepal_rasuwa_reasoning_v1/data/flood/', 'license': 'free and open Copernicus product',
         'used_for': f'max modeled RP10/RP100 depth within {FLOOD_SAMPLE_M} m; quality mask flags spurious depths'},
        {'id': 'osm_waterways', 'url': next(r['url'] for r in manifest['resources'] if r['layer'] == 'waterways'),
         'license': 'ODbL, © OpenStreetMap contributors', 'used_for': 'distance to nearest mapped river or stream'}]
    if retrieval:
        sources[1]['full_file_sha256'] = retrieval['worldpop_full_sha256']
        for source in sources[:2]:
            source['retrieved_date'] = retrieval['retrieved_date']
    else:
        previous = json.loads((HOT / 'terrain.json').read_text()) if (HOT / 'terrain.json').exists() else {}
        for source, old in zip(sources[:2], previous.get('data_sources', [])[:2]):
            source.update({k: old[k] for k in ('retrieved_date', 'full_file_sha256') if k in old})
    terrain = {
        'terrain_version': 2, 'scenario_id': scenario['scenario_id'], 'data_mode': 'MEASURED_OPEN_DATA',
        'region': 'Shyaphru Bensi, Rasuwa District, Nepal (2.4 km HOT AOI)',
        'coordinate_system': manifest['projected_crs'], 'board_bounds_projected': manifest['projected_bounds'],
        'data_sources': sources,
        'risk_index': {'name': 'educational_exposure_index', 'weights': WEIGHTS,
                       'terms': {'modeled_flood_footprint': '1 if RP10 depth > 0, 0.7 if only RP100 depth > 0, else 0',
                                 'height_above_river': 'max(0, 1 - height_above_river_m / 30)',
                                 'river_proximity': 'exp(-distance_to_river_m / 200)'},
                       'caveat': 'Authored weights over measured inputs; a relative teaching index, not a flood probability.'},
        'node_terrain': node_terrain,
        'population_data': {'source': 'WorldPop 2020 constrained (modeled estimate, not a census count)',
                            'nodes': population_nodes, 'total_population': sum(p['population'] for p in population_nodes.values()),
                            'frame_total_population': round(frame_total), 'total_households': None},
        'flood_scenarios': {
            f'rp{f["return_period_years"]}': {'name': f'{f["return_period_years"]}-year return-period river flood (modeled)',
                'probability': round(1 / f['return_period_years'], 3), 'affected_edges': hazard['stages'][f['stage']],
                'quality_flagged_wet_pixels': f['quality_flagged_wet_pixels'], 'wet_pixels': f['wet_pixels']}
            for f in hazard['footprints']},
        'limitations': [
            'GloFAS depths are ~90 m statistical return-period maps; most wet pixels here are quality-flagged.',
            'WorldPop is a modeled distribution of residents, not a headcount; zones count only cells within 400 m.',
            'Copernicus GLO-30 is a surface model (includes buildings/trees); height above river uses nearest mapped river point.',
            'No mortality, casualty or evacuation-time data is measured; those outputs remain illustrative model assumptions.']}
    risk = {'risk_model_version': 2, 'scenario_id': scenario['scenario_id'], 'method': 'educational_exposure_index',
            'provenance': 'Measured open data (see terrain.json data_sources); token effects are authored game assumptions.',
            'token_prevention_effects': json.loads((ROOT / 'scenarios/nepal_rasuwa_v1/data/risk.json').read_text())['token_prevention_effects'],
            'token_effects_origin': 'scenario_synthetic'}
    for directory, scenario_id in [(HOT, 'nepal_rasuwa_hot_v1'), (REASONING, 'nepal_rasuwa_reasoning_v1')]:
        for name, value in [('terrain.json', dict(terrain, scenario_id=scenario_id)), ('risk.json', dict(risk, scenario_id=scenario_id))]:
            if directory == REASONING and name == 'terrain.json':
                value = json.loads(json.dumps(value).replace('"risk/', '"../../nepal_rasuwa_hot_v1/data/risk/'))
            (directory / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    return terrain


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--raw', type=Path, default=Path('/tmp/floodshift-risk'))
    args = parser.parse_args()
    retrieval = None
    if args.download:
        bounds = json.loads((HOT / 'source_manifest.json').read_text())['aoi_wgs84_bounds']
        retrieval = download(args.raw, bounds)
    terrain = build(retrieval)
    print(json.dumps({'nodes': terrain['node_terrain'], 'population': terrain['population_data']}, indent=2, ensure_ascii=False))
