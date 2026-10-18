"""
Disaster Prevention Planning Engine - V2

Per-bundle data in scenarios/<id>/data/{terrain,risk}.json:
- nepal_rasuwa_hot_v1 / _reasoning_v1: measured open data (Copernicus GLO-30 DEM,
  WorldPop 2020, Copernicus GloFAS RP10/RP100, OSM waterways), built by
  scripts/geodata/build_risk_data.py and scored with an educational exposure index.
- nepal_rasuwa_v1: illustrative values for the schematic fixture (not measured).

Weights, evacuation times, mortality and casualty figures below are authored teaching
assumptions, not FEMA/WHO/Nepal DRR methods or calibrated predictions.

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
_REPO = Path(__file__).resolve().parents[2]
_DEFAULT_SCENARIO = 'nepal_rasuwa_v1'
_cache: dict[str, tuple[dict, dict]] = {}


def _load_data(bundle: dict | Path | None = None) -> tuple[dict, dict]:
    """Terrain and risk data for the given bundle (dict), bundle directory, or the schematic default."""
    if isinstance(bundle, dict):
        root = _REPO / 'scenarios' / bundle.get('scenario_id', _DEFAULT_SCENARIO)
    elif bundle is not None:
        root = Path(bundle)
    else:
        root = _REPO / 'scenarios' / _DEFAULT_SCENARIO
    key = str(root)
    if key not in _cache:
        files = [root / 'data' / name for name in ('terrain.json', 'risk.json')]
        _cache[key] = tuple(json.loads(f.read_text(encoding="utf-8")) if f.exists() else {} for f in files)
    return _cache[key]


def supports_bundle(bundle: dict) -> bool:
    """Terrain/risk data is keyed by nepal_rasuwa_v1 node ids and drawn at their UVs.

    Applying it to another map (e.g. the HOT-derived bundle) would stack every zone at
    the board centre and attach invented population counts to the wrong places.
    """
    nodes = {n.get('id') for n in bundle.get('roads', {}).get('nodes', [])}
    if not nodes:
        return True  # no geometry to contradict (mock world)
    terrain, _ = _load_data(bundle)
    return bool(terrain.get('node_terrain')) and set(terrain['node_terrain']) <= nodes


def provenance(bundle: dict | None = None) -> dict:
    """Where the risk inputs come from, for display next to any risk overlay."""
    terrain, _ = _load_data(bundle)
    return {k: terrain.get(k) for k in ('data_mode', 'region', 'data_sources', 'risk_index', 'limitations')}


def flood_scenarios(bundle: dict | None = None) -> dict:
    terrain, _ = _load_data(bundle)
    return terrain.get('flood_scenarios', {})


def _real_site(bundle: dict, kind: str, near_uv: list[float]) -> tuple[str, list[float]] | None:
    """Nearest approved site of ``kind`` so suggestions name pads the reducer accepts."""
    candidates = [s for s in bundle.get('sites', []) if s.get('kind') == kind]
    if not candidates:
        return None
    site = min(candidates, key=lambda s: (s['board_uv'][0]-near_uv[0])**2 + (s['board_uv'][1]-near_uv[1])**2)
    return site['id'], list(site['board_uv'])


def load_risk_data(bundle: dict | Path | None = None) -> dict:
    """Load risk data (backward compatible)."""
    _, risk_data = _load_data(bundle)
    return risk_data


def exposure_index(t_info: dict) -> float:
    """Educational index over measured inputs (see terrain.json risk_index); not a probability."""
    flood = 1.0 if t_info.get('flood_depth_rp10_m') else 0.7 if t_info.get('flood_depth_rp100_m') else 0.0
    height = max(0.0, 1 - t_info.get('height_above_river_m', 30) / 30)
    proximity = math.exp(-t_info.get('distance_to_river_m', 300) / 200)
    return round(min(0.95, max(0.05, 0.5 * flood + 0.3 * height + 0.2 * proximity)), 3)


def node_risk(t_info: dict) -> float:
    """Measured bundles use exposure_index; the schematic fixture keeps its illustrative formula."""
    if 'flood_depth_rp10_m' in t_info:
        return exposure_index(t_info)
    return calculate_flood_probability(
        elevation_m=t_info.get('elevation_m', 1000),
        distance_to_river_m=t_info.get('distance_to_river_m', 300),
        slope_percent=t_info.get('slope_percent', 10),
        flood_history_events=t_info.get('flood_history_events') or 0)


# =============================================================================
# ILLUSTRATIVE FORMULAS (schematic fixture; authored weights)
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
    Weights are authored for the schematic teaching fixture.
    """
    # Elevation factor (lower = higher risk)
    elev_normalized = max(0, min(1, (max_elevation - elevation_m) / (max_elevation - base_elevation)))

    # River proximity factor (exponential decay)
    prox_factor = math.exp(-distance_to_river_m / 200)

    # Slope factor (steeper = better drainage = lower risk)
    slope_factor = 1 / (1 + slope_percent / 10)

    # Historical factor
    history_factor = min(1.0, flood_history_events / 5)

    # Weighted combination (authored weights)
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
    Illustrative evacuation-time model (authored assumptions, not WHO guidance).

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
    Illustrative casualty model (authored assumptions; no measured mortality data).

    Formula: C = P × V × H × (1 - E)
    Where:
    - P = affected population
    - V = vulnerability factor (age, disability, poverty)
    - H = hazard intensity (flood probability)
    - E = evacuation efficiency (0-1)

    """
    # Affected population (those in flood zone)
    affected = population * flood_probability

    # Authored mortality rate for the teaching model
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
    Generate risk zones from the bundle's terrain data.
    Each zone has probability calculated from actual elevation/river data.
    """
    terrain, _ = _load_data(bundle)
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

        flood_prob = node_risk(terrain_info)

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


