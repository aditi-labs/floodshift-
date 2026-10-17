"""Build a compact, source-traceable HOT scenario and prove retained connectivity.

Run from repository root: python -m scripts.geodata.build_hot_scenario
No network or GIS dependencies are needed after import_hot has exported context.
"""
from copy import deepcopy
from hashlib import sha256
from itertools import combinations
from math import atan2, degrees, dist, isclose
from pathlib import Path
import argparse
import json

import networkx as nx

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = ROOT / 'scenarios/nepal_rasuwa_v1/data/hot_context'
OUTPUT = ROOT / 'scenarios/nepal_rasuwa_hot_v1/data'
CROSSINGS = {'crossing_east': 'way/83925870', 'crossing_west': 'way/1017959928',
             'crossing_south': 'way/83925838'}


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def source_graph(candidate):
    graph = nx.Graph()
    for node in candidate['nodes']:
        graph.add_node(node['id'], **node)
    for edge in sorted(candidate['edges'], key=lambda e: e['id']):
        if edge['from'] == edge['to'] or edge['length_m'] <= 0:
            raise ValueError('Invalid source segment')
        if graph.has_edge(edge['from'], edge['to']):
            raise ValueError('Parallel source segments require explicit review')
        graph.add_edge(edge['from'], edge['to'], **edge, weight=edge['length_m'])
    return graph


def nearest_node(graph, uv, allowed=None):
    return min(allowed if allowed is not None else graph.nodes,
               key=lambda n: (dist(uv, graph.nodes[n]['board_uv']), n))


def compact_graph(full, terminals, bridges):
    """Preserve shortest paths between every retained terminal within each bank."""
    closed = full.copy()
    closed.remove_edges_from(bridges.values())
    selected = nx.Graph()
    selected.add_nodes_from((n, deepcopy(full.nodes[n])) for n in terminals)
    for a, b in combinations(sorted(terminals), 2):
        if nx.has_path(closed, a, b):
            path = nx.shortest_path(closed, a, b, weight='weight')
            for u, v in zip(path, path[1:]):
                selected.add_node(u, **deepcopy(full.nodes[u]))
                selected.add_node(v, **deepcopy(full.nodes[v]))
                selected.add_edge(u, v, **deepcopy(full.edges[u, v]))
    for a, b in bridges.values():
        selected.add_edge(a, b, **deepcopy(full.edges[a, b]))
    keep = terminals | {n for n in selected if selected.degree(n) != 2}
    walked, edges = set(), []
    crossing_lookup = {frozenset(pair): name for name, pair in bridges.items()}
    for start in sorted(keep):
        for neighbor in sorted(selected.neighbors(start)):
            key = frozenset((start, neighbor))
            if key in walked:
                continue
            path = [start, neighbor]
            walked.add(key)
            while path[-1] not in keep:
                following = next(n for n in selected.neighbors(path[-1]) if n != path[-2])
                walked.add(frozenset((path[-1], following)))
                path.append(following)
            records = [selected.edges[a, b] for a, b in zip(path, path[1:])]
            crossing = crossing_lookup.get(frozenset((start, neighbor))) if len(path) == 2 else None
            length = sum(e['length_m'] for e in records)
            edge_id = crossing + '_road' if crossing else 'road-' + sha256('|'.join(path).encode()).hexdigest()[:12]
            edges.append({'id': edge_id, 'from': path[0], 'to': path[-1],
                'length_m': round(length, 3), 'weight_min': round(length / 60, 8),
                'cost_method': 'illustrative 60 metres per model minute; not travel prediction',
                'origin': 'mapped_OSM', 'source_refs': sorted({e['source_id'] for e in records}),
                'source_segment_ids': [e['id'] for e in records],
                'board_uv': [selected.nodes[n]['board_uv'] for n in path],
                'mapped_statuses': sorted({e['mapped_status'] for e in records if e.get('mapped_status')}),
                'simulated_blocked_reason': 'illustrative_crossing_closure' if crossing else None})
    nodes = [dict(selected.nodes[n], origin='mapped_OSM') for n in sorted(keep)]
    return {'nodes': nodes, 'edges': sorted(edges, key=lambda e: e['id'])}


