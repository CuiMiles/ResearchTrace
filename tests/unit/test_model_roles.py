"""Role chains: configured model order, labelled downgrade, and caps that a chain cannot bypass."""
import json
import time as _time

import httpx
import pytest

from services.api import models, store

NOW = 1780000000
LITE = 'gemini-3.5-flash-lite'
FLASH = 'gemini-3.6-flash'


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    store.migrate()
    for name, value in {'HYDROGEN_SMOKE_LIMIT': '400', 'HYDROGEN_SESSION_LIMIT': '400',
                        'HYDROGEN_WORKFLOW_LIMIT': '2', 'HYDROGEN_RUNTIME_SOFT_RPD': '16',
                        'RT_SMOKE_MODE': 'true', 'GEMINI_API_KEY': 'fixture-key-one',
                        'GEMINI_PROJECT_1': 'project-one'}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv('GEMINI_API_KEY2', raising=False)
    monkeypatch.setattr(models.time, 'time', lambda: NOW)
    monkeypatch.setattr(models.time, 'sleep', lambda _: pytest.fail('Unexpected local wait'))


def run(workspace='ws-a'):
    rid = store.uid()
    with store.db() as c:
        c.execute("INSERT INTO runs(id,workspace,kind,status,payload,created,updated) VALUES(?,?,?,?,?,?,?)",
                  (rid, workspace, 'qa', 'running', '{}', _time.time(), _time.time()))
    return rid


def upstream(monkeypatch, status_for=lambda model: 200):
    seen = []

    def handle(request):
        model = request.url.path.split('/models/')[1].split(':')[0]
        seen.append(model)
        code = status_for(model)
        if code != 200:
            return httpx.Response(code, json={'error': {'status': 'UNAVAILABLE', 'message': 'fixture'}})
        return httpx.Response(200, json={'modelVersion': model, 'usageMetadata': {'promptTokenCount': 5, 'candidatesTokenCount': 3},
                                         'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '{"ok":true}'}]}}]})

    monkeypatch.setattr(models, 'client', lambda: httpx.Client(transport=httpx.MockTransport(handle), trust_env=False))
    return seen


def test_unconfigured_roles_keep_legacy_single_models(monkeypatch):
    assert models.role_chain('deep') == [models.CORE]
    assert models.role_chain('answer') == [models.CORE]
    assert models.role_chain('verify') == [models.CORE]
    assert models.role_chain('light') == [models.BATCH]
    monkeypatch.setenv('RT_MODEL_DEEP', f'{models.CORE}, {FLASH}')
    assert models.role_chain('answer') == [models.CORE, FLASH]


def test_invalid_role_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv('RT_MODEL_LIGHT', 'gemini/../../x')
    with pytest.raises(models.QuotaRefusal) as caught:
        models.role_chain('light')
    assert caught.value.code == 'budget_configuration'


def test_pydantic_json_schema_uses_json_schema_api_field(monkeypatch):
    from services.api.writing_workflows import ClaimRepairs
    schema = ClaimRepairs.model_json_schema()
    assert '$defs' in schema
    bodies = []
    def request(model, method, body, run_id, estimate):
        bodies.append(body)
        return {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '{"claims":[]}'}]}}]}, 'fixture'
    monkeypatch.setattr(models, 'request', request)
    models._generate_once(LITE, 's', 'p', None, response_schema=schema)
    config = bodies[0]['generationConfig']
    assert config['responseJsonSchema'] == models.provider_json_schema(schema) and 'responseSchema' not in config
    assert 'default' not in config['responseJsonSchema']['$defs']['Claim']['properties']['id']
    # Provider hints cannot remove local validation constraints.
    assert schema['$defs']['Claim']['properties']['id']['anyOf'][0]['maxLength'] == 100


def test_exhausted_daily_quota_downgrades_with_label(monkeypatch):
    monkeypatch.setenv('RT_MODEL_DEEP', f'{models.CORE},{FLASH}')
    monkeypatch.setenv('RT_MODEL_DAILY_LIMITS', json.dumps({models.CORE: 1}))
    seen = upstream(monkeypatch)
    rid = run()
    first = models.generate('s', 'p', rid, role='deep')
    assert first['requested_model'] == models.CORE and 'downgraded_from' not in first
    second = models.generate('s', 'p', run(), role='deep')
    assert second['requested_model'] == FLASH
    assert second['downgraded_from'] == [{'model': models.CORE, 'reason': 'model_daily'}]
    assert seen == [models.CORE, FLASH]


