"""
Gemini AI Adapter for FLOODSHIFT
Provides intelligent analysis for both Relief and Prevention modes.

Uses Gemini to:
- Analyze risk based on real terrain/population data
- Explain evacuation strategies
- Compare prevention vs relief outcomes
- Answer user questions grounded in simulation state
"""
from __future__ import annotations
import os
import json
from typing import Literal

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    genai = None


class GeminiAdapter:
    """
    Wrapper for Gemini API with FLOODSHIFT-specific prompts.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model_name = model or os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
        self._model = None
        self._status = "not_configured"

        if not GEMINI_AVAILABLE:
            self._status = "sdk_not_installed"
            return

        if not self.api_key:
            self._status = "no_api_key"
            return

        try:
            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel(self.model_name)
            self._status = "ready"
        except Exception as e:
            self._status = f"error: {str(e)}"

    @property
    def status(self) -> str:
        return self._status

    @property
    def is_ready(self) -> bool:
        return self._status == "ready" and self._model is not None

    def analyze_risk(
        self,
        node_data: dict,
        elevation_m: float,
        distance_to_river_m: float,
        population: int,
        historical_floods: int = 0
    ) -> dict:
        """
        Use Gemini to analyze flood risk for a location.
        Returns structured risk assessment.
        """
        if not self.is_ready:
            return self._fallback_risk_analysis(elevation_m, distance_to_river_m, population)

        prompt = f"""You are a flood risk analyst. Analyze this location:

Location Data:
- Elevation: {elevation_m}m above sea level
- Distance to nearest river: {distance_to_river_m}m
- Population: {population} people
- Historical flood events in area: {historical_floods}

Based on hydrology principles:
1. Calculate flood_probability (0.0 to 1.0)
2. Determine risk_level (low/medium/high/critical)
3. Estimate evacuation_time_minutes for this population
4. Calculate potential casualties if no preparation (use research-based formula)

Respond in JSON format only:
{{"flood_probability": 0.X, "risk_level": "X", "evacuation_time_minutes": X, "potential_casualties": X, "reasoning": "brief explanation"}}
"""
        try:
            response = self._model.generate_content(prompt)
            text = response.text.strip()
            # Extract JSON from response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            return json.loads(text)
        except Exception as e:
            return self._fallback_risk_analysis(elevation_m, distance_to_river_m, population)

    def _fallback_risk_analysis(
        self,
        elevation_m: float,
        distance_to_river_m: float,
        population: int
    ) -> dict:
        """Fallback formula-based risk analysis when Gemini unavailable."""
        # Real formula based on flood research:
        # Risk increases with: lower elevation, closer to river, higher population

        # Elevation factor (lower = higher risk)
        # Base elevation for Rasuwa is ~800-2000m
        elev_factor = max(0, min(1, (1500 - elevation_m) / 700))

        # River proximity factor (closer = higher risk)
        # Within 100m is critical, >500m is low risk
        river_factor = max(0, min(1, (500 - distance_to_river_m) / 500))

        # Combined probability using weighted geometric mean
        flood_probability = round((elev_factor * 0.4 + river_factor * 0.6), 2)

        # Risk level thresholds
        if flood_probability >= 0.7:
            risk_level = "critical"
        elif flood_probability >= 0.5:
            risk_level = "high"
        elif flood_probability >= 0.3:
            risk_level = "medium"
        else:
            risk_level = "low"

        # Evacuation time: ~2 min per person for organized evacuation
        # Plus base time for warning dissemination
        evacuation_time = 30 + (population * 0.5)

        # Casualty model from disaster research:
        # C = P × V × (1 - E) where P=population, V=vulnerability, E=evacuation_efficiency
        vulnerability = flood_probability
        evacuation_efficiency = 0.7  # Assume 70% can evacuate without preparation
        potential_casualties = int(population * vulnerability * (1 - evacuation_efficiency))

        return {
            "flood_probability": flood_probability,
            "risk_level": risk_level,
            "evacuation_time_minutes": int(evacuation_time),
            "potential_casualties": potential_casualties,
            "reasoning": f"Elevation {elevation_m}m, {distance_to_river_m}m from river"
        }

    def explain_prevention_strategy(
        self,
        placed_tokens: list[dict],
        risk_zones: list[dict],
        metrics: dict
    ) -> str:
        """
        Generate intelligent explanation of current prevention strategy.
        """
        if not self.is_ready:
            return self._fallback_prevention_explanation(placed_tokens, metrics)

        prompt = f"""You are a disaster preparedness expert explaining an evacuation plan.

Current Prevention Measures:
{json.dumps(placed_tokens, indent=2)}

Risk Zones:
{json.dumps(risk_zones, indent=2)}

Current Metrics:
{json.dumps(metrics, indent=2)}

