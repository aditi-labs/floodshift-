"""Snap tokens to actual polyline segments and split edges without shortcuts."""
from copy import deepcopy
from math import dist


def snap_to_road(bundle, uv):
    best = None
    for edge in sorted(bundle['roads']['edges'], key=lambda e: e['id']):
        points = edge['board_uv']
        lengths = [dist(a,b) for a,b in zip(points, points[1:])]
        total = sum(lengths)
        if total <= 0:
            continue
        before = 0
        for index, (a,b,length) in enumerate(zip(points, points[1:], lengths)):
            if length == 0:
                continue
            t = max(0., min(1., sum((uv[i]-a[i])*(b[i]-a[i]) for i in (0,1))/length**2))
            point = [a[i]+t*(b[i]-a[i]) for i in (0,1)]
            candidate = (dist(uv, point), edge['id'], (before+t*length)/total, point)
            if best is None or candidate[:3] < best[:3]:
                best = candidate
            before += length
    if best is None or best[0] > bundle['routing_policy']['snap_tolerance_uv']:
        return None
    return {'edge_id': best[1], 'fraction': best[2], 'board_uv': best[3], 'distance_uv': best[0]}


def split_at_groups(bundle, state, edges):
    """Keep full road bends and exact snapped origin; share parent edge capacity."""
    nodes = {n['id']: deepcopy(n) for n in bundle['roads']['nodes']}
    by_edge = {}
    origins = {}
    for token in state['tokens'].values():
        if token['type'] != 'person' or 'road_snap' not in token:
            continue
        snap = token['road_snap']
        edge = next(e for e in edges if e['id'] == snap['edge_id'])
        fraction = snap['fraction']
        if fraction <= 1e-10:
            origins[token['id']] = edge['from']
        elif fraction >= 1-1e-10:
            origins[token['id']] = edge['to']
        else:
            # Co-located groups share one topological vertex.
            identity = f"snap:{edge['id']}:{fraction:.10f}"
            origins[token['id']] = identity
            nodes[identity] = {'id': identity, 'board_uv': snap['board_uv'], 'parent_edge_id': edge['id']}
            by_edge.setdefault(edge['id'], {})[identity] = fraction
    output = []
    for edge in edges:
        cuts = sorted((fraction, identity) for identity,fraction in by_edge.get(edge['id'], {}).items())
        if not cuts:
            output.append(deepcopy(edge)); continue
        points = edge['board_uv']
        lengths = [dist(a,b) for a,b in zip(points, points[1:])]
        total, cumulative = sum(lengths), [0.]
        for length in lengths:
            cumulative.append(cumulative[-1]+length)
        positions = [value/total for value in cumulative]
        stops = [(0., edge['from'])]+cuts+[(1., edge['to'])]
        for i, ((lo,start),(hi,end)) in enumerate(zip(stops,stops[1:])):
            part = deepcopy(edge)
            part.update(id=f"{edge['id']}::part:{i}", parent_edge_id=edge['id'],
                        weight_min=edge['weight_min']*(hi-lo))
            part['from'], part['to'] = start,end
            part['board_uv'] = [nodes[start]['board_uv']]+[point for t,point in zip(positions,points) if lo<t<hi]+[nodes[end]['board_uv']]
            output.append(part)
    return output, nodes, origins
