"""Game layer: a transparent score, objectives and results derived from measured state.

Everything here is a pure function of (bundle, state). The score is never
accumulated from events, so placing and removing the same piece returns the same
score and repeated cycles cannot farm points. It is a GAME score for comparing
strategies inside this educational scenario, not a humanitarian outcome metric.
"""
from copy import deepcopy

from backend.simulation.reachability import measure

# One configurable place for every weight. Units: points per model unit.
SCORING = {
    'access_per_unit': 5,           # + per model person newly able to reach a service, per service kind
    'need_met_per_unit': 10,        # + per unit of essential need met beyond the no-response baseline
    'reconnect_per_community': 50,  # + per modeled community newly connected to the supply depot
    'unmet_penalty_per_unit': 2,    # - per unit of essential need still unmet
    'spend_penalty_per_unit': 15,   # - per unit of model budget spent
    'ineffective_penalty': 40,      # - per intervention whose removal changes no measured outcome
    'unmet_reduction_goal': 0.4,    # objective: cut unmet need to at most this share of the baseline
}

FORMULA = ('score = 5·Δaccess + 10·Δneeds_met + 50·Δcommunities − 2·unmet − 15·budget_spent '
           '− 40·ineffective_interventions (Δ = versus the same flood stage with no response pieces)')

NON_INTERVENTIONS = {'disaster_start', 'person'}
NEEDS = ('food', 'medical', 'refuge')
ACCESS = {'food': 'food', 'medical': 'medical', 'refuge': 'shelter'}
OUTCOME_KEYS = (['unmet_' + n + '_model' for n in NEEDS] +
                ['people_reachable_for_' + a for a in ACCESS.values()] + ['reachable_communities'])
LABELS = {'hospital': 'Hospital', 'food_shelter': 'Food & water station', 'shelter': 'Shelter',
          'bridge': 'Temporary bridge'}


def _without(state, keep):
    """Same stage and branch with only the tokens ``keep`` accepts."""
    clone = deepcopy(state)
    clone['tokens'] = {k: t for k, t in clone['tokens'].items() if keep(t)}
    return clone


def _outcomes(metrics):
    return {k: metrics.get(k, 0) for k in OUTCOME_KEYS}


def score_breakdown(baseline, current, spent, ineffective):
    access = sum(current['people_reachable_for_' + a] - baseline['people_reachable_for_' + a]
                 for a in ACCESS.values())
    unmet = sum(current['unmet_' + n + '_model'] for n in NEEDS)
    met = sum(baseline['unmet_' + n + '_model'] for n in NEEDS) - unmet
    reconnected = current['reachable_communities'] - baseline['reachable_communities']
    parts = {
        'access': SCORING['access_per_unit'] * access,
        'needs_met': SCORING['need_met_per_unit'] * met,
        'communities': SCORING['reconnect_per_community'] * reconnected,
        'unmet_penalty': -SCORING['unmet_penalty_per_unit'] * unmet,
        'spend_penalty': -SCORING['spend_penalty_per_unit'] * spent,
        'ineffective_penalty': -SCORING['ineffective_penalty'] * ineffective,
    }
    return sum(parts.values()), parts


