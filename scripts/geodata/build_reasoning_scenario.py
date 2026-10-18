"""Derive an opt-in reasoning demo without inventing any road connections."""
from copy import deepcopy
import json
from pathlib import Path
from backend.world.scenarios import load_bundle, validate_bundle

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'scenarios/nepal_rasuwa_hot_v1'
TARGET = ROOT / 'scenarios/nepal_rasuwa_reasoning_v1/data'


def build():
    bundle = deepcopy(load_bundle(SOURCE))
    bundle['scenario_id'] = 'nepal_rasuwa_reasoning_v1'
    bundle['token_inventory'].update(person=4, shelter=2)
    bundle['budget_model'] = 8
    nodes = {n['id']: n for n in bundle['roads']['nodes']}
    for site in bundle['sites']:
        if site['kind'] == 'population_node':
            site['demand'] = dict(households_model=0, people_model=0, need_food=0, need_medical=0, need_refuge=0)
            site['tolerance_uv'] = .0125
        if site['kind'] == 'shelter_site':
            site['capacity_model'] = 8
    for identity, node_id, kind in [
        ('people_junction', '336911.680:3116545.792', 'population_node'),
        ('people_southwest', '336763.019:3116549.789', 'population_node'),
        ('shelter_site_depot', '336740.745:3116467.408', 'shelter_site')]:
        site = {'id': identity, 'kind': kind, 'node_id': node_id,
                'board_uv': nodes[node_id]['board_uv'], 'tolerance_uv': .0125 if kind == 'population_node' else .018,
                'approved': True, 'hazard_exposed': False, 'resource_cost': 0 if kind == 'population_node' else 1,
                'origin': 'scenario_synthetic', 'position_origin': 'mapped_OSM_road_vertex',
                'approval_basis': 'educational placement only; not verified site suitability'}
        if kind == 'population_node':
            site['demand'] = dict(households_model=0, people_model=0, need_food=0, need_medical=0, need_refuge=0)
        else:
            site['capacity_model'] = 8
        bundle['sites'].append(site)
    bundle['routing_policy'] = {
        'paths_per_shelter': 16, 'snap_tolerance_uv': .015, 'snapped_node_capacity_groups': 3,
        'shelter_capacity_groups': {'shelter_site_west': 2, 'shelter_site_depot': 2},
        'edge_capacity_model': {e['id']: .5 if e['id'].startswith('crossing_') else 2 for e in bundle['roads']['edges']},
        'node_capacity_model': {n: 3 for n in nodes},
        'assumptions': [
            'Four population pieces with unspecified headcounts; each represents one normalized group.',
            'Groups can split into fractions; tokens snap to the nearest mapped road within 0.015 board UV.',
            'Shelter evacuation is separate from food/medical/refuge service allocation metrics.',
            'Road capacity 2 group equivalents, bridge capacity 0.5, junction capacity 3 per planning wave.',
            'Capacities, demand, walking costs and shelter suitability are authored educational assumptions, not measured facts.',
            'Flood closures come from Copernicus RP10/RP100 footprints; 82/90 wet pixels are quality-flagged, and no-data is not verified dry.',
            'Shared edge capacity covers both directions; no departure-time simulation or real safety guarantee.',
            'Unassigned groups remain at their origins; waiting crowding is reported separately.',
            'Joint fractional linear programming among up to 16 shortest paths per shelter; omitted paths are disclosed.']}
    bundle['hazard'] = json.loads((TARGET/'flood/hazard_analysis.json').read_text())
    bundle['source_manifest']['reasoning_extension'] = {
        'source_bundle': 'nepal_rasuwa_hot_v1', 'road_geometry_unchanged': True,
        'extra_pads': 'synthetic sites at existing mapped road vertices',
        'capacity_origin': 'scenario_synthetic', 'flood_origin': 'Copernicus_CEMS_GloFAS_v2.1.2_quality_flagged',
        'planner': 'fractional-group-lp-v1'}
    validate_bundle(bundle)
    return bundle


def main():
    bundle = build()
    TARGET.mkdir(parents=True, exist_ok=True)
    for key in ('roads', 'sites', 'hazard', 'source_manifest'):
        (TARGET / (key+'.json')).write_text(json.dumps(bundle[key], indent=2)+'\n')
    scenario = {k:v for k,v in bundle.items() if k not in {'roads','sites','hazard','source_manifest'}}
    (TARGET / 'scenario.json').write_text(json.dumps(scenario, indent=2)+'\n')
    (TARGET / 'points.json').write_text(json.dumps(bundle['roads']['nodes'], indent=2)+'\n')


if __name__ == '__main__':
    main()
