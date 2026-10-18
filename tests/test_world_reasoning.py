from copy import deepcopy
from pathlib import Path
from math import dist
import json

import pytest

from backend.planning.population_routes import plan_population_routes
from backend.world import WorldService
from backend.world.demo import place
from backend.simulation.population_positions import snap_to_road, split_at_groups
from backend.narration.decision_narration import speech_payload
from scripts.geodata.build_reasoning_scenario import build

ROOT=Path(__file__).resolve().parents[1]
BUNDLE=ROOT/'scenarios/nepal_rasuwa_reasoning_v1'


def diamond(capacity=1):
    coords={'a':[0,0], 'b':[.5,0], 'c':[.5,1], 'd':[1,0]}
    nodes=[{'id':n,'board_uv':uv} for n,uv in coords.items()]
    edges=[{'id':k,'from':a,'to':b,'weight_min':w,'board_uv':[coords[a],coords[b]],'blocked':False}
           for k,a,b,w in [('ab','a','b',1),('bd','b','d',1),('ac','a','c',2),('cd','c','d',2)]]
    policy={'paths_per_shelter':16,'edge_capacity_model':{e['id']:capacity for e in edges},
            'node_capacity_model':{n:10 for n in coords},'snapped_node_capacity_groups':3,
            'shelter_capacity_groups':{'refuge':10},'assumptions':['synthetic unit-test model']}
    bundle={'roads':{'nodes':nodes,'edges':edges},'routing_policy':policy,'hazard':{'method':'test','stages':[[]]}}
    measured={'edges':edges,'simulation_stage':0,'population_demand':[{'id':g,'token_id':g,'node_id':'a'} for g in ['one','two']],
              'facilities':[{'id':'shelter','site_id':'refuge','node_id':'d','type':'shelter','active':True}]}
    return bundle,measured


def assert_valid(plan):
    assert all(0 <= load['reserved_groups'] <= load['capacity_groups']+1e-7 for load in plan['loads'])
    assert all(g['assigned_fraction']+g['unassigned_fraction'] == pytest.approx(1) for g in plan['groups'])
    assert sum(g['assigned_fraction'] for g in plan['groups']) == pytest.approx(plan['assigned_group_equivalents'])
    for g in plan['groups']:
        assert sum(r['fraction'] for r in g['routes']) == pytest.approx(g['assigned_fraction'])
        assert all(not set(r['mapped_edge_ids']) & set(plan['blocked_edge_ids']) for r in g['routes'])


def test_joint_routes_use_both_corridors_without_overloading_shortest():
    bundle,measured=diamond()
    plan=plan_population_routes(bundle,measured)
    assert plan['assigned_group_equivalents']==2
    assert {tuple(r['edge_ids']) for g in plan['groups'] for r in g['routes']} == {('ab','bd'),('ac','cd')}
    assert all(g['preferred_route_ignoring_crowding']['edge_ids']==['ab','bd'] for g in plan['groups'])
    assert not plan['candidate_paths_truncated']
    assert_valid(plan)


def test_fractional_capacity_cut_matches_known_max_flow_and_fair_share():
    bundle,measured=diamond(.6)
    plan=plan_population_routes(bundle,measured)
    assert plan['assigned_group_equivalents']==pytest.approx(1.2)
    assert [g['assigned_fraction'] for g in plan['groups']]==pytest.approx([.6,.6])
    assert_valid(plan)


def test_one_group_can_split_and_returns_percentages_without_headcount():
    bundle,measured=diamond(.6)
    measured['population_demand']=measured['population_demand'][:1]
    plan=plan_population_routes(bundle,measured)
    assert len(plan['groups'][0]['routes'])==2
    assert sorted(r['fraction'] for r in plan['groups'][0]['routes'])==pytest.approx([.5,.5])
    assert plan['population_unit']=='group_fraction_not_headcount'
    assert_valid(plan)


