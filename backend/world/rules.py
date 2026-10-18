"""Rules shared by manual and perception actions. Invalid actions never mutate."""
from copy import deepcopy
from math import dist

from backend.simulation.reachability import measure
from backend.simulation.routing import route_minutes
from backend.world.scenarios import valid_uv
from backend.simulation.population_positions import snap_to_road

ALLOWED = {'disaster_start': 'control_start_pad', 'person': 'population_node',
           'hospital': 'medical_site', 'food_shelter': 'food_site',
           'shelter': 'shelter_site', 'bridge': 'bridge_crossing'}
SOURCES = {'manual', 'physical_perceptron', 'physical_local_cv', 'replay'}
VISION_SOURCE = {'physical_perceptron': 'perceptron', 'physical_local_cv': 'local_cv'}


def resolve_site(bundle, token_type, board_uv):
    """Nearest approved pad of the kind this piece may use, or None if none is in reach.

    Camera placements carry only board_uv; the UI sends a site_id as well. Both end
    up here, so a physical piece and a mouse click obey identical tolerances.
    """
    kind = ALLOWED.get(token_type)
    candidates = [s for s in bundle['sites'] if s['kind'] == kind and valid_uv(board_uv)]
    if not candidates:
        return None
    site = min(candidates, key=lambda s: (dist(board_uv, s['board_uv']), s['id']))
    return site if dist(board_uv, site['board_uv']) <= site['tolerance_uv'] else None


class RuleError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise RuleError(reason)


def initial_state(bundle, branch_id='main'):
    return {'phase': 'ready', 'simulation_stage': 0, 'branch_id': branch_id,
            'tokens': {}, 'token_inventory': deepcopy(bundle['token_inventory']),
            'budget_remaining_model': bundle['budget_model'], 'narration_event': None,
            'ghost_goal': None}


def reduce_action(bundle, original, action):
    state = deepcopy(original)
    kind = action['type']
    if kind == 'reset':
        return initial_state(bundle, state['branch_id'])
    if kind == 'advance_stage':
        require(state['phase'] == 'disaster_active', 'start_first')
        require('hazard' in bundle and 'stages' in bundle['hazard'], 'no_hazard_data')
        stage = state['simulation_stage'] + 1
        require(stage < len(bundle['hazard']['stages']), 'last_stage')
        state['simulation_stage'] = stage
        state['narration_event'] = {'event_type': 'stage_advanced', 'model_only': True}
        return state
    require(kind in {'place_token', 'move_token', 'remove_token'}, 'unsupported_action')
    token_id = action.get('token_id')
    # Manual examples in the spec omit identity; use a stable site identity.
    if token_id is None and kind == 'place_token' and action['source'] == 'manual':
        token_id = 'manual:' + str(action.get('site_id', ''))
    require(isinstance(token_id, str) and bool(token_id), 'missing_token_id')
    old = state['tokens'].get(token_id)
    if kind in {'move_token', 'remove_token'}:
        require(old is not None, 'unknown_token')
        require(old['type'] != 'disaster_start', 'start_is_latched')
        require(action.get('token_type', old['type']) == old['type'], 'token_type_mismatch')
        old_site = next((s for s in bundle['sites'] if s['id'] == old['site_id']), {'resource_cost': 0})
        del state['tokens'][token_id]
        state['token_inventory'][old['type']] += 1
        # P0 sandbox: moving/removing returns the model deployment cost.
        state['budget_remaining_model'] += old_site['resource_cost']
        if kind == 'remove_token':
            state['narration_event'] = {'event_type': 'token_removed', 'model_only': True}
            return state
    else:
        require(old is None, 'token_already_placed')
    token_type = action.get('token_type', old['type'] if old else None)
    require(isinstance(token_type, str) and token_type in ALLOWED, 'unsupported_token')
    if action.get('site_id') is None and token_type in ALLOWED and valid_uv(action.get('board_uv')):
        site = resolve_site(bundle, token_type, action['board_uv'])
        require(site is not None or token_type == 'person', 'outside_site')
    else:
        site = next((s for s in bundle['sites'] if s['id'] == action.get('site_id')), None)
    road_snap = None
    if token_type == 'person' and 'routing_policy' in bundle:
        require(valid_uv(action.get('board_uv')), 'invalid_board_uv')
        road_snap = snap_to_road(bundle, action['board_uv'])
        require(road_snap is not None, 'too_far_from_mapped_road')
        site = {'id': 'population:' + token_id, 'kind': 'population_node',
                'board_uv': road_snap['board_uv'], 'tolerance_uv': bundle['routing_policy']['snap_tolerance_uv'],
                'approved': True, 'resource_cost': 0}
    require(site is not None and site['kind'] == ALLOWED[token_type], 'invalid_site')
    require(valid_uv(action.get('board_uv')), 'invalid_board_uv')
    require(dist(action['board_uv'], site['board_uv']) <= site['tolerance_uv'], 'outside_site')
    if token_type == 'disaster_start':
        require(state['phase'] == 'ready', 'already_started')
    else:
        require(state['phase'] == 'disaster_active', 'start_first')
    require(site.get('approved', False), 'site_not_approved')
    require(not any(t['site_id'] == site['id'] for t in state['tokens'].values()), 'site_occupied')
    if token_type in {'hospital', 'food_shelter', 'shelter'}:
        require(not site.get('hazard_exposed', False), 'site_exposed')
        require(site['id'] not in bundle['hazard'].get('site_stages', [[]]*len(bundle['hazard']['stages']))[state['simulation_stage']], 'site_in_flood_footprint')
    require(state['token_inventory'].get(token_type, 0) > 0, 'resource_exhausted')
    require(state['budget_remaining_model'] >= site['resource_cost'], 'insufficient_budget')
    measured = measure(bundle, state)
    if token_type == 'food_shelter':
        require(route_minutes(measured['edges'], bundle['depot_node'], site['node_id'])['reachable'], 'no_supply_route')
    if token_type == 'bridge':
        require(site['edge_id'] not in bundle['hazard'].get('non_restorable_stages', [[]]*len(bundle['hazard']['stages']))[state['simulation_stage']], 'flood_closure_not_restorable')
        require(any(e.get('parent_edge_id', e['id']) == site['edge_id'] and e['blocked'] for e in measured['edges']), 'crossing_already_open')
    if token_type == 'disaster_start':
        state['phase'], state['simulation_stage'] = 'disaster_active', 1
    if token_type == 'bridge':
        state['ghost_goal'] = None
    state['tokens'][token_id] = {'id': token_id, 'type': token_type,
        'board_uv': list(action['board_uv']), 'site_id': site['id'],
        'vision_source': VISION_SOURCE.get(action['source'], action['source']),
        'status': 'accepted'}
    if road_snap is not None:
        state['tokens'][token_id]['road_snap'] = road_snap
    state['token_inventory'][token_type] -= 1
    state['budget_remaining_model'] -= site['resource_cost']
    state['narration_event'] = {'event_type': 'bridge_reconnected' if token_type == 'bridge'
                              else token_type + '_placed', 'model_only': True}
    return state
