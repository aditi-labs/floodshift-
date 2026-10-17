import json
from types import SimpleNamespace as NS

import pytest

from backend.narration.local_config import ConfigError, read_config
from backend.narration.gemini_adapter import GeminiNarrator, api_failure_reason
from backend.narration.smoke import main, run_smoke
from backend.world.demo import staged_world


def test_config_never_executes_shell_or_expands_variables(tmp_path):
    path = tmp_path / 'gemini.env'
    path.write_text('GEMINI_API_KEY="$(touch /tmp/must-not-run)"\nGEMINI_MODEL="example-model"\n')
    values = read_config(path)
    assert values['GEMINI_API_KEY'] == '$(touch /tmp/must-not-run)'
    assert values['GEMINI_MODEL'] == 'example-model'


@pytest.mark.parametrize('content', [
    'GEMINI_API_KEY="secret-value',
    'GEMINI_API_KEY=secret-value\nGEMINI_API_KEY=again',
    'OTHER_SETTING=secret-value',
    'GEMINI_API_KEY=secret-value another-word',
])
def test_invalid_config_errors_never_contain_values(tmp_path, content):
    path = tmp_path / 'gemini.env'
    path.write_text(content)
    with pytest.raises(ConfigError) as error:
        read_config(path)
    assert 'secret-value' not in str(error.value)


@pytest.mark.parametrize('code,reason', [(401, 'api_authentication_failed'),
    (403, 'api_permission_denied'), (404, 'api_model_not_found'), (429, 'api_quota_exceeded'),
    (503, 'api_unavailable')])
def test_api_failures_have_safe_actionable_reasons(code, reason):
    error = RuntimeError('secret-sensitive-sdk-message')
    error.code = code
    assert api_failure_reason(error) == reason


def test_required_tool_call_cannot_pass_with_plain_text():
    class Client:
        def __init__(self):
            self.models = self
        def generate_content(self, **kwargs):
            assert kwargs['config']['tool_config']['function_calling_config']['mode'] == 'ANY'
            return NS(candidates=[], text='I have checked the tools.')
    result = GeminiNarrator(client=Client(), require_tool_call=True).answer(staged_world(), 'Explain')
    assert result['mode'] == 'TEXT' and result['reason'] == 'tool_call_missing'


def test_offline_smoke_proves_before_after_but_never_claims_live():
    report = run_smoke(GeminiNarrator(enabled=False))
    assert report['requested_mode'] == 'TEXT'
    assert not report['live_transport_and_tools_verified']
    assert report['cases'][0]['facts']['unmet_food_model'] == 8
    assert report['cases'][1]['facts']['unmet_food_model'] == 0
    assert all(c['world_unchanged'] for c in report['cases'])
    assert report['narration_text_review_required']


def test_missing_key_is_a_failed_live_smoke_not_false_success(monkeypatch, capsys):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    assert main(['--live']) == 1
    report = json.loads(capsys.readouterr().out)
    assert not report['live_transport_and_tools_verified']
    assert all(c['reason'] == 'missing_api_key' for c in report['cases'])


def test_bad_config_cli_reports_no_key_material(tmp_path, capsys):
    path = tmp_path / 'gemini.env'
    path.write_text('GEMINI_API_KEY="secret-value')
    assert main(['--env-file', str(path)]) == 2
    output = capsys.readouterr().out
    assert 'secret-value' not in output
    assert json.loads(output)['error'] == 'smoke_setup_failed'