def calculate_protected_zones(
    base_zones: list[dict],
    placed_tokens: list[dict],
    bundle: dict
) -> list[dict]:
    """
    Calculate updated risk zones based on placed token protection.

    Protection effects (probability reduction):
    - shelter: -0.20 to nearby zones (evacuation point exists)
    - hospital: -0.15 to nearby zones (medical access)
    - food_shelter: -0.10 to nearby zones (supplies available)
    - bridge: -0.18 to connected zones (evacuation route)

    Returns updated zones with new probabilities, colors, and is_protected flag.
    """
    if not base_zones:
        return []

    # Build node -> tokens mapping
    node_protection = {}  # node_id -> total protection reduction
    sites = {s.get('id'): s for s in bundle.get('sites', [])}

    # Calculate protection from each placed token
    for token in placed_tokens:
        token_type = token.get('type')
        site_id = token.get('site_id')

        # Find which node this token affects
        affected_nodes = []

        if site_id and site_id in sites:
            site = sites[site_id]
            node_id = site.get('node_id')
            if node_id:
                affected_nodes.append(node_id)

        # Also check token board_uv proximity to zones
        token_uv = token.get('board_uv', [0.5, 0.5])
        if isinstance(token_uv, (list, tuple)) and len(token_uv) >= 2:
            for zone in base_zones:
                zone_uv = zone.get('board_uv_center', (0.5, 0.5))
                # Calculate distance in UV space
                dist = ((token_uv[0] - zone_uv[0])**2 + (token_uv[1] - zone_uv[1])**2)**0.5
                # Token protects zones within 0.15 UV distance
                if dist < 0.15:
                    node_id = zone.get('node_id')
                    if node_id and node_id not in affected_nodes:
                        affected_nodes.append(node_id)

        # Apply protection based on token type
        protection = 0.0
        if token_type == 'shelter':
            protection = 0.20
        elif token_type == 'hospital':
            protection = 0.15
        elif token_type == 'food_shelter':
            protection = 0.10
        elif token_type == 'bridge':
            protection = 0.18

        for node_id in affected_nodes:
            node_protection[node_id] = node_protection.get(node_id, 0) + protection

    # Update zones with protection
    updated_zones = []
    for zone in base_zones:
        node_id = zone.get('node_id', '')
        base_prob = zone.get('flood_probability', 0.5)
        protection = min(0.5, node_protection.get(node_id, 0))  # Cap at 50% reduction

        new_prob = max(0.05, base_prob - protection)
        is_protected = protection > 0

        # Determine new risk level and color
        if new_prob >= 0.7:
            risk_level = 'critical'
            color = '#FF0000'
        elif new_prob >= 0.5:
            risk_level = 'high'
            color = '#FF6600'
        elif new_prob >= 0.3:
            risk_level = 'medium'
            color = '#FFCC00'
        else:
            risk_level = 'low'
            color = '#66CC66'

        updated_zones.append({
            **zone,
            'flood_probability': round(new_prob, 3),
            'base_probability': base_prob,
            'risk_level': risk_level,
            'color': color,
            'color_hex': color,  # Backward compatibility
            'is_protected': is_protected
        })

    return sorted(updated_zones, key=lambda z: -z['flood_probability'])


