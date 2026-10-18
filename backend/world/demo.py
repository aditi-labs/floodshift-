"""Run `python -m backend.world.demo` for P4's independent hardware-free proof."""
import json
import argparse
from pathlib import Path

from backend.world import WorldService


def place(service, piece_type, target_site, token_id=None, **overrides):
    site = next(s for s in service.scenario()['sites'] if s['id'] == target_site)
    action = {'action_id': f'demo-{service.snapshot()["world_version"]}', 'type': 'place_token',
              'token_type': piece_type, 'token_id': token_id or piece_type,
              'site_id': target_site, 'board_uv': site['board_uv'], 'source': 'manual',
              'expected_world_version': service.snapshot()['world_version'], **overrides}
    return service.apply(action)


def staged_world(bundle_path=None):
    service = WorldService.from_bundle(bundle_path) if bundle_path else WorldService()
    for kind, site in [('disaster_start', 'start_pad'), ('person', 'people_east'),
                       ('hospital', 'medical_site_west'), ('food_shelter', 'food_site_west'),
                       ('shelter', 'shelter_site_west')]:
        result = place(service, kind, site)
        if not result['accepted']:
            raise RuntimeError(result['reason'])
    return service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-fixtures', action='store_true')
    parser.add_argument('--bundle', type=Path, help='Opt into a bundle without changing shared schematic fixtures')
    args = parser.parse_args()
    service = staged_world(args.bundle)
    # Judge asks "what should we do?": the ghost bridge appears in the snapshot.
    assert service.request_suggestion()['accepted']
    before = service.snapshot()
    result = place(service, 'bridge', 'crossing_east')
    assert result['accepted'], result['reason']
    after = service.snapshot()
    if args.write_fixtures:
        root = Path(__file__).resolve().parents[2]
        artifacts = {'contracts/fixture_world.json': before,
                     'scenarios/nepal_rasuwa_v1/data/fixture_after_bridge.json': after,
                     'scenarios/nepal_rasuwa_v1/data/demo_actions.json':
                         [event['action'] for event in service.event_log()]}
        if args.bundle:
            output = args.bundle.resolve() / 'data'
            artifacts = {output / 'fixture_world.json': before,
                         output / 'fixture_after_bridge.json': after,
                         output / 'demo_actions.json': [event['action'] for event in service.event_log()]}
        for name, value in artifacts.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps({'before': before['metrics'], 'suggestion': before['ghost_suggestion'],
                      'after': after['metrics']}, indent=2))


if __name__ == '__main__':
    main()
