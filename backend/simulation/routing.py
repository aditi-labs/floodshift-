"""Deterministic model routes; minutes are educational costs, not travel advice."""
import networkx as nx


def usable_graph(edges, nodes=()):
    graph = nx.Graph()
    graph.add_nodes_from(nodes)
    for edge in edges:
        graph.add_nodes_from((edge['from'], edge['to']))
        if not edge['blocked']:
            weight = float(edge['weight_min'])
            previous = graph.get_edge_data(edge['from'], edge['to'])
            if previous is None or weight < previous['weight']:
                graph.add_edge(edge['from'], edge['to'], weight=weight)
    return graph


def route_minutes(edges, source, target, nodes=()):
    graph = usable_graph(edges, nodes)
    try:
        minutes, path = nx.single_source_dijkstra(graph, source, target, weight='weight')
        return {'reachable': True, 'path': path, 'estimated_model_minutes': minutes}
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return {'reachable': False, 'path': [], 'estimated_model_minutes': None}


def _cheapest_edge(edges, source, target):
    candidates = [e for e in edges if not e['blocked'] and {e['from'], e['to']} == {source, target}]
    return min(candidates, key=lambda e: float(e['weight_min']))


def route_edge_ids(edges, path):
    """Mapped edge IDs along a node path; split parts report their parent road once."""
    ids = []
    for source, target in zip(path, path[1:]):
        edge = _cheapest_edge(edges, source, target)
        identity = edge.get('parent_edge_id', edge['id'])
        if not ids or ids[-1] != identity:
            ids.append(identity)
    return ids


def route_geometry(edges, path, nodes):
    """Expand a node path along the same cheapest usable edges as usable_graph.

    Compacted HOT edges retain every mapped bend. Drawing only the junctions
    would cut across rivers or terrain instead of following the mapped route.
    """
    if not path:
        return []
    geometry = []
    for source, target in zip(path, path[1:]):
        edge = _cheapest_edge(edges, source, target)
        points = edge.get('board_uv', [nodes[edge['from']]['board_uv'], nodes[edge['to']]['board_uv']])
        points = points if edge['from'] == source else list(reversed(points))
        geometry.extend(points if not geometry else points[1:])
    return geometry or [nodes[path[0]]['board_uv']]
