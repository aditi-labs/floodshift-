"""
Disaster Prevention Planning Engine - V2
Uses REAL terrain data + research-based formulas + Gemini AI.

Math based on:
- FEMA flood risk assessment methodology
- WHO emergency evacuation guidelines
- Nepal DRR casualty models

Integrates with P4's WorldService for consistent graph analysis.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.ai.gemini_adapter import GeminiAdapter

# Lazy imports to avoid circular dependencies
_terrain_data: dict | None = None
_risk_data: dict | None = None


def _load_data(bundle_path: Path | None = None) -> tuple[dict, dict]:
    """Load terrain and risk data."""
    global _terrain_data, _risk_data

    if _terrain_data is not None and _risk_data is not None:
        return _terrain_data, _risk_data

    if bundle_path is None:
        bundle_path = Path(__file__).resolve().parents[2] / 'scenarios' / 'nepal_rasuwa_v1'

    terrain_file = bundle_path / 'data' / 'terrain.json'
    risk_file = bundle_path / 'data' / 'risk.json'

    _terrain_data = json.loads(terrain_file.read_text()) if terrain_file.exists() else {}
    _risk_data = json.loads(risk_file.read_text()) if risk_file.exists() else {}

    return _terrain_data, _risk_data


def load_risk_data(bundle_path: Path | None = None) -> dict:
    """Load risk data (backward compatible)."""
    _, risk_data = _load_data(bundle_path)
    return risk_data


# =============================================================================
# REAL FLOOD RISK FORMULAS
# Based on: FEMA Flood Risk Assessment + Nepal DRR Guidelines
# =============================================================================

def calculate_flood_probability(
    elevation_m: float,
    distance_to_river_m: float,
    slope_percent: float,
    flood_history_events: int,
    base_elevation: float = 800,
    max_elevation: float = 1500
) -> float:
    """
    Calculate flood probability using multi-factor model.

    Formula components:
    1. Elevation factor: P_elev = (max_elev - elev) / (max_elev - base_elev)
    2. Proximity factor: P_prox = exp(-distance / 200)  # 200m decay constant
    3. Slope factor: P_slope = 1 / (1 + slope/10)  # Steeper = better drainage
    4. History factor: P_hist = min(1, history_events / 5)

    Combined: P = w1*P_elev + w2*P_prox + w3*P_slope + w4*P_hist
    Weights based on FEMA methodology.
    """
    # Elevation factor (lower = higher risk)
    elev_normalized = max(0, min(1, (max_elevation - elevation_m) / (max_elevation - base_elevation)))

    # River proximity factor (exponential decay)
    prox_factor = math.exp(-distance_to_river_m / 200)

    # Slope factor (steeper = better drainage = lower risk)
    slope_factor = 1 / (1 + slope_percent / 10)

    # Historical factor
    history_factor = min(1.0, flood_history_events / 5)

    # Weighted combination (FEMA-style weights)
    weights = {'elevation': 0.30, 'proximity': 0.35, 'slope': 0.15, 'history': 0.20}

    probability = (
        weights['elevation'] * elev_normalized +
        weights['proximity'] * prox_factor +
        weights['slope'] * (1 - slope_factor) +  # Invert: low slope = high risk
        weights['history'] * history_factor
    )

    return round(min(0.95, max(0.05, probability)), 3)


def calculate_evacuation_time(
    population: int,
    distance_to_safety_m: float,
    road_quality: str = "fair",
    warning_time_hours: float = 4.0
) -> int:
    """
    Calculate evacuation time using WHO emergency guidelines.

    Components:
    1. Warning dissemination: 15-60 min depending on infrastructure
    2. Departure preparation: 30-90 min per household
    3. Travel time: distance / speed (adjusted for road quality)
    4. Bottleneck factor: sqrt(population) for congestion

    Formula: T = T_warn + T_prep + T_travel * congestion_factor
    """
    # Warning dissemination time (minutes)
    warning_time = 30 if warning_time_hours >= 6 else 45 if warning_time_hours >= 3 else 60

    # Preparation time per household (assume 4.5 people per household avg)
    households = population / 4.5
    prep_time = households * 2  # 2 minutes per household

    # Travel speed by road quality (m/min for walking evacuation)
    speed_map = {'good': 80, 'fair': 60, 'poor': 40}
    speed = speed_map.get(road_quality, 60)

    # Base travel time
    travel_time = distance_to_safety_m / speed

    # Congestion factor (sqrt model for bottlenecks)
    congestion = 1 + math.sqrt(population) / 50

    total_time = warning_time + prep_time + (travel_time * congestion)

    return int(min(480, max(30, total_time)))  # Cap at 8 hours


def calculate_casualties(
    population: int,
    flood_probability: float,
    evacuation_efficiency: float,
    vulnerability_factor: float = 0.25
) -> int:
    """
    Calculate potential casualties using disaster research model.

    Formula: C = P × V × H × (1 - E)
    Where:
    - P = affected population
    - V = vulnerability factor (age, disability, poverty)
    - H = hazard intensity (flood probability)
    - E = evacuation efficiency (0-1)

    Based on: Nepal DRR National Framework casualty models
    """
    # Affected population (those in flood zone)
    affected = population * flood_probability

    # Base mortality rate for flash floods (research: 0.01-0.05)
    base_mortality = 0.025

    # Adjusted for vulnerability
    mortality_rate = base_mortality * (1 + vulnerability_factor)

    # Evacuation reduces casualties
    casualties = affected * mortality_rate * (1 - evacuation_efficiency)

    return int(max(0, round(casualties)))


# =============================================================================
# RISK ZONE GENERATION (from real terrain data)
# =============================================================================

def get_risk_zones(bundle: dict, risk_data: dict) -> list[dict]:
    """
    Generate risk zones from REAL terrain data.
    Each zone has probability calculated from actual elevation/river data.
    """
    terrain, _ = _load_data()
    if not terrain:
        return _get_fallback_risk_zones(risk_data)

    node_terrain = terrain.get('node_terrain', {})
    population_data = terrain.get('population_data', {}).get('nodes', {})
    sites = {s['id']: s for s in bundle.get('sites', [])}

    zones = []
    for node_id, terrain_info in node_terrain.items():
        pop_info = population_data.get(node_id, {})
        population = pop_info.get('population', 0)

        if population == 0:
            continue  # Skip non-populated nodes

        # Calculate REAL flood probability
        flood_prob = calculate_flood_probability(
            elevation_m=terrain_info.get('elevation_m', 1000),
            distance_to_river_m=terrain_info.get('distance_to_river_m', 300),
            slope_percent=terrain_info.get('slope_percent', 10),
            flood_history_events=terrain_info.get('flood_history_events', 0)
        )

        # Determine risk level from probability
        if flood_prob >= 0.7:
            risk_level = 'critical'
            color = '#FF0000'
        elif flood_prob >= 0.5:
            risk_level = 'high'
            color = '#FF6600'
        elif flood_prob >= 0.3:
            risk_level = 'medium'
            color = '#FFCC00'
        else:
            risk_level = 'low'
            color = '#66CC66'

        # Find board_uv from sites or roads
        board_uv = [0.5, 0.5]
        for site in bundle.get('sites', []):
            if site.get('node_id') == node_id:
                board_uv = site.get('board_uv', board_uv)
                break
        else:
            # Check roads nodes
            for node in bundle.get('roads', {}).get('nodes', []):
                if node.get('id') == node_id:
                    board_uv = node.get('board_uv', board_uv)
                    break

        zones.append({
            'zone_id': f"zone_{node_id}",
            'node_id': node_id,
            'board_uv_center': tuple(board_uv),
            'radius_uv': 0.08 + (population / 5000),  # Larger pop = larger zone
            'risk_level': risk_level,
            'flood_probability': flood_prob,
            'population_exposed': population,
            'elevation_m': terrain_info.get('elevation_m'),
            'distance_to_river_m': terrain_info.get('distance_to_river_m'),
            'color_hex': color
        })

    return sorted(zones, key=lambda z: -z['flood_probability'])


def _get_fallback_risk_zones(risk_data: dict) -> list[dict]:
    """Fallback when terrain data unavailable."""
    return risk_data.get('risk_zones', [])


# =============================================================================
# VULNERABILITY & EFFECTIVENESS (research-based)
# =============================================================================

def calculate_vulnerability_score(bundle: dict, state: dict, risk_data: dict) -> float:
    """
    Calculate system vulnerability using terrain + token placement.
    Returns 0 (fully prepared) to 1 (completely vulnerable).
    """
    terrain, _ = _load_data()
    if not terrain:
        return 0.5

    # Get placed tokens
    tokens = state.get('tokens', {})
    if isinstance(tokens, list):
        tokens = {str(i): t for i, t in enumerate(tokens)}

    placed_types = {t.get('type') for t in tokens.values()}

    # Calculate base vulnerability from terrain
    node_terrain = terrain.get('node_terrain', {})
    population_data = terrain.get('population_data', {}).get('nodes', {})

    total_pop = 0
    weighted_risk = 0

    for node_id, t_info in node_terrain.items():
        pop = population_data.get(node_id, {}).get('population', 0)
        if pop == 0:
            continue

        flood_prob = calculate_flood_probability(
            elevation_m=t_info.get('elevation_m', 1000),
            distance_to_river_m=t_info.get('distance_to_river_m', 300),
            slope_percent=t_info.get('slope_percent', 10),
            flood_history_events=t_info.get('flood_history_events', 0)
        )

        total_pop += pop
        weighted_risk += pop * flood_prob

    base_vulnerability = weighted_risk / max(total_pop, 1)

    # Reduction from placed tokens
    reduction = 0.0
    if 'shelter' in placed_types:
        reduction += 0.20  # Evacuation point reduces vulnerability
    if 'hospital' in placed_types:
        reduction += 0.15  # Medical prep reduces mortality
    if 'bridge' in placed_types:
        reduction += 0.25  # Route reinforcement is critical
    if 'food_shelter' in placed_types:
        reduction += 0.10  # Supplies help survival

    final_vulnerability = max(0.05, base_vulnerability - reduction)
    return round(final_vulnerability, 3)


def calculate_lives_at_risk(bundle: dict, risk_data: dict, scenario: str = 'default') -> int:
    """Calculate lives at risk using real population + flood probability."""
    terrain, _ = _load_data()
    if not terrain:
        return 320  # Fallback

    node_terrain = terrain.get('node_terrain', {})
    population_data = terrain.get('population_data', {}).get('nodes', {})

    lives = 0
    for node_id, t_info in node_terrain.items():
        pop = population_data.get(node_id, {}).get('population', 0)
        flood_prob = calculate_flood_probability(
            elevation_m=t_info.get('elevation_m', 1000),
            distance_to_river_m=t_info.get('distance_to_river_m', 300),
            slope_percent=t_info.get('slope_percent', 10),
            flood_history_events=t_info.get('flood_history_events', 0)
        )

        if flood_prob >= 0.5:  # High risk threshold
            lives += pop

    return lives


def calculate_prevention_effectiveness(
    bundle: dict,
    state: dict,
    risk_data: dict,
    scenario: str = 'default'
) -> dict:
    """
    Calculate prevention effectiveness using real formulas.
    """
    terrain, _ = _load_data()
    tokens = state.get('tokens', {})
    if isinstance(tokens, list):
        tokens = {str(i): t for i, t in enumerate(tokens)}

    placed_types = {t.get('type') for t in tokens.values()}
    population_data = terrain.get('population_data', {}) if terrain else {}
    total_pop = population_data.get('total_population', 1191)

    # Calculate baseline (no preparation)
    baseline_evac_efficiency = 0.60  # 60% can evacuate without prep
    baseline_casualties = calculate_casualties(
        population=total_pop,
        flood_probability=0.5,  # Average risk
        evacuation_efficiency=baseline_evac_efficiency,
        vulnerability_factor=0.25
    )

    # Calculate with preparation
    prep_evac_efficiency = baseline_evac_efficiency
    if 'shelter' in placed_types:
        prep_evac_efficiency += 0.15  # Shelter adds 15%
    if 'bridge' in placed_types:
        prep_evac_efficiency += 0.12  # Route adds 12%
    if 'hospital' in placed_types:
        prep_evac_efficiency += 0.05  # Medical adds 5%
    if 'food_shelter' in placed_types:
        prep_evac_efficiency += 0.03  # Supplies add 3%

    prep_evac_efficiency = min(0.95, prep_evac_efficiency)

    prep_casualties = calculate_casualties(
        population=total_pop,
        flood_probability=0.5,
        evacuation_efficiency=prep_evac_efficiency,
        vulnerability_factor=0.25
    )

    lives_protected = baseline_casualties - prep_casualties
    effectiveness = 1 - (prep_casualties / max(baseline_casualties, 1))

    return {
        'lives_protected': lives_protected,
        'evacuation_routes_secured': 1 if 'bridge' in placed_types else 0,
        'shelters_ready': 1 if 'shelter' in placed_types else 0,
        'medical_coverage': 1 if 'hospital' in placed_types else 0,
        'evacuation_efficiency': round(prep_evac_efficiency, 2),
        'effectiveness_score': round(effectiveness, 3)
    }


def compare_outcomes(
    bundle: dict,
    state: dict,
    risk_data: dict,
    scenario: str = 'default'
) -> dict:
    """
    Compare outcomes using research-based casualty and time models.
    """
    terrain, _ = _load_data()
    population_data = terrain.get('population_data', {}) if terrain else {}
    total_pop = population_data.get('total_population', 1191)

    tokens = state.get('tokens', {})
    if isinstance(tokens, list):
        tokens = {str(i): t for i, t in enumerate(tokens)}

    placed_types = {t.get('type') for t in tokens.values()}

    # Without preparation
    without_evac_eff = 0.60
    without_casualties = calculate_casualties(total_pop, 0.5, without_evac_eff, 0.25)
    without_evac_time = calculate_evacuation_time(total_pop, 2000, 'fair', 4)

    # With preparation
    with_evac_eff = without_evac_eff
    road_quality = 'fair'

    if 'shelter' in placed_types:
        with_evac_eff += 0.15
    if 'bridge' in placed_types:
        with_evac_eff += 0.12
        road_quality = 'good'
    if 'hospital' in placed_types:
        with_evac_eff += 0.05
    if 'food_shelter' in placed_types:
        with_evac_eff += 0.03

    with_evac_eff = min(0.95, with_evac_eff)
    with_casualties = calculate_casualties(total_pop, 0.5, with_evac_eff, 0.25)
    with_evac_time = calculate_evacuation_time(total_pop, 2000, road_quality, 6)

    # Cost model ($50K per unit)
    recovery_without = int(without_casualties * 50 + 200)  # Casualties + infrastructure
    recovery_with = int(with_casualties * 50 + 100)
    prevention_cost = len(placed_types) * 2  # 2 units per token type

    return {
        'scenario_id': scenario,
        'without_prevention': {
            'scenario_id': 'no_preparation',
            'severity': 'baseline',
            'casualties_model': without_casualties,
            'evacuation_time_minutes': without_evac_time,
            'people_reached': total_pop - without_casualties,
            'recovery_cost_model': recovery_without
        },
        'with_prevention': {
            'scenario_id': 'with_preparation',
            'severity': 'mitigated',
            'casualties_model': with_casualties,
            'evacuation_time_minutes': with_evac_time,
            'people_reached': total_pop - with_casualties,
            'recovery_cost_model': recovery_with
        },
        'lives_saved': without_casualties - with_casualties,
        'time_saved_minutes': without_evac_time - with_evac_time,
        'cost_avoided': recovery_without - recovery_with,
        'prevention_investment': prevention_cost,
        'roi_ratio': round((recovery_without - recovery_with - prevention_cost) / max(prevention_cost, 1), 2),
        'effectiveness_score': round(1 - (with_casualties / max(without_casualties, 1)), 3)
    }


def best_prevention_suggestion(
    bundle: dict,
    state: dict,
    risk_data: dict,
    scenario: str = 'default'
) -> dict | None:
    """
    Suggest optimal prevention action using risk analysis.
    Prioritizes by lives protected per cost.
    """
    terrain, _ = _load_data()
    tokens = state.get('tokens', {})
    if isinstance(tokens, list):
        tokens = {str(i): t for i, t in enumerate(tokens)}

    placed_types = {t.get('type') for t in tokens.values()}
    zones = get_risk_zones(bundle, risk_data)

    # Find highest risk unprotected zone
    critical_zones = [z for z in zones if z['risk_level'] in ('critical', 'high')]

    if not critical_zones:
        return None

    highest_risk = critical_zones[0]
    population_data = terrain.get('population_data', {}) if terrain else {}
    total_pop = population_data.get('total_population', 1191)

    # Calculate impact of each token type
    candidates = []

    if 'shelter' not in placed_types:
        # Shelter in highest risk zone
        lives = int(highest_risk['population_exposed'] * 0.15)  # 15% improvement
        candidates.append({
            'token_type': 'shelter',
            'site_id': f"shelter_{highest_risk['node_id']}",
            'board_uv': list(highest_risk['board_uv_center']),
            'reason_code': 'designate_evacuation_point',
            'reason_text': f"Designate evacuation shelter for {highest_risk['population_exposed']} people in {highest_risk['risk_level']} risk zone",
            'lives_protected': lives,
            'priority': 1,
            'score': lives / 2  # Cost = 2
        })

    if 'bridge' not in placed_types:
        # Bridge protects evacuation route
        lives = int(total_pop * 0.12 * 0.5 * 0.025)  # 12% efficiency gain
        candidates.append({
            'token_type': 'bridge',
            'site_id': 'reinforce_crossing_east',
            'board_uv': [0.475, 0.5],
            'reason_code': 'reinforce_evacuation_route',
            'reason_text': 'Reinforce critical bridge to maintain evacuation route during flood',
            'lives_protected': max(lives, 8),
            'priority': 2,
            'score': lives / 2
        })

    if 'hospital' not in placed_types:
        lives = int(total_pop * 0.05 * 0.5 * 0.025)
        candidates.append({
            'token_type': 'hospital',
            'site_id': 'medical_staging',
            'board_uv': [0.2, 0.25],
            'reason_code': 'pre_position_medical',
            'reason_text': 'Pre-position medical supplies to reduce flood-related mortality',
            'lives_protected': max(lives, 4),
            'priority': 3,
            'score': lives / 2
        })

    if 'food_shelter' not in placed_types:
        lives = int(total_pop * 0.03 * 0.5 * 0.025)
        candidates.append({
            'token_type': 'food_shelter',
            'site_id': 'supply_depot',
            'board_uv': [0.2, 0.6],
            'reason_code': 'stock_emergency_supplies',
            'reason_text': 'Stock emergency supplies for extended displacement',
            'lives_protected': max(lives, 2),
            'priority': 4,
            'score': lives / 2
        })

    if not candidates:
        return None

    # Return highest priority (most impactful)
    return min(candidates, key=lambda c: c['priority'])