def prove_connectivity(full, compact, terminals, bridges):
    """Exhaustively compare all 8 crossing states to the complete imported graph."""
    comparisons = 0
    names = sorted(bridges)
    for mask in range(1 << len(names)):
        reference = full.copy()
        model = nx.Graph()
        model.add_nodes_from(n['id'] for n in compact['nodes'])
        blocked = {name for i, name in enumerate(names) if mask & (1 << i)}
        reference.remove_edges_from(bridges[name] for name in blocked)
        for edge in compact['edges']:
            if edge['id'] in {b + '_road' for b in blocked}:
                continue
            previous = model.get_edge_data(edge['from'], edge['to'])
            if previous is None or previous['weight'] > edge['length_m']:
                model.add_edge(edge['from'], edge['to'], weight=edge['length_m'])
        for a, b in combinations(sorted(terminals), 2):
            reachable = nx.has_path(reference, a, b)
            if reachable != nx.has_path(model, a, b):
                raise ValueError('Compaction changed connectivity')
            if reachable and not isclose(nx.shortest_path_length(reference, a, b, weight='weight'),
                                         nx.shortest_path_length(model, a, b, weight='weight'), abs_tol=.01):
                raise ValueError('Compaction changed shortest path length')
            comparisons += 1
    return {'crossing_states_tested': 1 << len(names), 'terminal_pair_comparisons': comparisons,
            'connectivity_preserved': True, 'shortest_lengths_preserved_within_m': .01}