def evaluate(bundle, state, measured=None):
    """Score, objectives and an honest results summary for one world state."""
    measured = measured or measure(bundle, state)
    metrics = measured['metrics']
    people = measured['population_demand']
    if state['phase'] != 'disaster_active':
        return {'status': 'not_started', 'score': 0, 'score_parts': {}, 'formula': FORMULA,
                'weights': dict(SCORING), 'objectives': [], 'interventions': [],
                'label': 'Game score — compares strategies in this educational model; not a real outcome metric'}
    sites = {s['id']: s for s in bundle['sites']}
    baseline = _outcomes(measure(bundle, _without(state, lambda t: t['type'] in NON_INTERVENTIONS))['metrics'])
    current = _outcomes(metrics)
    interventions = []
    for token in sorted(state['tokens'].values(), key=lambda t: t['id']):
        if token['type'] in NON_INTERVENTIONS:
            continue
        without = _outcomes(measure(bundle, _without(state, lambda t, own=token['id']: t['id'] != own))['metrics'])
        marginal = {k: current[k] - without[k] for k in OUTCOME_KEYS}
        site = sites.get(token['site_id'], {})
        interventions.append({'token_id': token['id'], 'type': token['type'], 'site_id': token['site_id'],
                              'label': LABELS.get(token['type'], token['type']),
                              'cost_model': site.get('resource_cost', 0),
                              'effective': any(marginal.values()), 'marginal': marginal})
    spent = sum(i['cost_model'] for i in interventions)
    ineffective = sum(not i['effective'] for i in interventions)
    score, parts = score_breakdown(baseline, current, spent, ineffective)
    total_need = sum(p['need_' + n] for p in people for n in NEEDS)
    unmet = sum(current['unmet_' + n + '_model'] for n in NEEDS)
    baseline_unmet = sum(baseline['unmet_' + n + '_model'] for n in NEEDS)
    reachable = {(r['population_id'], r['service']) for r in measured['service_routes'] if r['reachable']}
    covered = [p for p in people if all((p['id'], n) in reachable for n in NEEDS)]
    restored = [i for i in interventions if i['type'] == 'bridge' and any(
        r['reachable'] and sites.get(i['site_id'], {}).get('edge_id') in r['edge_ids']
        for r in measured['service_routes'])]
    communities = len(people)
    objectives = [
        {'id': 'restore_access', 'label': 'Restore access across the flood',
         'complete': bool(restored),
         'detail': f"{len(restored)} bridge(s) carry a reachable service route" if restored
                   else 'No bridge currently carries a reachable service route'},
        {'id': 'connect_communities', 'label': 'Connect isolated communities',
         'complete': communities > 0 and current['reachable_communities'] == communities,
         'detail': f"{current['reachable_communities']}/{communities} model communities reach the supply depot"},
        {'id': 'service_coverage', 'label': 'Establish essential service coverage',
         'complete': communities > 0 and len(covered) == communities,
         'detail': f"{len(covered)}/{communities} communities reach medical, food and shelter"},
        {'id': 'minimize_unmet', 'label': 'Minimize unmet needs',
         'complete': baseline_unmet > 0 and unmet <= SCORING['unmet_reduction_goal'] * baseline_unmet,
         'detail': f"{unmet} of {baseline_unmet} need units unmet (goal ≤ {SCORING['unmet_reduction_goal']:.0%} of no-response)"},
        {'id': 'within_budget', 'label': 'Stay within budget',
         'complete': bool(interventions) and state['budget_remaining_model'] >= 0 and ineffective == 0,
         'detail': f"{spent} of {bundle['budget_model']} budget spent, {ineffective} ineffective piece(s)"},
    ]
    return {'status': 'active', 'score': score, 'score_parts': parts, 'formula': FORMULA,
            'weights': dict(SCORING),
            'label': 'Game score — compares strategies in this educational model; not a real outcome metric',
            'population_unit': 'model people units (no verified headcount)',
            'baseline': baseline, 'current': current, 'communities_total': communities,
            'communities_reconnected': current['reachable_communities'] - baseline['reachable_communities'],
            'total_need_model': total_need, 'unmet_total_model': unmet, 'baseline_unmet_total_model': baseline_unmet,
            'budget_total_model': bundle['budget_model'], 'budget_spent_model': spent,
            'ineffective_interventions': ineffective, 'interventions': interventions,
            'objectives': objectives, 'summary': _summary(measured, interventions, current, baseline)}


def _summary(measured, interventions, current, baseline):
    """Plain statements of what improved and what did not, read off the measurements."""
    improved, unresolved = [], []
    for item in interventions:
        m = item['marginal']
        gains = [f"{-m['unmet_' + n + '_model']} {n}" for n in NEEDS if m['unmet_' + n + '_model'] < 0]
        if m['reachable_communities'] > 0:
            gains.append(f"{m['reachable_communities']} community reconnected")
        if gains:
            improved.append(f"{item['label']} ({item['site_id']}): " + ', '.join(gains) + ' need units served')
        else:
            unresolved.append(f"{item['label']} ({item['site_id']}) changed no measured outcome")
    reachable = {(r['population_id'], r['service']) for r in measured['service_routes'] if r['reachable']}
    for need in NEEDS:
        left = current['unmet_' + need + '_model']
        if left <= 0:
            continue
        cut = sorted({p['id'] for p in measured['population_demand'] if (p['id'], need) not in reachable})
        cause = (f"no open route for {', '.join(cut)}" if cut else 'facility capacity is exhausted')
        unresolved.append(f"{left} {need} need units remain unmet — {cause}")
    if current['reachable_communities'] < len(measured['population_demand']):
        unresolved.append(f"{len(measured['population_demand']) - current['reachable_communities']} "
                          'community(ies) still cut off from the supply depot')
    return {'improved': improved, 'unresolved': unresolved}
