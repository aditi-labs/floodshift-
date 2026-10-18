"""
Gemini AI Adapter for FLOODSHIFT prevention mode.

Numbers (risk index, casualties, evacuation times, comparisons) are always computed
by deterministic code. Gemini only turns those supplied facts into a short
explanation, so it can never invent statistics. Without a key or SDK every method
returns the same numbers with a template explanation (mode="TEXT").

Uses the current Google Gen AI SDK (`google-genai`, pyproject `ai` extra) — the
older `google.generativeai` package is deprecated and is not a dependency.
Relief-mode questions go through backend/narration/gemini_adapter.py (tool-grounded).
"""
from __future__ import annotations
import json
import os
from typing import Literal

from backend.narration.gemini_adapter import api_failure_reason

try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    genai = None

SYSTEM_INSTRUCTION = '''You explain results of the FLOODSHIFT educational flood-preparedness
simulation. Use ONLY the numbers in the supplied JSON facts; never compute, estimate or
add new numbers. Call them model results. Do not claim real lives saved, safe routes,
engineering validation or official guidance. At most 60 words, plain text.'''
MAX_WORDS = 80


class GeminiAdapter:
    """Explains deterministic prevention results with Gemini; never the source of numbers."""

    def __init__(self, api_key: str | None = None, model: str | None = None, timeout_ms: int = 10000,
                 client=None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.model_name = model or os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
        self.timeout_ms = timeout_ms
        self._client = client
        if client is not None:
            self._status = "ready"
        elif not GEMINI_AVAILABLE:
            self._status = "sdk_not_installed"
        elif not self.api_key:
            self._status = "no_api_key"
        else:
            self._status = "ready"
        self.last_reason: str | None = None

    @property
    def status(self) -> str:
        return self._status

    @property
    def is_ready(self) -> bool:
        return self._status == "ready"

    def _explain(self, task: str, facts: dict) -> str | None:
        """Short grounded text, or None (reason in last_reason). Never raises or echoes errors."""
        if not self.is_ready:
            self.last_reason = self._status
            return None
        try:
            if self._client is None:
                self._client = genai.Client(api_key=self.api_key, http_options={
                    'timeout': self.timeout_ms, 'retry_options': {'attempts': 1}})
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=json.dumps({'task': task, 'facts': facts}, ensure_ascii=False, default=str),
                config={'system_instruction': SYSTEM_INSTRUCTION, 'max_output_tokens': 1024})
            text = getattr(response, 'text', None)
            if not isinstance(text, str) or not text.strip():
                self.last_reason = 'empty_response'
                return None
            if len(text.split()) > MAX_WORDS:
                self.last_reason = 'response_too_long'
                return None
            self.last_reason = None
            return text.strip()
        except Exception as error:
            # SDK exception text may contain transport or key data; return a code only.
            self.last_reason = api_failure_reason(error)
            return None

    def _mode(self, text: str | None) -> dict:
        return {'mode': 'LIVE' if text else 'TEXT', 'reason': None if text else self.last_reason}

    def analyze_risk(
        self,
        node_data: dict,
        elevation_m: float,
        distance_to_river_m: float,
        population: int,
        historical_floods: int = 0
    ) -> dict:
        """Formula risk analysis; Gemini may add an explanation but never changes numbers."""
        result = self._fallback_risk_analysis(elevation_m, distance_to_river_m, population)
        text = self._explain('Explain this location risk result in two sentences.',
                             {**result, 'node': node_data, 'elevation_m': elevation_m,
                              'distance_to_river_m': distance_to_river_m})
        if text:
            result['reasoning'] = text
        return {**result, **self._mode(text)}

    def _fallback_risk_analysis(
        self,
        elevation_m: float,
        distance_to_river_m: float,
        population: int
    ) -> dict:
        """Illustrative formula (authored weights and rates, not a calibrated model)."""
        elev_factor = max(0, min(1, (1500 - elevation_m) / 700))
        river_factor = max(0, min(1, (500 - distance_to_river_m) / 500))
        flood_probability = round((elev_factor * 0.4 + river_factor * 0.6), 2)

        if flood_probability >= 0.7:
            risk_level = "critical"
        elif flood_probability >= 0.5:
            risk_level = "high"
        elif flood_probability >= 0.3:
            risk_level = "medium"
        else:
            risk_level = "low"

        evacuation_time = 30 + (population * 0.5)
        vulnerability = flood_probability
        evacuation_efficiency = 0.7
        potential_casualties = int(population * vulnerability * (1 - evacuation_efficiency))

        return {
            "flood_probability": flood_probability,
            "risk_level": risk_level,
            "evacuation_time_minutes": int(evacuation_time),
            "potential_casualties": potential_casualties,
            "reasoning": f"Model result from elevation {elevation_m} m and {distance_to_river_m} m to the river.",
            "model_only": True,
        }

    def explain_prevention_strategy(
        self,
        placed_tokens: list[dict],
        risk_zones: list[dict],
        metrics: dict
    ) -> str:
        """Grounded explanation of the current prevention setup."""
        text = self._explain('In 2-3 sentences: what the current preparation does in this model, '
                             'the remaining gaps, and the next piece to place.',
                             {'placed_tokens': [t.get('type') for t in placed_tokens],
                              'risk_zones': [{k: z.get(k) for k in ('zone_id', 'risk_level', 'flood_probability',
                                                                     'population_exposed', 'is_protected')}
                                             for z in risk_zones],
                              'metrics': metrics})
        return text or self._fallback_prevention_explanation(placed_tokens, metrics)

    def _fallback_prevention_explanation(self, placed_tokens: list, metrics: dict) -> str:
        """Template explanation from the same facts."""
        token_types = [t.get('type', 'unknown') for t in placed_tokens]
        lives = metrics.get('lives_protected', 0)
        vuln = metrics.get('vulnerability_score', 1.0)

        if not placed_tokens:
            return "No prevention measures in place. All modeled population zones remain at risk."

        measures = []
        if 'shelter' in token_types:
            measures.append("evacuation shelter designated")
        if 'hospital' in token_types:
            measures.append("medical supplies pre-positioned")
        if 'bridge' in token_types:
            measures.append("evacuation route reinforced")
        if 'food_shelter' in token_types:
            measures.append("emergency supplies stocked")

        return (f"Current preparation: {', '.join(measures)}. Model estimate: {lives} people protected, "
                f"vulnerability index {vuln:.0%}. Illustrative, not a real outcome.")

    def compare_outcomes(
        self,
        without_prep: dict,
        with_prep: dict,
        prevention_cost: int
    ) -> dict:
        """Deterministic comparison; Gemini only writes the recommendation sentence."""
        result = self._fallback_comparison(without_prep, with_prep, prevention_cost)
        text = self._explain('Write a one-sentence recommendation comparing the two model outcomes.',
                             {'without_preparation': without_prep, 'with_preparation': with_prep, **result})
        if text:
            result['recommendation'] = text
        return {**result, **self._mode(text)}

    def _fallback_comparison(self, without_prep: dict, with_prep: dict, prevention_cost: int) -> dict:
        """Differences in model units; no currency or real casualty claims."""
        lives_saved = without_prep.get('casualties_model', 0) - with_prep.get('casualties_model', 0)
        cost_avoided = without_prep.get('recovery_cost_model', 0) - with_prep.get('recovery_cost_model', 0)
        roi = (cost_avoided - prevention_cost) / max(prevention_cost, 1)

        return {
            "lives_saved_model": lives_saved,
            "cost_avoided_model": cost_avoided,
            "prevention_investment_model": prevention_cost,
            "roi_ratio": round(roi, 2),
            "recommendation": (f"In this teaching model, preparation lowers modeled casualties by {lives_saved} "
                               f"and recovery cost by {cost_avoided} model units."),
            "model_only": True,
        }

    def answer_question(
        self,
        question: str,
        world_state: dict,
        mode: Literal["prevention", "relief"] = "relief"
    ) -> str:
        """Answer from a compact state summary; unknown facts stay unknown."""
        metrics = world_state.get('metrics', {})
        facts = {'mode': mode, 'phase': world_state.get('phase'),
                 'tokens_placed': [t.get('type') for t in world_state.get('tokens', [])],
                 'metrics': metrics}
        text = self._explain(f'Answer in 2-3 sentences using only the facts: {question[:500]}', facts)
        if text:
            return text
        return (f"Model state: phase {facts['phase']}, {metrics.get('blocked_roads', 0)} blocked road(s), "
                f"{len(facts['tokens_placed'])} piece(s) placed. AI explanation unavailable ({self.last_reason}).")


# Singleton instance
_gemini_instance: GeminiAdapter | None = None


def get_gemini() -> GeminiAdapter:
    """Get or create singleton Gemini adapter."""
    global _gemini_instance
    if _gemini_instance is None:
        _gemini_instance = GeminiAdapter()
    return _gemini_instance
