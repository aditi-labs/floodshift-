"""Discover actual HDX resources, download selected layers, and record provenance.

Run with --output /tmp/floodshift-hot. No raw data is written into the repository.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

API = 'https://data.humdata.org/api/3/action/package_show?id=hot_flood_npl_corridor'
LAYERS = {'bridges': ('Bridges (OSM)', 'GeoJSON'),
          'roads': ('Roads (OSM)', 'Geopackage'),
          'waterways': ('Waterways (OSM)', 'GeoJSON'),
          'settlements': ('Settlement Names (OSM)', 'GeoJSON')}


def download(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with urlopen(API, timeout=60) as response:
        package = json.load(response)
    if not package.get('success'):
        raise ValueError('HDX inventory unavailable')
    metadata = package['result']
    audit = {'dataset': metadata['title'], 'inventory_url': API,
             'coverage': 'NPL_CORRIDOR (wider corridor, not the NPL affected-area extract)',
             'license': metadata['license_title'], 'dataset_modified': metadata['metadata_modified'],
             'retrieved_utc': datetime.now(timezone.utc).isoformat(),
             'attribution': '© OpenStreetMap contributors; HOT via HDX', 'resources': []}
    for layer, (name, format_) in LAYERS.items():
        resource = next(r for r in metadata['resources'] if r['name'].startswith(name + ',') and r['format'] == format_)
        url = resource['url']
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname != 'production-raw-data-api.s3.amazonaws.com':
            raise ValueError('Unexpected resource host; inspect before download')
        filename = Path(parsed.path).name
        with urlopen(url, timeout=90) as response:
            content = response.read()
        (output / filename).write_bytes(content)
        audit['resources'].append({'layer': layer, 'filename': filename, 'url': url,
            'format': format_, 'modified': resource.get('last_modified'),
            'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
    (output / 'download_manifest.json').write_text(json.dumps(audit, indent=2) + '\n')
    return audit


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(download(args.output), indent=2))
