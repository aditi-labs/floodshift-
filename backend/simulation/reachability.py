"""Allocate each independent need once, with stable nearest-service ordering."""
from backend.simulation.routing import route_minutes, route_geometry, route_edge_ids
from backend.simulation.population_positions import split_at_groups

NEEDS = {'hospital': ('medical', 'medical'), 'food_shelter': ('food', 'food'),
         'shelter': ('refuge', 'shelter')}


def measure(bundle, state):
    sites = {s['id']: s for s in bundle['sites']}
    restored = {sites[t['site_id']]['edge_id'] for t in state['tokens'].values()
                if t['type'] == 'bridge'}
    blocked_ids = set(bundle['hazard']['stages'][state['simulation_stage']])
    non_restorable = set(bundle['hazard'].get('non_restorable_stages', [[]]*len(bundle['hazard']['stages']))[state['simulation_stage']])
    excluded_sites = set(bundle['hazard'].get('site_stages', [[]]*len(bundle['hazard']['stages']))[state['simulation_stage']])
    edges = [dict(e, blocked=e['id'] in blocked_ids and (e['id'] not in restored or e['id'] in non_restorable),
                  reason='counterfactual_temporary_bridge' if e['id'] in restored else
                  ('illustrative_disruption' if e['id'] in blocked_ids else 'model_open'))
             for e in bundle['roads']['edges']]
    nodes = {n['id']: n for n in bundle['roads']['nodes']}
    origins = {}
    if 'routing_policy' in bundle:
        edges, nodes, origins = split_at_groups(bundle, state, edges)
    def route(a, b):
        return route_minutes(edges, a, b, nodes)
    facilities, people, allocations = [], [], []
    for token in sorted(state['tokens'].values(), key=lambda t: t['id']):
        site = sites.get(token['site_id'], {'id': token['site_id'], 'node_id': origins.get(token['id']),
            'demand': {'households_model': 0, 'people_model': 0, 'need_food': 0, 'need_medical': 0, 'need_refuge': 0}})
        if token['type'] in NEEDS:
            supplied = route(bundle['depot_node'], site['node_id'])['reachable']
            facilities.append({'id': token['id'], 'type': token['type'],
                               'site_id': site['id'], 'node_id': site['node_id'],
                               'capacity_model': site['capacity_model'],
                               'used_capacity_model': 0, 'reachable': supplied,
                               'active': site['id'] not in excluded_sites and (supplied if token['type'] == 'food_shelter' else True)})
        elif token['type'] == 'person':
            demand = dict(site['demand'])
            if 'population_size_model' in token:
                size = token['population_size_model']
                demand.update(people_model=size, need_food=size, need_refuge=size,
                              need_medical=(size+3)//4, households_model=1)
            people.append(dict(demand, id=site['id'], token_id=token['id'], node_id=site['node_id']))
    if 'routing_policy' in bundle:
        for population in people:
            population.update(headcount_known=False, group_equivalents=1)
    people.sort(key=lambda p: p['id'])
    metrics = {'blocked_roads': sum(e['blocked'] for e in edges),
               'resource_spent': bundle['budget_model'] - state['budget_remaining_model']}
    service_routes = []
    open_edges = [dict(e, blocked=False) for e in edges]
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
                _, _, nearest, result = min(candidates)
                # Geometry is expanded from the same edges, so drawings never shortcut.
                service_routes.append({'population_id': person['id'], 'service': need,
                    'facility_id': nearest['id'], 'reachable': True,
                    'edge_ids': route_edge_ids(edges, result['path']),
                    'board_uv': route_geometry(edges, result['path'], nodes)})
            else:
                # Show where access breaks: the cheapest route if every closure were open.
                blocked_options = []
                for facility in facilities:
                    if facility['type'] == kind and facility['active']:
                        result = route_minutes(open_edges, person['node_id'], facility['node_id'], nodes)
                        if result['reachable']:
                            blocked_options.append((result['estimated_model_minutes'], facility['id'], result))
                if blocked_options:
                    _, facility_id, result = min(blocked_options)
                    service_routes.append({'population_id': person['id'], 'service': need,
                        'facility_id': facility_id, 'reachable': False,
                        'edge_ids': route_edge_ids(open_edges, result['path']),
                        'board_uv': route_geometry(open_edges, result['path'], nodes)})
            for _, _, facility, result in sorted(candidates):
                amount = min(remaining, facility['capacity_model'] - facility['used_capacity_model'])
                if amount <= 0:
                    continue
                facility['used_capacity_model'] += amount
                remaining -= amount
                allocations.append({'population_id': person['id'], 'facility_id': facility['id'],
                                    'need': need, 'units_model': amount, **result,
                                    'board_uv': route_geometry(edges, result['path'], nodes)})
            metrics['unmet_' + need + '_model'] += remaining
            person['unmet_' + need] = remaining
    metrics['reachable_communities'] = sum(route(bundle['depot_node'], p['node_id'])['reachable'] for p in people)
    metrics['road_access_fraction'] = sum(not e['blocked'] for e in edges) / len(edges) if edges else 0
    result = {'edges': edges, 'facilities': facilities, 'population_demand': people,
              'routes': allocations, 'service_routes': service_routes, 'metrics': metrics}
    if 'routing_policy' in bundle:
        result['routing_nodes'] = list(nodes.values())
        result['population_unit'] = 'unspecified_population_group_no_headcount'
    return result