def test_definite_provider_error_moves_on_but_is_counted(monkeypatch):
    monkeypatch.setenv('RT_MODEL_ANSWER', f'{LITE},{FLASH}')
    seen = upstream(monkeypatch, lambda model: 400 if model == LITE else 200)
    rid = run()
    result = models.generate('s', 'p', rid, role='answer')
    assert result['requested_model'] == FLASH
    assert result['downgraded_from'][0]['reason'] == 'provider_failed'
    assert seen == [LITE, FLASH]
    statuses = {r['model']: r['status'] for r in store.rows('SELECT model,status FROM quota WHERE run_id=?', (rid,))}
    assert statuses == {LITE: 'failed', FLASH: 'ok'}
    steps = [s['event'] for s in store.rows('SELECT event FROM steps WHERE run_id=?', (rid,))]
    assert 'model_downgraded' in steps


def test_unknown_outcome_is_never_repeated_on_another_model(monkeypatch):
    monkeypatch.setenv('RT_MODEL_ANSWER', f'{LITE},{FLASH}')
    seen = []

    def handle(request):
        seen.append(request.url.path)
        raise httpx.ReadTimeout('fixture timeout')

    monkeypatch.setattr(models, 'client', lambda: httpx.Client(transport=httpx.MockTransport(handle), trust_env=False))
    with pytest.raises(models.SentRequestError) as caught:
        models.generate('s', 'p', run(), role='answer')
    assert caught.value.outcome == 'unknown'
    assert len(seen) == 1


def test_run_wide_call_cap_is_not_bypassed_by_the_chain(monkeypatch):
    monkeypatch.setenv('RT_MODEL_LIGHT', f'{LITE},{FLASH}')
    monkeypatch.setenv('RT_WORKFLOW_MODEL_CALLS', '2')
    seen = upstream(monkeypatch)
    rid = run()
    models.generate('s', 'p', rid, role='light')
    models.generate('s', 'p', rid, role='light')
    with pytest.raises(models.QuotaRefusal) as caught:
        models.generate('s', 'p', rid, role='light')
    assert caught.value.code == 'workflow_calls'
    assert seen == [LITE, LITE]


def test_workspace_daily_cap_spans_models(monkeypatch):
    monkeypatch.setenv('RT_MODEL_LIGHT', f'{LITE},{FLASH}')
    monkeypatch.setenv('RT_WORKSPACE_DAILY_CALLS', '1')
    upstream(monkeypatch)
    models.generate('s', 'p', run('ws-b'), role='light')
    with pytest.raises(models.QuotaRefusal) as caught:
        models.generate('s', 'p', run('ws-b'), role='light')
    assert caught.value.code == 'workspace_calls'
    models.generate('s', 'p', run('ws-c'), role='light')


def test_plain_text_generation_omits_json_mime(monkeypatch):
    bodies = []

    def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={'modelVersion': LITE, 'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': 'hi'}]}}]})

    monkeypatch.setattr(models, 'client', lambda: httpx.Client(transport=httpx.MockTransport(handle), trust_env=False))
    models.generate('s', 'p', run(), role='light', json_output=False)
    assert 'responseMimeType' not in bodies[0]['generationConfig']


def test_overload_on_whole_chain_gets_one_delayed_retry(monkeypatch):
    monkeypatch.setenv('RT_MODEL_ANSWER', f'{LITE},{FLASH}')
    replies = iter([503, 503, 200])
    seen = upstream(monkeypatch, lambda model: next(replies))
    waits = []
    monkeypatch.setattr(models.time, 'sleep', waits.append)
    rid = run()
    result = models.generate('s', 'p', rid, role='answer')
    assert seen == [LITE, FLASH, LITE] and waits == [4]
    assert result['requested_model'] == LITE
    assert len(store.rows('SELECT id FROM quota WHERE run_id=?', (rid,))) == 3


def test_overload_retry_happens_only_once(monkeypatch):
    monkeypatch.setenv('RT_MODEL_ANSWER', f'{LITE},{FLASH}')
    seen = upstream(monkeypatch, lambda model: 503)
    monkeypatch.setattr(models.time, 'sleep', lambda _: None)
    with pytest.raises(models.SentRequestError):
        models.generate('s', 'p', run(), role='answer')
    assert seen == [LITE, FLASH, LITE, FLASH]
