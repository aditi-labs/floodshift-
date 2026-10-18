"""
Disaster Prevention Planning Engine
Evacuation planning and resource pre-positioning using EXISTING tokens.

No new token types - reuses hospital, shelter, food_shelter, bridge, person
with prevention-focused meanings:
- hospital: Pre-position medical supplies
- shelter: Designate evacuation point
- food_shelter: Stock emergency supplies
- bridge: Reinforce crossing for evacuation route
- person: Mark population center needing evacuation plan
"""
from __future__ import annotations
import json
from pathlib import Path


def load_risk_data(bundle_path: Path | None = None) -> dict:
    """Load risk data for a scenario."""
    if bundle_path is None:
        bundle_path = Path(__file__).resolve().parents[2] / 'scenarios' / 'nepal_rasuwa_v1'
    risk_file = bundle_path / 'data' / 'risk.json'
    if risk_file.exists():
        return json.loads(risk_file.read_text())
    return {}


def get_risk_zones(bundle: dict, risk_data: dict) -> list[dict]:
    """
    Get pre-defined risk zones for projection overlay.
    Returns zones with risk levels, colors, and UV coordinates.
    """
    if not risk_data:
        return []

    # Use pre-defined risk zones from risk.json
    zones = risk_data.get('risk_zones', [])

    # Convert to API format
    result = []
    for zone in zones:
        result.append({
            'zone_id': zone.get('zone_id', ''),
            'board_uv_center': tuple(zone.get('center_uv', [0.5, 0.5])),
            'radius_uv': zone.get('radius_uv', 0.1),
            'risk_level': zone.get('risk_level', 'medium'),
            'flood_probability': zone.get('flood_probability', 0.5),
            'population_exposed': zone.get('population', 0),
            'color_hex': zone.get('color_hex', '#FFCC00')
        })

    return result


def calculate_vulnerability_score(bundle: dict, state: dict, risk_data: dict) -> float:
    """
    Calculate overall vulnerability (0=prepared, 1=unprepared).

    Factors:
    - How many high-risk populations are covered by shelters
    - Are evacuation routes reinforced (bridges)
    - Are medical supplies pre-positioned
    """
    if not risk_data:
        return 0.5

    # Get placed tokens
    tokens = state.get('tokens', {})
    if isinstance(tokens, list):
        tokens = {str(i): t for i, t in enumerate(tokens)}

    placed_types = {t.get('type') for t in tokens.values()}

    # Calculate preparation score
    score = 0.0
    max_score = 4.0

    if 'shelter' in placed_types:
        score += 1.0  # Evacuation point designated
    if 'hospital' in placed_types:
        score += 1.0  # Medical supplies pre-positioned
    if 'food_shelter' in placed_types:
        score += 1.0  # Emergency supplies stocked
    if 'bridge' in placed_types:
        score += 1.0  # Evacuation route reinforced

    preparation = score / max_score
    vulnerability = 1.0 - preparation

    return vulnerability


def calculate_lives_at_risk(bundle: dict, risk_data: dict, scenario: str = 'default') -> int:
    """Calculate total population in high-risk areas."""
    if not risk_data:
        return 0

    zones = risk_data.get('risk_zones', [])
    lives = 0

    for zone in zones:
        risk_level = zone.get('risk_level', 'low')
        if risk_level in ('critical', 'high'):
            lives += zone.get('population', 0)

    return lives


def calculate_prevention_effectiveness(
    bundle: dict,
    state: dict,
    risk_data: dict,
    scenario: str = 'default'
) -> dict:
    """
    Calculate how effective current token placements are for evacuation.
    """
    if not risk_data:
        return {
            'lives_protected': 0,
            'evacuation_routes_secured': 0,
            'shelters_ready': 0,
            'medical_coverage': 0,
            'effectiveness_score': 0.0
        }

    tokens = state.get('tokens', {})
    if isinstance(tokens, list):
        tokens = {str(i): t for i, t in enumerate(tokens)}

    effects = risk_data.get('token_prevention_effects', {})
    evac_metrics = risk_data.get('evacuation_metrics', {})
    baseline_casualties = evac_metrics.get('baseline_casualties_model', 45)

    lives_protected = 0
    routes_secured = 0
    shelters_ready = 0
    medical_coverage = 0

    for token in tokens.values():
        token_type = token.get('type', '')
        effect = effects.get(token_type, {})

        if token_type == 'shelter':
            shelters_ready += 1
            lives_protected += effect.get('capacity_people', 50)

        elif token_type == 'hospital':
            medical_coverage += 1
            reduction = effect.get('reduces_casualties_pct', 0.3)
            lives_protected += int(baseline_casualties * reduction)

        elif token_type == 'food_shelter':
            lives_protected += 20  # Supplies help 20 people survive longer

        elif token_type == 'bridge':
            routes_secured += 1
            lives_protected += 30  # Maintained route saves ~30 people

    # Cap at baseline
    lives_protected = min(lives_protected, baseline_casualties)
    effectiveness = lives_protected / max(baseline_casualties, 1)

    return {
        'lives_protected': lives_protected,
        'evacuation_routes_secured': routes_secured,
        'shelters_ready': shelters_ready,
        'medical_coverage': medical_coverage,
        'effectiveness_score': round(effectiveness, 2)
    }