def test_flood_closure_and_exposed_facility_are_never_used():
    bundle,measured=diamond()
    measured['edges'][0]['blocked']=True
    plan=plan_population_routes(bundle,measured)
    assert plan['assigned_group_equivalents']==1
    assert_valid(plan)
    bundle['hazard']['site_stages']=[['refuge']]
    plan=plan_population_routes(bundle,measured)
    assert plan['assigned_group_equivalents']==0
    assert all(g['reason_code']=='no_active_unexposed_shelter' for g in plan['groups'])


def test_node_and_shelter_limits_and_stable_input_order():
    bundle,measured=diamond()
    bundle['routing_policy']['node_capacity_model']['d']=.8
    bundle['routing_policy']['shelter_capacity_groups']['refuge']=.7
    first=plan_population_routes(bundle,measured)
    assert first['assigned_group_equivalents']==pytest.approx(.7)
    measured['population_demand'].reverse();measured['edges'].reverse()
    assert plan_population_routes(bundle,measured)==first
    assert_valid(first)


def test_service_alternative_uses_only_unexposed_open_route():
    bundle,measured=diamond()
    measured['facilities'].append({'id':'food','site_id':'food-pad','node_id':'c','type':'food_shelter','active':True})
    plan=plan_population_routes(bundle,measured)
    assert any(a['via_service'] and a['via_service']['id']=='food' for a in plan['groups'][0]['alternatives'])
    bundle['hazard']['site_stages']=[['food-pad']]
    plan=plan_population_routes(bundle,measured)
    assert not any(a['via_service'] for a in plan['groups'][0]['alternatives'])


def test_candidate_limit_is_disclosed():
    bundle,measured=diamond()
    bundle['routing_policy']['paths_per_shelter']=1
    plan=plan_population_routes(bundle,measured)
    assert plan['candidate_paths_truncated']
    assert plan['assigned_group_equivalents']==1


def test_snapping_follows_curved_road_not_endpoint_chord():
    bundle,measured=diamond()
    bundle['routing_policy']['snap_tolerance_uv']=.02
    bundle['roads']['edges']= [{'id':'bend','from':'a','to':'d','weight_min':10,
                               'board_uv':[[0,0],[0,.5],[1,.5],[1,0]],'blocked':False}]
    snap=snap_to_road(bundle,[.4,.51])
    assert snap['board_uv']==pytest.approx([.4,.5])
    assert snap['fraction']==pytest.approx(.45)
    assert snap_to_road(bundle,[.5,0]) is None
    state={'tokens':{'g':{'id':'g','type':'person','road_snap':snap}}}
    edges,nodes,origins=split_at_groups(bundle,state,bundle['roads']['edges'])
    assert sum(e['weight_min'] for e in edges)==pytest.approx(10)
    assert edges[0]['board_uv']==[[0,0],[0,.5],[.4,.5]]
    assert nodes[origins['g']]['board_uv']==pytest.approx([.4,.5])
    assert all(e['parent_edge_id']=='bend' for e in edges)


def test_real_bundle_preserves_geography_and_has_audited_flood_closures():
    bundle=build()
    source=json.loads((ROOT/'scenarios/nepal_rasuwa_hot_v1/data/roads.json').read_text())
    assert bundle['roads']==source
    assert bundle['hazard']['method']=='copernicus_glofas_return_period_footprint'
    assert len(bundle['hazard']['stages'][1])==13
    assert all(f['quality_flagged_wet_pixels']==82 for f in bundle['hazard']['footprints'])
    assert bundle==WorldService.from_bundle(BUNDLE).scenario()


def start_world(path=None):
    world=WorldService.open_session(path,BUNDLE) if path else WorldService.from_bundle(BUNDLE)
    for kind,site,identity in [('disaster_start','start_pad','start'),('shelter','shelter_site_west','shelter')]:
        assert place(world,kind,site,identity)['accepted']
    return world


