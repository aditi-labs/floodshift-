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
