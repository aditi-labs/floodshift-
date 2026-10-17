from backend.world import WorldService
from backend.world.demo import place, staged_world
from backend.narration.tools import WorldTools
from backend.narration.narration_fallback import narrate


def branch(service, name, snapshot_id):
    return service.apply({'action_id': name, 'type': 'branch', 'branch_id': name,
        'from_snapshot_id': snapshot_id, 'source': 'manual',
        'expected_world_version': service.snapshot()['world_version']})


def test_planner_ranks_computed_gain_and_does_not_mutate():
    service = staged_world()
    before = service.snapshot()
    candidates = service.get_eligible_interventions()
    assert [c['site_id'] for c in candidates] == ['crossing_east', 'crossing_north']
    assert [c['gain_model'] for c in candidates] == [18, 0]
    suggestion = service.suggest()
    assert suggestion['site_id'] == 'crossing_east'
    assert service.snapshot() == before
    place(service, 'bridge', suggestion['site_id'])
    assert service.snapshot()['metrics'] == suggestion['projected_metrics']
    assert service.suggest() is None
    assert WorldService().suggest() is None


def test_counterfactual_branches_are_isolated_and_rewind_from_same_baseline():
    service = staged_world()
    assert branch(service, 'plan-a', 'snap-5')['accepted']
    place(service, 'bridge', 'crossing_east')
    a = service.compare(['main', 'plan-a'])
    assert a['delta_from_first']['plan-a']['unmet_food_model'] == -8
    assert branch(service, 'plan-b', 'snap-5')['accepted']
    assert service.snapshot()['token_inventory']['bridge'] == 1
    place(service, 'bridge', 'crossing_north')
    comparison = service.compare(['plan-a', 'plan-b'])
    assert comparison['delta_from_first']['plan-b']['unmet_food_model'] == 8
    assert service.compare(['main', 'plan-a']) == a
    assert service.snapshot()['world_version'] == 9


def test_narration_tools_are_read_only_and_truthful():
    service = staged_world()
    before = service.snapshot()
    tools = WorldTools(service)
    assert tools.get_unmet_needs()['unmet_food_model'] == 8
    assert tools.get_eligible_interventions()[0]['gain_model'] == 18
    assert not tools.get_route_status('depot', 'village')['reachable']
    assert '8 unmet food units' in narrate(before)
    assert 'not real rescue results' in narrate(before)
    assert service.snapshot() == before