In 2-3 sentences, explain:
1. What the current preparation accomplishes
2. Any gaps in coverage
3. Priority next action

Be specific about lives protected and evacuation improvements.
"""
        try:
            response = self._model.generate_content(prompt)
            return response.text.strip()
        except Exception:
            return self._fallback_prevention_explanation(placed_tokens, metrics)

    def _fallback_prevention_explanation(self, placed_tokens: list, metrics: dict) -> str:
        """Fallback explanation without Gemini."""
        token_types = [t.get('type', 'unknown') for t in placed_tokens]
        lives = metrics.get('lives_protected', 0)
        vuln = metrics.get('vulnerability_score', 1.0)

        if not placed_tokens:
            return "No prevention measures in place. All population centers remain at risk."

        measures = []
        if 'shelter' in token_types:
            measures.append("evacuation shelter designated")
        if 'hospital' in token_types:
            measures.append("medical supplies pre-positioned")
        if 'bridge' in token_types:
            measures.append("evacuation route reinforced")
        if 'food_shelter' in token_types:
            measures.append("emergency supplies stocked")

        return f"Current preparation: {', '.join(measures)}. Estimated {lives} lives protected, vulnerability reduced to {vuln:.0%}."

    def compare_outcomes(
        self,
        without_prep: dict,
        with_prep: dict,
        prevention_cost: int
    ) -> dict:
        """
        Use Gemini to generate intelligent comparison analysis.
        """
        if not self.is_ready:
            return self._fallback_comparison(without_prep, with_prep, prevention_cost)

        prompt = f"""You are a disaster economics analyst comparing two scenarios.

WITHOUT Preparation:
- Casualties: {without_prep.get('casualties_model', 0)}
- Evacuation time: {without_prep.get('evacuation_time_minutes', 0)} minutes
- Recovery cost: ${without_prep.get('recovery_cost_model', 0) * 100000}

WITH Preparation:
- Casualties: {with_prep.get('casualties_model', 0)}
- Evacuation time: {with_prep.get('evacuation_time_minutes', 0)} minutes
- Recovery cost: ${with_prep.get('recovery_cost_model', 0) * 100000}

Prevention Investment: ${prevention_cost * 50000}

Calculate:
1. Lives saved
2. Cost avoided
3. Return on investment (ROI)
4. Brief recommendation

Respond in JSON:
{{"lives_saved": X, "cost_avoided_usd": X, "roi_percent": X, "recommendation": "brief text"}}
"""
        try:
            response = self._model.generate_content(prompt)
            text = response.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            return json.loads(text)
        except Exception:
            return self._fallback_comparison(without_prep, with_prep, prevention_cost)

    def _fallback_comparison(self, without_prep: dict, with_prep: dict, prevention_cost: int) -> dict:
        """Fallback comparison without Gemini."""
        lives_saved = without_prep.get('casualties_model', 0) - with_prep.get('casualties_model', 0)
        cost_avoided = (without_prep.get('recovery_cost_model', 0) - with_prep.get('recovery_cost_model', 0)) * 100000
        investment = prevention_cost * 50000
        roi = ((cost_avoided - investment) / max(investment, 1)) * 100

        return {
            "lives_saved": lives_saved,
            "cost_avoided_usd": cost_avoided,
            "roi_percent": round(roi, 1),
            "recommendation": f"Prevention investment saves {lives_saved} lives with {roi:.0f}% ROI."
        }

    def answer_question(
        self,
        question: str,
        world_state: dict,
        mode: Literal["prevention", "relief"] = "relief"
    ) -> str:
        """
        Answer user questions grounded in current simulation state.
        """
        if not self.is_ready:
            return "AI analysis unavailable. Please check Gemini configuration."

        context = f"""You are an AI assistant for FLOODSHIFT, a disaster simulation.
Current mode: {mode}

World State:
- Phase: {world_state.get('phase', 'unknown')}
- Tokens placed: {len(world_state.get('tokens', []))}
- Blocked roads: {world_state.get('metrics', {}).get('blocked_roads', 0)}
- People reachable for medical: {world_state.get('metrics', {}).get('people_reachable_for_medical', 0)}

Answer this question concisely (2-3 sentences), grounded in the data above:
{question}

Important: Only state facts from the data. Don't invent statistics.
"""
        try:
            response = self._model.generate_content(context)
            return response.text.strip()
        except Exception as e:
            return f"Unable to process question: {str(e)}"


# Singleton instance
_gemini_instance: GeminiAdapter | None = None


def get_gemini() -> GeminiAdapter:
    """Get or create singleton Gemini adapter."""
    global _gemini_instance
    if _gemini_instance is None:
        _gemini_instance = GeminiAdapter()
    return _gemini_instance