def test_free_road_placement_move_replay_and_persistent_decisions(tmp_path):
    path=tmp_path/'session.sqlite3'
    world=start_world(path)
    assert place(world,'person','people_southwest','group-a')['accepted']
    first=world.snapshot()['routing_decision']
    action={'action_id':'move','type':'move_token','token_id':'group-a','source':'manual',
            'board_uv':[.3130837,.30417035],'expected_world_version':world.snapshot()['world_version']}
    assert world.apply(action)['accepted']
    assert world.snapshot()['routing_decision']!=first
    expected=world.decision_log()
    assert expected[-1]['world_version']==4
    resumed=WorldService.open_session(path,BUNDLE)
    assert resumed.snapshot()==world.snapshot()
    assert resumed.decision_log()==expected
    packet=speech_payload(expected[-1])
    assert packet['decision_id']==expected[-1]['decision_id']
    assert packet['voice_status']=='not_connected'
    assert 'group equivalents' in packet['text']
    expected[0]['groups'].append({'bad':'mutation'})
    assert resumed.decision_log()!=expected


def test_rejected_move_no_decision_and_no_state_mutation():
    world=start_world()
    before=world.snapshot();history=world.decision_log()
    result=world.apply({'action_id':'off-map','type':'place_token','token_type':'person','token_id':'g',
                       'source':'manual','board_uv':[.95,.05],'expected_world_version':before['world_version']})
    assert not result['accepted'] and result['reason']=='too_far_from_mapped_road'
    assert world.snapshot()==before and world.decision_log()==history


def test_flood_bridge_cannot_magically_restore_inundated_road():
    world=start_world()
    result=place(world,'bridge','crossing_east')
    assert not result['accepted'] and result['reason']=='flood_closure_not_restorable'


def test_multiple_groups_can_share_a_road_origin_and_remove_cleanly():
    world=start_world()
    for identity in ['one','two']:
        assert place(world,'person','people_southwest',identity)['accepted']
    assert len(world.snapshot()['routing_decision']['groups'])==2
    result=world.apply({'action_id':'remove','type':'remove_token','token_id':'one','source':'manual',
                       'expected_world_version':world.snapshot()['world_version']})
    assert result['accepted']
    assert len(world.snapshot()['routing_decision']['groups'])==1
    assert_valid(world.snapshot()['routing_decision'])


def test_reasoning_disk_failure_does_not_record_uncommitted_decision(tmp_path,monkeypatch):
    from backend.world.session_store import SessionError
    world=start_world(tmp_path/'failed.sqlite3')
    before=world.snapshot();history=world.decision_log()
    def fail(payload):raise SessionError('test_disk_failure')
    monkeypatch.setattr(world._store,'save',fail)
    result=place(world,'person','people_southwest','new-group')
    assert result['reason']=='persistence_unavailable'
    assert world.snapshot()==before and world.decision_log()==history


def test_branch_rewind_retains_original_versioned_decisions(tmp_path):
    world=start_world(tmp_path/'branch.sqlite3')
    assert place(world,'person','people_southwest','one')['accepted']
    old=world.snapshot()['routing_decision'];saved=world.snapshot()['snapshot_id']
    assert place(world,'person','people_southwest','two')['accepted']
    result=world.apply({'action_id':'branch','type':'branch','branch_id':'counterfactual',
        'from_snapshot_id':saved,'source':'manual','expected_world_version':world.snapshot()['world_version']})
    assert result['accepted']
    current=world.snapshot()['routing_decision']
    assert len(current['groups'])==1 and current['branch_id']=='counterfactual'
    assert current['decision_id'] != old['decision_id']
    assert old in world.decision_log()
    assert WorldService.open_session(tmp_path/'branch.sqlite3',BUNDLE).decision_log()==world.decision_log()


def test_read_only_narration_receives_group_facts_without_mutation():
    from backend.narration.tools import WorldTools
    world=start_world();before=world.snapshot()
    facts=WorldTools(world).call('get_population_routing')
    assert facts==before['routing_decision']
    facts['groups'].append({'bad':'mutation'})
    assert world.snapshot()==before
