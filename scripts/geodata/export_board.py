"""Export paired reference SVGs in the authoritative board UV frame.

These data deliverables do not change P1/P2 visual_assets or add camera markers.
"""
import argparse
import json
from pathlib import Path
from xml.etree import ElementTree as ET

NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
LABELS = {'control_start_pad': 'START', 'population_node': 'Person',
          'medical_site': 'Hospital', 'food_site': 'Food shelter',
          'shelter_site': 'Shelter', 'bridge_crossing': 'Bridge'}
PAD_NAMES = {'start_pad': 'Start the scenario', 'people_east': 'Person — east',
             'people_west': 'Person — west', 'medical_site_west': 'Hospital',
             'food_site_west': 'Food shelter', 'shelter_site_west': 'Overnight shelter',
             'crossing_east': 'Bridge — east', 'crossing_west': 'Bridge — west',
             'crossing_south': 'Bridge — south'}


def element(parent, tag, **attrs):
    return ET.SubElement(parent, '{' + NS + '}' + tag,
                         {key.replace('_', '-'): str(value) for key, value in attrs.items()})


def text(parent, x, y, value, **attrs):
    node = element(parent, 'text', x=x, y=y, **attrs)
    node.text = value
    return node


def render(data, mode):
    scenario = json.loads((data / 'scenario.json').read_text())
    sites = json.loads((data / 'sites.json').read_text())
    board = scenario['board']
    root = ET.Element('{' + NS + '}svg', {
        'viewBox': '0 0 1000 1000', 'width': f"{board['width_mm']}mm",
        'height': f"{board['height_mm']}mm", 'data-coordinate-space': 'board_uv',
        'data-scenario-id': scenario['scenario_id'], 'data-mode': mode})
    element(root, 'title').text = 'FLOODSHIFT — Shyaphru Bensi, Nepal — reference board'
    element(root, 'desc').text = ('One board UV transform: SVG x=1000*u, y=1000*v. '
        'Provisional physical dimensions. Synthetic game pads, not real facilities. '
        'No calibration markers; P1/P2/P3 must verify physical registration.')
    dark = mode == 'projection'
    ink = '#e8edf2' if dark else '#23394b'
    element(root, 'rect', width=1000, height=1000, fill='#101923' if dark else '#ffffff')
    defs = element(root, 'defs')
    clip = element(defs, 'clipPath', id='map-frame')
    element(clip, 'rect', width=1000, height=1000)
    geometry = element(root, 'g', id='mapped-context', clip_path='url(#map-frame)')
    for layer, color, width in [('roads', '#617384' if dark else '#c6cdd2', 1),
                                 ('waterways', '#4189bd' if dark else '#9bcde4', 3)]:
        features = json.loads((data / (layer + '_board.json')).read_text())['features']
        group = element(geometry, 'g', id=layer, fill='none', stroke=color, stroke_width=width)
        for feature in features:
            geom = feature['geometry']
            if geom['type'] not in ('LineString', 'MultiLineString'):
                continue
            parts = [geom['coordinates']] if geom['type'] == 'LineString' else geom['coordinates']
            for part in parts:
                element(group, 'polyline', points=' '.join(f'{u*1000:.6f},{v*1000:.6f}' for u,v in part))
    left, top, right, bottom = board['control_inset_uv']
    element(root, 'rect', id='control-panel', x=left*1000, y=top*1000,
            width=(right-left)*1000, height=(bottom-top)*1000,
            fill='#101923' if dark else '#ffffff', stroke=ink)
    text(root, (left+right)*500, top*1000+25, 'CONTROL', fill=ink,
         font_size=14, text_anchor='middle')
    pads = element(root, 'g', id='placement-pads', font_family='sans-serif')
    for number, site in enumerate(sites, 1):
        x,y = (value*1000 for value in site['board_uv'])
        group = element(pads, 'g', id=site['id'])
        element(group, 'title').text = f"{LABELS[site['kind']]}: {site['id']} (educational placement pad)"
        element(group, 'circle', cx=x, cy=y, r=site['tolerance_uv']*1000,
                fill='#101923' if dark else '#ffffff', stroke=ink, stroke_width=1.5)
        text(group, x, y+6, str(number), fill=ink, font_size=18, text_anchor='middle')
    text(root, 30, 35, 'FLOODSHIFT | Shyaphru Bensi, Nepal', fill=ink, font_size=23,
         font_family='sans-serif')
    text(root, 30, 59, 'HOT-derived geography | hypothetical game placements',
         fill=ink, font_size=14, font_family='sans-serif')
    for number, site in enumerate(sites, 1):
        # Two compact legend columns, independent of the map/pad transform.
        col, row = divmod(number-1, 5)
        text(root, 30+col*370, 85+row*19,
             f"{number}. {PAD_NAMES.get(site['id'], LABELS[site['kind']])}",
             fill=ink, font_size=12, font_family='sans-serif')
    text(root, 25, 958, 'Place token centres inside matching numbered circles. START first.',
         fill=ink, font_size=13, font_family='sans-serif')
    text(root, 25, 977, '© OpenStreetMap contributors · HOT / HDX · ODbL',
         fill=ink, font_size=12, font_family='sans-serif')
    text(root, 25, 994, 'Educational model; not emergency routing. Physical dimensions provisional.',
         fill=ink, font_size=11, font_family='sans-serif')
    return ET.tostring(root, encoding='unicode', xml_declaration=True) + '\n'


def export(bundle):
    data = Path(bundle) / 'data'
    for mode in ('print', 'projection'):
        (data / f'map_{mode}.svg').write_text(render(data, mode), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=Path('scenarios/nepal_rasuwa_hot_v1'))
    export(parser.parse_args().bundle)
