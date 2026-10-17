"""Paired board geometry must match the authoritative physical placement frame."""
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from scripts.geodata.export_board import render

DATA = Path(__file__).resolve().parents[1] / 'scenarios/nepal_rasuwa_hot_v1/data'
NS = {'s': 'http://www.w3.org/2000/svg'}


def test_pair_preserves_every_pad_and_mapped_polyline():
    roots = [ET.fromstring(render(DATA, mode)) for mode in ('print', 'projection')]
    for root in roots:
        assert root.attrib['viewBox'] == '0 0 1000 1000'
        assert root.attrib['width'] == root.attrib['height'] == '420mm'
        for site in json.loads((DATA / 'sites.json').read_text()):
            circle = root.find(f".//s:g[@id='{site['id']}']/s:circle", NS)
            assert circle is not None
            assert float(circle.attrib['cx']) == site['board_uv'][0] * 1000
            assert float(circle.attrib['cy']) == site['board_uv'][1] * 1000
            assert float(circle.attrib['r']) == site['tolerance_uv'] * 1000
    lines = [[line.attrib['points'] for line in root.findall('.//s:polyline', NS)] for root in roots]
    assert lines[0] and lines[0] == lines[1]
    assert roots[0].find(".//s:rect[@id='control-panel']", NS).attrib['x'] == '840.0'


def test_committed_pair_is_reproducible():
    for mode in ('print', 'projection'):
        assert (DATA / f'map_{mode}.svg').read_text() == render(DATA, mode)
