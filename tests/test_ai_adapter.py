"""Prevention Gemini adapter: numbers are code-computed; Gemini only explains."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.ai.gemini_adapter import GeminiAdapter

ROOT = Path(__file__).resolve().parents[1]
WITHOUT = {'casualties_model': 9, 'recovery_cost_model': 650}
WITH = {'casualties_model': 3, 'recovery_cost_model': 250}


class FakeModels:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def generate_content(self, **request):
        self.calls.append(request)
        if isinstance(self.reply, Exception):
            raise self.reply
        return SimpleNamespace(text=self.reply)


def adapter(reply):
    client = SimpleNamespace(models=FakeModels(reply))
    return GeminiAdapter(client=client), client.models


def test_without_key_returns_computed_numbers_marked_text(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    result = GeminiAdapter().compare_outcomes(WITHOUT, WITH, 4)
    assert result['mode'] == 'TEXT' and result['lives_saved_model'] == 6 and result['cost_avoided_model'] == 400
    assert '$' not in json.dumps(result)


def test_live_explanation_never_changes_numbers_and_sends_only_facts():
    ai, models = adapter('Preparation lowers modeled casualties by 6 in this teaching model.')
    result = ai.compare_outcomes(WITHOUT, WITH, 4)
    assert result['mode'] == 'LIVE' and result['lives_saved_model'] == 6 and result['roi_ratio'] == 99.0
    assert result['recommendation'].startswith('Preparation')
    request = models.calls[0]
    assert 'never compute' in request['config']['system_instruction']
    assert json.loads(request['contents'])['facts']['lives_saved_model'] == 6


def test_errors_fall_back_without_leaking_exception_text():
    error = RuntimeError('secret-key-123 transport detail')
    error.code = 429
    ai, _ = adapter(error)
    result = ai.compare_outcomes(WITHOUT, WITH, 4)
    assert result['mode'] == 'TEXT' and result['reason'] == 'api_quota_exceeded'
    answer = ai.answer_question('What changed?', {'phase': 'disaster_active', 'metrics': {'blocked_roads': 3}, 'tokens': []})
    assert 'secret' not in answer and 'api_quota_exceeded' in answer


def test_overlong_answer_is_rejected():
    ai, _ = adapter('word ' * 200)
    assert ai.analyze_risk({}, 1460, 70, 700)['mode'] == 'TEXT'


def test_measured_risk_data_rebuilds_identically():
    pytest.importorskip('rasterio')
    pytest.importorskip('pyproj')
    from scripts.geodata.build_risk_data import HOT, build
    committed = (HOT / 'terrain.json').read_text()
    build()
    assert (HOT / 'terrain.json').read_text() == committed
    terrain = json.loads(committed)
    assert terrain['data_mode'] == 'MEASURED_OPEN_DATA'
    assert all(1300 < n['elevation_m'] < 1700 for n in terrain['node_terrain'].values())
    nodes = {n['id'] for n in json.loads((HOT / 'roads.json').read_text())['nodes']}
    assert set(terrain['node_terrain']) <= nodes