def get_risk_zones_for_snapshot(bundle: dict, state: dict, mode: str = 'relief') -> list[dict]:
    """
    Get risk zones for WorldSnapshot, accounting for placed tokens.
    Works in both prevention and relief modes.
    """
    terrain, risk_data = _load_data(bundle)
    if not supports_bundle(bundle):
        return []

    # Get base zones
    base_zones = get_risk_zones(bundle, risk_data)

    # Get placed tokens from state
    tokens = state.get('tokens', [])
    if isinstance(tokens, dict):
        tokens = list(tokens.values())

    # Filter to only accepted tokens
    placed_tokens = [t for t in tokens if t.get('status') == 'accepted']

    # Calculate protection
    if placed_tokens:
        return calculate_protected_zones(base_zones, placed_tokens, bundle)

    # Add default fields if no tokens placed
    for zone in base_zones:
        zone['base_probability'] = zone.get('flood_probability', 0.5)
        zone['color'] = zone.get('color_hex', '#FFCC00')
        zone['is_protected'] = False

    return base_zones


# =============================================================================
# VULNERABILITY & EFFECTIVENESS (illustrative model)
# =============================================================================

def calculate_vulnerability_score(bundle: dict, state: dict, risk_data: dict) -> float:
    """
    Calculate system vulnerability using terrain + token placement.
    Returns 0 (fully prepared) to 1 (completely vulnerable).
    """
    terrain, _ = _load_data(bundle)
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

        flood_prob = node_risk(t_info)

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
    terrain, _ = _load_data(bundle)
    if not terrain:
        return 320  # Fallback

    node_terrain = terrain.get('node_terrain', {})
    population_data = terrain.get('population_data', {}).get('nodes', {})

    lives = 0
    for node_id, t_info in node_terrain.items():
        pop = population_data.get(node_id, {}).get('population', 0)
        flood_prob = node_risk(t_info)

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
    terrain, _ = _load_data(bundle)
    tokens = state.get('tokens', {})
    if isinstance(tokens, list):
        tokens = {str(i): t for i, t in enumerate(tokens)}

    placed_types = {t.get('type') for t in tokens.values()}
    population_data = terrain.get('population_data', {}) if terrain else {}
    total_pop = population_data.get('total_population', 0)

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
    terrain, _ = _load_data(bundle)
    population_data = terrain.get('population_data', {}) if terrain else {}
    total_pop = population_data.get('total_population', 0)

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
    terrain, _ = _load_data(bundle)
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
    total_pop = population_data.get('total_population', 0)

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

    # Point each suggestion at a real approved pad when the bundle has one.
    kinds = {'shelter': 'shelter_site', 'bridge': 'bridge_crossing',
             'hospital': 'medical_site', 'food_shelter': 'food_site'}
    for candidate in candidates:
        real = _real_site(bundle, kinds[candidate['token_type']], candidate['board_uv'])
        if real:
            candidate['site_id'], candidate['board_uv'] = real

    # Return highest priority (most impactful)
    return min(candidates, key=lambda c: c['priority'])