def compare_outcomes(
    bundle: dict,
    state: dict,
    risk_data: dict,
    scenario: str = 'default'
) -> dict:
    """
    Compare outcomes WITH current preparation vs WITHOUT any preparation.
    """
    if not risk_data:
        return {}

    evac_metrics = risk_data.get('evacuation_metrics', {})
    baseline_time = evac_metrics.get('baseline_evacuation_time_minutes', 180)
    baseline_casualties = evac_metrics.get('baseline_casualties_model', 45)
    total_pop = evac_metrics.get('total_population', 500)

    effectiveness = calculate_prevention_effectiveness(bundle, state, risk_data, scenario)
    lives_saved = effectiveness['lives_protected']
    routes = effectiveness['evacuation_routes_secured']

    # Time reduction based on routes and shelters
    time_reduction = routes * 20 + effectiveness['shelters_ready'] * 15

    without = {
        'scenario_id': 'no_preparation',
        'severity': 'baseline',
        'casualties_model': baseline_casualties,
        'evacuation_time_minutes': baseline_time,
        'people_reached': total_pop - baseline_casualties
    }

    with_prep = {
        'scenario_id': 'with_preparation',
        'severity': 'mitigated',
        'casualties_model': max(0, baseline_casualties - lives_saved),
        'evacuation_time_minutes': max(60, baseline_time - time_reduction),
        'people_reached': min(total_pop, total_pop - baseline_casualties + lives_saved)
    }

    return {
        'scenario_id': scenario,
        'without_prevention': without,
        'with_prevention': with_prep,
        'lives_saved': lives_saved,
        'time_saved_minutes': time_reduction,
        'effectiveness_score': effectiveness['effectiveness_score']
    }


def best_prevention_suggestion(
    bundle: dict,
    state: dict,
    risk_data: dict,
    scenario: str = 'default'
) -> dict | None:
    """
    Suggest the best token placement for evacuation planning.
    Uses existing token types with prevention meanings.
    """
    if not risk_data:
        return None

    tokens = state.get('tokens', {})
    if isinstance(tokens, list):
        tokens = {str(i): t for i, t in enumerate(tokens)}

    placed_types = {t.get('type') for t in tokens.values()}
    zones = risk_data.get('risk_zones', [])
    effects = risk_data.get('token_prevention_effects', {})

    # Find highest risk zone without coverage
    critical_zones = [z for z in zones if z.get('risk_level') in ('critical', 'high')]
    critical_zones.sort(key=lambda z: -z.get('population', 0))

    suggestions = []

    # Priority 1: Shelter in critical zone if none placed
    if 'shelter' not in placed_types and critical_zones:
        zone = critical_zones[0]
        suggestions.append({
            'token_type': 'shelter',
            'site_id': f"evacuation_point_{zone['zone_id']}",
            'board_uv': zone.get('center_uv', [0.5, 0.5]),
            'reason_code': 'designate_evacuation_shelter',
            'reason_text': f"Designate evacuation shelter for {zone.get('population', 0)} people in {zone['zone_id']}",
            'lives_protected': effects.get('shelter', {}).get('capacity_people', 50),
            'priority': 1
        })

    # Priority 2: Bridge to secure evacuation route
    if 'bridge' not in placed_types:
        edge_vuln = risk_data.get('edge_vulnerability', {})
        critical_edges = [(k, v) for k, v in edge_vuln.items()
                         if v.get('is_evacuation_route') and v.get('vulnerability', 0) > 0.7]
        if critical_edges:
            edge_id, edge = max(critical_edges, key=lambda x: x[1].get('vulnerability', 0))
            # Find approximate position for this edge
            suggestions.append({
                'token_type': 'bridge',
                'site_id': f"reinforce_{edge_id}",
                'board_uv': [0.475, 0.5],  # Default crossing position
                'reason_code': 'reinforce_evacuation_route',
                'reason_text': f"Reinforce {edge_id} to maintain evacuation route",
                'lives_protected': 30,
                'priority': 2
            })

    # Priority 3: Hospital for medical coverage
    if 'hospital' not in placed_types:
        suggestions.append({
            'token_type': 'hospital',
            'site_id': 'medical_staging',
            'board_uv': [0.2, 0.25],
            'reason_code': 'pre_position_medical',
            'reason_text': "Pre-position medical supplies to reduce casualties by 30%",
            'lives_protected': 14,
            'priority': 3
        })

    # Priority 4: Food shelter for supplies
    if 'food_shelter' not in placed_types:
        suggestions.append({
            'token_type': 'food_shelter',
            'site_id': 'supply_depot',
            'board_uv': [0.2, 0.6],
            'reason_code': 'stock_emergency_supplies',
            'reason_text': "Stock emergency food and water for 7-day supply",
            'lives_protected': 20,
            'priority': 4
        })

    if not suggestions:
        return None

    # Return highest priority suggestion
    return min(suggestions, key=lambda s: s['priority'])
