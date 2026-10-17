from backend.world import WorldService
from backend.world.demo import place, staged_world
from backend.world.scenarios import load_bundle
from backend.simulation.routing import route_minutes


def test_bridge_reconnects_actual_graph_and_three_services():
    service = staged_world()
    before = service.snapshot()
    assert [before['metrics']['unmet_' + n + '_model'] for n in ('food', 'medical', 'refuge')] == [8, 2, 8]
    assert not service.get_route_status('depot', 'village')['reachable']
    assert place(service, 'bridge', 'crossing_east')['accepted']
    after = service.snapshot()
    assert [after['metrics']['unmet_' + n + '_model'] for n in ('food', 'medical', 'refuge')] == [0, 0, 0]
    assert service.get_route_status('depot', 'village')['estimated_model_minutes'] == 7
    assert all(after['metrics']['people_reachable_for_' + k] == 8 for k in ('food', 'medical', 'shelter'))
    assert len(after['routes']) == 3


def test_capacity_is_shared_and_needs_are_independent():
    service = staged_world()
    assert place(service, 'person', 'people_west', 'person-west')['accepted']
    assert place(service, 'bridge', 'crossing_east')['accepted']
    snapshot = service.snapshot()
    assert [snapshot['metrics']['unmet_' + n + '_model'] for n in ('food', 'medical', 'refuge')] == [6, 1, 6]
    assert all(f['used_capacity_model'] <= f['capacity_model'] for f in snapshot['facilities'])


def test_food_requires_supply_and_loses_it_when_road_blocks():
    service = WorldService()
    place(service, 'disaster_start', 'start_pad')
    assert place(service, 'food_shelter', 'food_site_east')['reason'] == 'no_supply_route'
    place(service, 'person', 'people_west')
    place(service, 'food_shelter', 'food_site_west')
    assert service.snapshot()['metrics']['unmet_food_model'] == 0
    result = service.apply({'action_id': 'stage', 'type': 'advance_stage', 'source': 'manual', 'expected_world_version': 3})
    assert result['accepted']
    assert result['snapshot']['metrics']['unmet_food_model'] == 8
    assert result['snapshot']['facilities'][0]['active'] is False


def test_exposed_site_rejected_without_spend():
    service = WorldService()
    place(service, 'disaster_start', 'start_pad')
    before = service.snapshot()
    assert place(service, 'shelter', 'shelter_site_exposed')['reason'] == 'site_exposed'
    assert service.snapshot() == before


def test_budget_and_inventory_cannot_go_negative():
    bundle = load_bundle()
    bundle['budget_model'] = 1
    service = WorldService(bundle)
    place(service, 'disaster_start', 'start_pad')
    assert place(service, 'bridge', 'crossing_east')['reason'] == 'insufficient_budget'
    service = staged_world()
    place(service, 'bridge', 'crossing_east')
    assert place(service, 'bridge', 'crossing_north', 'bridge-2')['reason'] == 'resource_exhausted'
    assert service.snapshot()['budget_remaining_model'] == 0


def test_remove_bridge_restores_disruption_and_refunds_cost():
    service = staged_world()
    place(service, 'bridge', 'crossing_east')
    result = service.apply({'action_id': 'remove', 'type': 'remove_token', 'token_id': 'bridge',
                            'source': 'manual', 'expected_world_version': 6})
    assert result['accepted']
    assert result['snapshot']['metrics']['unmet_food_model'] == 8
    assert result['snapshot']['budget_remaining_model'] == 2
    assert result['snapshot']['token_inventory']['bridge'] == 1


def test_invalid_move_rolls_back_original_token():
    service = staged_world()
    before = service.snapshot()
    result = service.apply({'action_id': 'move', 'type': 'move_token', 'token_id': 'shelter',
                            'site_id': 'shelter_site_exposed', 'board_uv': [.65, .65],
                            'source': 'manual', 'expected_world_version': 5})
    assert result['reason'] == 'site_exposed'
    assert service.snapshot() == before


def test_route_on_isolated_known_node_and_parallel_edge_cost():
    edges = [{'from': 'a', 'to': 'b', 'weight_min': 3, 'blocked': False},
             {'from': 'a', 'to': 'b', 'weight_min': 9, 'blocked': False}]
    assert route_minutes(edges, 'a', 'b')['estimated_model_minutes'] == 3
    assert route_minutes(edges, 'c', 'c', ['c'])['reachable']
    assert not route_minutes(edges, 'missing', 'missing')['reachable']
