"""Finite candidate search through the same constraints used for real placement."""
from backend.simulation.reachability import measure
from backend.world.rules import RuleError, reduce_action

GOALS = {'needs_served': ('food', 'medical', 'refuge'), 'food': ('food',),
         'medical': ('medical',), 'refuge': ('refuge',)}


def eligible_interventions(bundle, state, goal='needs_served'):
    if not isinstance(goal, str) or goal not in GOALS:
        raise ValueError('unsupported_goal')
    baseline = measure(bundle, state)['metrics']
    candidates = []
    for site in sorted(bundle['sites'], key=lambda s: s['id']):
        if site['kind'] != 'bridge_crossing':
            continue
        action = {'type': 'place_token', 'token_type': 'bridge', 'source': 'manual',
                  'site_id': site['id'], 'board_uv': site['board_uv']}
        try:
            preview = reduce_action(bundle, state, action)
        except RuleError:
            continue
        after = measure(bundle, preview)['metrics']
        gain = sum(baseline['unmet_' + n + '_model'] - after['unmet_' + n + '_model'] for n in GOALS[goal])
        candidates.append({'token_type': 'bridge', 'site_id': site['id'],
                           'board_uv': site['board_uv'], 'rotation_deg': site.get('rotation_deg', 0),
                           'reason_code': 'improves_multi_service_access' if gain > 0 else 'no_current_need_gain',
                           'gain_model': gain, 'resource_cost': site['resource_cost'],
                           'score': gain * 10 - site['resource_cost'], 'projected_metrics': after})
    return sorted(candidates, key=lambda c: (-c['score'], c['site_id']))


def best_suggestion(bundle, state, goal='needs_served'):
    candidates = eligible_interventions(bundle, state, goal)
    return next((c for c in candidates if c['gain_model'] > 0), None)
