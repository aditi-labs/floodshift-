"""Allocate each independent need once, with stable nearest-service ordering."""
from backend.simulation.routing import route_minutes

NEEDS = {'hospital': ('medical', 'medical'), 'food_shelter': ('food', 'food'),
         'shelter': ('refuge', 'shelter')}


def measure(bundle, state):
    sites = {s['id']: s for s in bundle['sites']}
    restored = {sites[t['site_id']]['edge_id'] for t in state['tokens'].values()
                if t['type'] == 'bridge'}
    blocked_ids = set(bundle['hazard']['stages'][state['simulation_stage']])
    edges = [dict(e, blocked=e['id'] in blocked_ids and e['id'] not in restored,
                  reason='counterfactual_temporary_bridge' if e['id'] in restored else
                  ('illustrative_disruption' if e['id'] in blocked_ids else 'model_open'))
             for e in bundle['roads']['edges']]
    nodes = {n['id']: n for n in bundle['roads']['nodes']}
    def route(a, b):
        return route_minutes(edges, a, b, nodes)
    facilities, people, allocations = [], [], []
    for token in sorted(state['tokens'].values(), key=lambda t: t['id']):
        site = sites[token['site_id']]
        if token['type'] in NEEDS:
            supplied = route(bundle['depot_node'], site['node_id'])['reachable']
            facilities.append({'id': token['id'], 'type': token['type'],
                               'site_id': site['id'], 'node_id': site['node_id'],
                               'capacity_model': site['capacity_model'],
                               'used_capacity_model': 0, 'reachable': supplied,
                               'active': supplied if token['type'] == 'food_shelter' else True})
        elif token['type'] == 'person':
            people.append(dict(site['demand'], id=site['id'], token_id=token['id'],
                               node_id=site['node_id']))
    people.sort(key=lambda p: p['id'])
    metrics = {'blocked_roads': sum(e['blocked'] for e in edges),
               'resource_spent': bundle['budget_model'] - state['budget_remaining_model']}
    for kind, (need, access) in NEEDS.items():
        metrics['unmet_' + need + '_model'] = 0
        metrics['people_reachable_for_' + access] = 0
        for person in people:
            remaining = person['need_' + need]
            candidates = []
            for facility in facilities:
                if facility['type'] != kind or not facility['active']:
                    continue
                result = route(person['node_id'], facility['node_id'])
                if result['reachable']:
                    candidates.append((result['estimated_model_minutes'], facility['id'], facility, result))
            if candidates:
                metrics['people_reachable_for_' + access] += person['people_model']
            for _, _, facility, result in sorted(candidates):
                amount = min(remaining, facility['capacity_model'] - facility['used_capacity_model'])
                if amount <= 0:
                    continue
                facility['used_capacity_model'] += amount
                remaining -= amount
                allocations.append({'population_id': person['id'], 'facility_id': facility['id'],
                                    'need': need, 'units_model': amount, **result,
                                    'board_uv': [nodes[n]['board_uv'] for n in result['path']]})
            metrics['unmet_' + need + '_model'] += remaining
    metrics['reachable_communities'] = sum(route(bundle['depot_node'], p['node_id'])['reachable'] for p in people)
    metrics['road_access_fraction'] = sum(not e['blocked'] for e in edges) / len(edges) if edges else 0
    return {'edges': edges, 'facilities': facilities, 'population_demand': people,
            'routes': allocations, 'metrics': metrics}