def build(context=CONTEXT, output=OUTPUT):
    context, output = Path(context), Path(output)
    candidate = read(context / 'candidate_graph.json')
    audit = read(context / 'source_manifest.json')
    full = source_graph(candidate)
    bridge_features = {f['properties']['source_id']: f for f in read(context / 'bridges_board.json')['features']}
    bridges, matches = {}, []
    for name, source_id in CROSSINGS.items():
        segments = [e for e in candidate['edges'] if e['source_id'] == source_id]
        if len(segments) != 1:
            raise ValueError('Crossing must match exactly one source road segment')
        edge = segments[0]
        geom = bridge_features[source_id]['geometry']
        endpoints = [full.nodes[n]['board_uv'] for n in (edge['from'], edge['to'])]
        if geom['type'] != 'LineString' or len(geom['coordinates']) != 2 or any(
                dist(a, b) > 1e-7 for a, b in zip(geom['coordinates'], endpoints)):
            raise ValueError('Bridge geometry does not match road endpoints')
        bridges[name] = (edge['from'], edge['to'])
        matches.append({'site_id': name, 'source_id': source_id, 'road_segment_id': edge['id'],
                        'match_method': 'identical OSM way ID and endpoint geometry',
                        'mapped_status': bridge_features[source_id]['properties'].get('status')})
    closed = full.copy()
    closed.remove_edges_from(bridges.values())
    places = {f['properties']['source_id']: f for f in read(context / 'settlements_board.json')['features']}
    east_id, west_id = 'node/14127413536', 'node/267564991'
    east = nearest_node(full, places[east_id]['geometry']['coordinates'])
    west = nearest_node(full, places[west_id]['geometry']['coordinates'])
    west_bank = nx.node_connected_component(closed, west)
    if nx.has_path(closed, west, east):
        raise ValueError('Chosen baseline does not isolate the settlement')
    # Select distinct game-pad vertices on the mapped west-bank network.
    targets = {'medical_site_west': [.3, .3], 'food_site_west': [.18, .65],
               'shelter_site_west': [.12, .42]}
    pad_nodes = {name: nearest_node(full, uv, west_bank) for name, uv in targets.items()}
    terminals = {east, west, *pad_nodes.values(), *(n for pair in bridges.values() for n in pair)}
    compact = compact_graph(full, terminals, bridges)
    proof = prove_connectivity(full, compact, terminals, bridges)
    sites = []
    def site(id_, kind, node, cost=0, **extra):
        sites.append({'id': id_, 'kind': kind, 'node_id': node,
            'board_uv': full.nodes[node]['board_uv'], 'tolerance_uv': .025,
            'approved': True, 'hazard_exposed': False, 'resource_cost': cost,
            'origin': 'scenario_synthetic', 'position_origin': 'mapped_OSM_road_vertex',
            'approval_basis': 'educational game preset; no real site suitability assessment', **extra})
    site('start_pad', 'control_start_pad', west)
    sites[-1].update(board_uv=[.92, .92], position_origin='off_geography_control')
    demand = {'households_model': 1, 'people_model': 8, 'need_food': 8, 'need_medical': 2, 'need_refuge': 8}
    for name, node, source in [('people_east', east, east_id), ('people_west', west, west_id)]:
        distance_m = dist(full.nodes[node]['board_uv'], places[source]['geometry']['coordinates']) * 2400
        if distance_m > 25:
            raise ValueError('Settlement snap exceeds reviewed 25 metre maximum')
        site(name, 'population_node', node, demand=deepcopy(demand), source_refs=[source],
             source_name=places[source]['properties']['name_en'], settlement_snap_distance_m=distance_m)
    for name, kind, capacity in [('medical_site_west', 'medical_site', 3),
                                 ('food_site_west', 'food_site', 10), ('shelter_site_west', 'shelter_site', 10)]:
        node = pad_nodes[name]
        site(name, kind, node, 1, capacity_model=capacity,
             source_refs=sorted({e['source_id'] for _, _, e in full.edges(node, data=True)}))
    for name, (a, b) in bridges.items():
        uv_a, uv_b = full.nodes[a]['board_uv'], full.nodes[b]['board_uv']
        site(name, 'bridge_crossing', a, 2, edge_id=name + '_road', source_refs=[CROSSINGS[name]])
        sites[-1].update(board_uv=[(x+y)/2 for x, y in zip(uv_a, uv_b)],
                          position_origin='mapped_OSM_bridge_midpoint',
                          rotation_deg=degrees(atan2(uv_b[1]-uv_a[1], uv_b[0]-uv_a[0])))
    for a, b in combinations(sites, 2):
        if dist(a['board_uv'], b['board_uv']) <= a['tolerance_uv'] + b['tolerance_uv']:
            raise ValueError('Overlapping interaction pads: ' + a['id'] + '/' + b['id'])
    scenario = {'scenario_id': 'nepal_rasuwa_hot_v1', 'scenario_version': 2,
        'depot_node': west, 'budget_model': 5,
        'token_inventory': {'disaster_start': 1, 'person': 2, 'hospital': 1, 'food_shelter': 1, 'shelter': 1, 'bridge': 1},
        'data_mode': 'HOT_DERIVED', 'routing_mode': 'illustrative_mixed_road_and_footpath_access',
        'provenance_label': 'HOT/OSM mapped geography; closures, demand, service pads and intervention outcomes are educational assumptions, not operational guidance.',
        'board': {'uv_origin': 'top_left', 'width_mm': 420, 'height_mm': 420,
                  'dimensions_provisional': True, 'aspect_ratio': 1.0,
                  'control_inset_uv': [.84, .84, 1.0, 1.0]},
        'cost_policy': 'Removing or moving a token refunds its model deployment cost; START is latched until reset.'}
    blocked = sorted(name + '_road' for name in bridges)
    manifest = deepcopy(audit)
    manifest.update(data_mode='HOT_DERIVED', historical_geometry_used=True,
        runtime_promoted=True, scenario_id=scenario['scenario_id'],
        build_inputs={p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(context.glob('*.json'))},
        topology_validation={'scope': 'curated educational network, not emergency routing',
            'source_nodes': len(full), 'source_segments': full.number_of_edges(),
            'source_component_sizes': sorted(map(len, nx.connected_components(full)), reverse=True),
            'runtime_nodes': len(compact['nodes']), 'runtime_edges': len(compact['edges']),
            'no_added_road_connections': True, 'junction_policy': 'shared source vertices only; no planar crossing noding or proximity joins',
            'vertex_identity_precision_m': .001, **proof}, bridge_matches=matches,
        model_assumptions={'closure_basis': 'selected mapped crossings closed as an educational preset; mapped status retained separately',
            'service_sites': 'game pads on mapped road vertices; not existing hospitals or assessed safe sites',
            'hazard_exposed': 'preset game eligibility only; no hydrological hazard mask',
            'demand': 'invented household groups, not population observations',
            'model_speed_m_per_min': 60, 'access': 'mixed roads/paths/steps, undirected; no vehicle-access or road-safety claim',
            'board_size': 'square UV area; paper dimensions await P1/P2/P3 calibration'},
        caveats=['OSM mapped status is not field-verified operability.',
                 'Connectivity proof covers selected terminals and three bridge states only.',
                 'Closed bridges and temporary restoration are educational assumptions.',
                 'No source-confirmed safe facility, damage prediction or travel time is implied.'])
    output.mkdir(parents=True, exist_ok=True)
    for name, value in {'scenario': scenario, 'roads': compact, 'points': compact['nodes'],
                        'sites': sites, 'hazard': {'method': 'illustrative_disruption_mask', 'stages': [[], blocked]},
                        'source_manifest': manifest}.items():
        write(output / (name + '.json'), value)
    # Keep all map layers in the exact same UV frame as the runtime road geometry.
    for layer in ['roads', 'bridges', 'waterways', 'settlements']:
        (output / (layer + '_board.json')).write_bytes((context / (layer + '_board.json')).read_bytes())
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', type=Path, default=CONTEXT)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.context, args.output)['topology_validation'], indent=2))
