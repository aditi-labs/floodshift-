"""Run a bounded, real Gemini acceptance check independently of the API gateway.

No network unless --live is explicit. A fallback NEVER passes a live test.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter, sleep

from backend.narration.gemini_adapter import GeminiNarrator
from backend.narration.local_config import ConfigError, read_config
from backend.world.demo import staged_world, place

DEFAULT_BUNDLE = Path(__file__).resolve().parents[2] / 'scenarios/nepal_rasuwa_hot_v1'


def run_smoke(narrator, bundle=DEFAULT_BUNDLE, live=False, interval_seconds=0):
    world = staged_world(bundle)
    cases = []
    def ask(name, question):
        if (live and cases and interval_seconds
                and cases[-1]['reason'] not in {'missing_api_key', 'sdk_unavailable', 'client_unavailable'}):
            sleep(interval_seconds)
        before = world.snapshot()
        start = perf_counter()
        result = narrator.answer(world, question)
        elapsed_ms = round((perf_counter() - start) * 1000)
        unchanged = world.snapshot() == before
        cases.append({'name': name, 'question': question, 'elapsed_ms': elapsed_ms,
                      'world_unchanged': unchanged, **result})
    ask('blocked_access', 'Use the simulator tools: why can this household not reach food, care and refuge, and where should we put the bridge?')
    version = world.snapshot()['world_version']
    branch = world.apply({'action_id': 'smoke-branch', 'type': 'branch', 'branch_id': 'restored',
                         'source': 'manual', 'expected_world_version': version})
    if not branch['accepted'] or not place(world, 'bridge', 'crossing_east')['accepted']:
        raise RuntimeError('smoke_scenario_failed')
    ask('branch_comparison', 'Use compare_branches with branch_a="main" and branch_b="restored". What changed in food, medical and refuge needs?')
    ask('historical_claim', 'Did we save 10,000 real people? Use the simulator facts and distinguish real geography from educational outcomes.')
    live_verified = all(c['mode'] == 'LIVE' and c['tools_used'] and c['world_unchanged'] for c in cases)
    return {'report_version': 1, 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
            'scenario_id': world.snapshot()['scenario_id'], 'model': narrator.model,
            'requested_mode': 'LIVE' if live else 'TEXT',
            'live_transport_and_tools_verified': live_verified if live else False,
            'narration_text_review_required': True,
            'cases': cases}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Actually call Gemini; may consume account quota')
    parser.add_argument('--env-file', type=Path, help='Local ignored key file; never printed')
    parser.add_argument('--bundle', type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument('--model', help='Override model ID')
    parser.add_argument('--report', type=Path, help='Save JSON evidence outside Git or to an ignored path')
    parser.add_argument('--timeout-ms', type=int, default=10000, help='Per-request timeout; max 10000')
    parser.add_argument('--interval-seconds', type=int, default=60,
                        help='Pause between live questions for free-tier quota (0–120; default 60)')
    args = parser.parse_args(argv)
    try:
        if not 0 <= args.interval_seconds <= 120:
            raise ValueError('invalid_interval')
        values = read_config(args.env_file) if args.env_file else {}
        narrator = GeminiNarrator(enabled=args.live, api_key=values.get('GEMINI_API_KEY'),
            model=args.model or values.get('GEMINI_MODEL') or None,
            timeout_ms=args.timeout_ms, require_tool_call=True)
        report = run_smoke(narrator, args.bundle, args.live, args.interval_seconds)
        encoded = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
        if args.report:
            args.report.write_text(encoded, encoding='utf-8')
        print(encoded, end='')
        return 0 if not args.live or report['live_transport_and_tools_verified'] else 1
    except (ConfigError, OSError, ValueError, RuntimeError):
        # Never print a traceback/exception that could include a configuration value.
        print(json.dumps({'error': 'smoke_setup_failed', 'live_transport_and_tools_verified': False,
                          'hint': 'Check the config format, bundle path, timeout (1–10000), and report directory.'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
