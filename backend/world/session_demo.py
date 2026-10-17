"""Run twice with the same --session file to demonstrate restart recovery."""
import argparse
import json

from backend.narration.gemini_adapter import GeminiNarrator
from backend.world import WorldService
from backend.world.demo import place


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', required=True, help='Local SQLite file outside Git; parent directory must exist')
    parser.add_argument('--bundle', default='scenarios/nepal_rasuwa_hot_v1')
    args = parser.parse_args()
    world = WorldService.open_session(args.session, args.bundle)
    recovered = world.snapshot()['world_version'] > 0
    if not recovered:
        for token, site in [('disaster_start', 'start_pad'), ('person', 'people_east'),
                            ('hospital', 'medical_site_west'), ('food_shelter', 'food_site_west'),
                            ('shelter', 'shelter_site_west'), ('bridge', 'crossing_east')]:
            result = place(world, token, site)
            if not result['accepted']:
                raise RuntimeError(result['reason'])
    snapshot = world.snapshot()
    print(json.dumps({'recovered': recovered, 'world_version': snapshot['world_version'],
        'metrics': snapshot['metrics'], 'narration': GeminiNarrator(enabled=False).answer(world, 'What changed?')}, indent=2))


if __name__ == '__main__':
    main()
