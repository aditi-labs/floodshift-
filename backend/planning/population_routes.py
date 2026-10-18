"""Fractional group routing, optimized jointly under declared wave capacities.

No headcounts, model training, physical safety claim, or time-dependent crowd model.
"""
from itertools import islice
import networkx as nx

ALGORITHM_VERSION = 'fractional-group-lp-v1'
EPS = 1e-7


def plan_population_routes(bundle, measured):
    import numpy as np
    from scipy.optimize import linprog
    policy = bundle['routing_policy']
    edges = {e['id']: e for e in measured['edges']}
    nodes = {n['id']: n for n in measured.get('routing_nodes', bundle['roads']['nodes'])}
    groups = sorted(measured['population_demand'], key=lambda g: g['token_id'])
    excluded_sites = set(bundle['hazard'].get('site_stages', [[]]*len(bundle['hazard']['stages']))[measured['simulation_stage']])
    facilities = sorted((f for f in measured['facilities'] if f['active'] and f['site_id'] not in excluded_sites), key=lambda f:f['id'])
    shelters = [f for f in facilities if f['type'] == 'shelter']
    limits = {('edge', k): v for k,v in policy['edge_capacity_model'].items()}
    limits.update({('node', k): policy['node_capacity_model'].get(k, policy['snapped_node_capacity_groups']) for k in nodes})
    limits.update({('shelter', f['id']): policy['shelter_capacity_groups'][f['site_id']] for f in shelters})
    graph = nx.Graph()
    graph.add_nodes_from(('n', n) for n in sorted(nodes))
    for edge_id, edge in sorted(edges.items()):
        if not edge['blocked']:
            for node in (edge['from'], edge['to']):
                graph.add_edge(('n', node), ('e', edge_id), weight=edge['weight_min']/2)
    choices, truncated = {}, False

    def candidate(path, shelter, via=None):
        node_path = [identity for kind,identity in path if kind == 'n']
        edge_path = [identity for kind,identity in path if kind == 'e']
        parents = sorted({edges[k].get('parent_edge_id', k) for k in edge_path})
        resources = [('edge', k) for k in parents] + [('node', k) for k in node_path] + [('shelter', shelter['id'])]
        geometry = []
        for start, edge_id in zip(node_path, edge_path):
            edge = edges[edge_id]
            points = edge['board_uv'] if edge['from'] == start else list(reversed(edge['board_uv']))
            geometry.extend(points if not geometry else points[1:])
        return {'shelter_id': shelter['id'], 'node_path': node_path, 'edge_ids': edge_path,
                'mapped_edge_ids': parents, 'model_minutes': sum(edges[k]['weight_min'] for k in edge_path),
                'resources': resources, 'board_uv': geometry or [nodes[node_path[0]]['board_uv']],
                'via_service': via, 'route_id': shelter['id']+'|'+','.join(edge_path)}

    service_alternatives = {}
    for group in groups:
        candidates, visits = [], []
        for shelter in shelters:
            source, target = ('n', group['node_id']), ('n', shelter['node_id'])
            try:
                paths = list(islice(nx.shortest_simple_paths(graph, source, target, weight='weight'), policy['paths_per_shelter']+1))
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                paths = []
            truncated |= len(paths) > policy['paths_per_shelter']
            candidates.extend(candidate(path, shelter) for path in paths[:policy['paths_per_shelter']])
            for facility in facilities:
                if facility['type'] not in {'hospital','food_shelter'}:
                    continue
                via = ('n', facility['node_id'])
                try:
                    # Find the shortest simple candidate through the service, if enumerated.
                    via_paths = [path for path in paths[:policy['paths_per_shelter']] if via in path]
                    if via_paths:
                        path = via_paths[0]
                    else:
                        first = nx.shortest_path(graph, source, via, weight='weight')
                        second = nx.shortest_path(graph, via, target, weight='weight')
                        path = first+second[1:]
                        if len(path) != len(set(path)):
                            continue
                    visits.append(candidate(path,shelter,{'id': facility['id'], 'type': facility['type']}))
                except (nx.NetworkXNoPath,nx.NodeNotFound):
                    continue
        choices[group['token_id']] = sorted(candidates, key=lambda c:(c['model_minutes'],c['route_id']))
        service_alternatives[group['token_id']] = visits
    columns = [(g['token_id'], c) for g in groups for c in choices[g['token_id']]]
    rows = sorted(limits)
    allocations = [0.]*len(columns)
    peak, solver_status = 0., 'no_open_routes'
    if columns:
        # Last variables are peak utilization z and minimum assigned fraction t.
        matrix, bounds = [], []
        for resource in rows:
            row = [float(resource in c['resources']) for _,c in columns]
            matrix.append(row+[0.,0.]); bounds.append(limits[resource])
            matrix.append(row+[-limits[resource],0.]); bounds.append(0.)
        for group in groups:
            group_row = [float(gid == group['token_id']) for gid,_ in columns]
            matrix.append(group_row+[0.,0.]); bounds.append(1.)
            if choices[group['token_id']]:
                matrix.append([-v for v in group_row]+[0.,1.]); bounds.append(0.)
        A, b = np.asarray(matrix), np.asarray(bounds)
        total_row = np.asarray([1.]*len(columns)+[0.,0.])
        options = {'time_limit': 5.0, 'dual_feasibility_tolerance': 1e-9, 'primal_feasibility_tolerance': 1e-9}
        def solve(cost, equality=None, rhs=None):
            result = linprog(cost, A_ub=A, b_ub=b, A_eq=equality, b_eq=rhs,
                             bounds=[(0,1)]*(len(columns)+2), method='highs-ds', options=options)
            if not result.success or np.max(A@result.x-b) > EPS:
                raise RuntimeError('routing_solver_failed')
            return result.x
        x = solve(-total_row)
        routed = float(total_row@x)
        fair_row = np.asarray([0.]*len(columns)+[0.,1.])
        x = solve(-fair_row, [total_row], [routed])
        fair = x[-1]
        peak_row = np.asarray([0.]*len(columns)+[1.,0.])
        x = solve(peak_row, [total_row,fair_row], [routed,fair])
        x = solve([c['model_minutes'] for _,c in columns]+[0.,0.], [total_row,fair_row,peak_row], [routed,fair,x[-2]])
        allocations, peak, solver_status = [float(v) for v in x[:-2]], float(x[-2]), 'optimal_among_candidates'
    loads = {r: sum(amount for amount,(_,c) in zip(allocations,columns) if r in c['resources']) for r in rows}
    decisions = []
    for group in groups:
        identity = group['token_id']
        assigned = [(amount,c) for amount,(gid,c) in zip(allocations,columns) if gid == identity and amount > EPS]
        fraction = min(1.,sum(a for a,_ in assigned))
        def public(c):
            return {k:v for k,v in c.items() if k != 'resources'}
        reason = ('fully_assigned' if fraction >= 1-EPS else 'partially_assigned_capacity_limit' if fraction else
                  'no_active_unexposed_shelter' if not shelters else 'no_open_route' if not choices[identity] else 'capacity_limit')
        alternatives = []
        for c in choices[identity]+service_alternatives[identity]:
            other_load = {r: loads[r]-sum(a for a,own in assigned if r in own['resources']) for r in c['resources']}
            available = max(0., min([1.]+[limits[r]-other_load[r] for r in c['resources']]))
            alternatives.append({**public(c), 'available_group_fraction_replacing_this_group': round(available,8),
                                 'service_stop_capacity_verified': False if c['via_service'] else None})
        preferred = choices[identity][0] if choices[identity] else None
        decisions.append({'group_id': identity, 'origin_node': group['node_id'], 'reason_code': reason,
            'assigned_fraction': round(fraction,8), 'unassigned_fraction': round(1-fraction,8),
            'preferred_route_ignoring_crowding': public(preferred) if preferred else None,
            'routes': [{**public(c),'fraction': round(a,8),
                        'extra_model_minutes_vs_preferred': c['model_minutes']-preferred['model_minutes'],
                        'selection_reason': 'joint_capacity_fairness_load_balance_then_travel'} for a,c in assigned],
            'alternatives': alternatives,
            'explanation': (f"Group {identity}: {fraction:.0%} is assigned across {len(assigned)} route(s). "
                f"{1-fraction:.0%} remains unassigned. " +
                ' '.join(f"{a:.0%} goes to {c['shelter_id']} over {len(c['edge_ids'])} road sections." for a,c in assigned) +
                ' The plan first maximizes routed groups, then fair shares, then reduces peak crowding and travel cost. It respects '
                'assumed shared road, junction and shelter capacities. No headcount or verified real-world safety is implied.')})
    return {'algorithm_version': ALGORITHM_VERSION, 'model_only': True, 'population_unit': 'group_fraction_not_headcount',
            'objective': ['maximize_routed_group_fraction','maximize_minimum_reachable_group_share','minimize_peak_capacity_utilization','minimize_group_weighted_model_time'],
            'capacity_semantics': 'shared_conservative_wave_reservations_not_a_timetable',
            'optimality': solver_status, 'candidate_paths_truncated': truncated,
            'assigned_group_equivalents': round(sum(allocations),8),
            'unassigned_group_equivalents': round(len(groups)-sum(allocations),8),
            'peak_utilization': round(peak,8), 'groups': decisions,
            'blocked_edge_ids': sorted({e.get('parent_edge_id',k) for k,e in edges.items() if e['blocked']}),
            'excluded_facility_site_ids': sorted(excluded_sites),
            'loads': [{'kind':r[0],'id':r[1],'reserved_groups':round(loads[r],8),'capacity_groups':limits[r]} for r in rows],
            'assumptions': policy['assumptions'],
            'flood_evidence': {'method': bundle['hazard']['method'], 'limitations': bundle['hazard'].get('limitations', []),
                'footprint': [{k:v for k,v in f.items() if k != 'geometry'} for f in bundle['hazard'].get('footprints', []) if f['stage'] == measured['simulation_stage']]}}
