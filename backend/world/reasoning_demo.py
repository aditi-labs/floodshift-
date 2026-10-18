"""Offline population-routing demo with persistent speech-ready decision history."""
import argparse
import json
from pathlib import Path
from time import perf_counter
from backend.world import WorldService
from backend.world.demo import place
from backend.narration.decision_narration import speech_payload

BUNDLE=Path(__file__).resolve().parents[2]/'scenarios/nepal_rasuwa_reasoning_v1'


def demo(session):
    world=WorldService.open_session(session,BUNDLE)
    timings=[]
    if world.snapshot()['world_version']==0:
        placements=[('disaster_start','start_pad','start'),('shelter','shelter_site_west','refuge-west'),
                    ('shelter','shelter_site_depot','refuge-depot'),
                    ('hospital','medical_site_west','medical-west'),('food_shelter','food_site_west','food-west'),
                    ('person','people_southwest','group-one'),('person','people_west','group-two'),
                    ('person','medical_site_west','group-three'),('person','people_east','group-four')]
        for kind,site,identity in placements:
            start=perf_counter();result=place(world,kind,site,identity)
            timings.append(round((perf_counter()-start)*1000,2))
            if not result['accepted']:raise RuntimeError(result['reason'])
        result=world.apply({'action_id':'move-group-two','type':'move_token','token_id':'group-two',
                           'source':'manual','board_uv':[.19210287,.60766786],
                           'expected_world_version':world.snapshot()['world_version']})
        if not result['accepted']:raise RuntimeError(result['reason'])
    decision=world.snapshot()['routing_decision']
    return {'snapshot':world.snapshot(),'decisions':world.decision_log(),'speech':speech_payload(decision),
            'accepted_action_latency_ms':timings,
            'summary':{'world_version':world.snapshot()['world_version'],
                       'assigned_group_equivalents':decision['assigned_group_equivalents'],
                       'unassigned_group_equivalents':decision['unassigned_group_equivalents'],
                       'groups':[{k:g[k] for k in ('group_id','assigned_fraction','unassigned_fraction','reason_code')} for g in decision['groups']]}}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();report=demo(args.session)
    if args.output:args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'summary':report['summary'],'accepted_action_latency_ms':report['accepted_action_latency_ms']},indent=2))
