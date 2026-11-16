"""P0-03 regression coverage: isolated SQLite and explicit HTTP fixtures only."""
from concurrent.futures import ThreadPoolExecutor
import json

import httpx
import pytest

from services.api import models, store


NOW = 1780000000


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    store.migrate()
    for name in ('RT_BUDGET_PROFILE', 'HYDROGEN_EVALUATION_LIMIT',
                 'HYDROGEN_JUDGING_LIMIT', 'GEMINI_API_KEY2',
                 'GEMINI_PROJECT_1', 'GEMINI_PROJECT_2'):
        monkeypatch.delenv(name, raising=False)
    for name, value in {'HYDROGEN_SMOKE_LIMIT': '4', 'HYDROGEN_SESSION_LIMIT': '2',
                        'HYDROGEN_WORKFLOW_LIMIT': '2', 'HYDROGEN_RUNTIME_SOFT_RPD': '16',
                        'RT_SMOKE_MODE': 'true', 'GEMINI_API_KEY': 'fixture-key-one'}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(models.time, 'time', lambda: NOW)

    def no_http():
        pytest.fail('This test did not install an explicit upstream fixture')

    monkeypatch.setattr(models, 'client', no_http)
    monkeypatch.setattr(models.time, 'sleep', lambda _: pytest.fail('Unexpected local wait'))


def routes(monkeypatch, same_project=False):
    monkeypatch.setenv('GEMINI_PROJECT_1', 'project-one')
    monkeypatch.setenv('GEMINI_PROJECT_2', 'project-one' if same_project else 'project-two')
    monkeypatch.setenv('GEMINI_API_KEY2', 'fixture-key-two')


def upstream(monkeypatch, reply=None):
    calls = []

    def handle(request):
        calls.append(request)
        return reply(request) if reply else httpx.Response(200, json={'fixture': True})

    monkeypatch.setattr(models, 'client', lambda: httpx.Client(transport=httpx.MockTransport(handle), trust_env=False))
    return calls


def seed(project, count=1, model=None, run_id=None, profile=None, status='ok', now=None, workflow_limit=2):
    ids = []
    with store.db() as c:
        for _ in range(count):
            qid = store.uid()
            c.execute('''INSERT INTO quota(id,project,model,day,run_id,started,input_tokens,status)
                         VALUES(?,?,?,?,?,?,?,?)''',
                      (qid, project, model or models.CORE, models.quota_day(NOW), run_id,
                       NOW - 3600 if now is None else now, 100, status))
            if profile:
                c.execute('INSERT INTO quota_context VALUES(?,?,?)', (qid, profile, workflow_limit))
            ids.append(qid)
    return ids


def run(workspace='fixture-workspace'):
    rid = store.uid()
    store.execute('''INSERT INTO runs(id,workspace,kind,status,payload,created,updated)
                     VALUES(?,?,?,?,?,?,?)''', (rid, workspace, 'qa', 'running', '{}', NOW, NOW))
    return rid


def evaluation(monkeypatch, limit='30'):
    monkeypatch.setenv('RT_BUDGET_PROFILE', 'evaluation')
    monkeypatch.setenv('HYDROGEN_EVALUATION_LIMIT', limit)


@pytest.mark.parametrize('status',['ok','failed','unknown','reserved'])
def test_daily_model_cap_counts_all_projects_and_outcomes(monkeypatch,status):
    routes(monkeypatch);evaluation(monkeypatch,'80')
    monkeypatch.setenv('RT_MODEL_DAILY_LIMITS',json.dumps({models.CORE:40,'gemini-3.8-flash':40}))
    seed('project-one',20,status=status);seed('project-two',20,status=status)
    before=store.rows('SELECT * FROM quota ORDER BY id')
    with pytest.raises(models.QuotaRefusal) as caught:
        models.request(models.CORE,'generateContent',{},None,100)
    assert caught.value.scope=='global' and caught.value.code=='model_daily'
    assert store.rows('SELECT * FROM quota ORDER BY id')==before
    # The second model has its own cap; a first-model refusal cannot consume it.
    calls=upstream(monkeypatch)
    models.request('gemini-3.8-flash','generateContent',{},None,100)
    assert len(calls)==1


def test_first_daily_exhausted_project_routes_to_second_without_recording_refusal(monkeypatch):
    routes(monkeypatch)
    evaluation(monkeypatch)
    seed('project-one', count=20)
    before = store.rows('SELECT * FROM quota ORDER BY id')
    calls = upstream(monkeypatch)

    _, project = models.request(models.CORE, 'generateContent', {}, None, 100)

    assert project == 'project-two'
    assert len(calls) == 1
    assert calls[0].headers['x-goog-api-key'] == 'fixture-key-two'
    assert store.one('SELECT COUNT(*) n FROM quota')['n'] == 21
    assert store.rows('SELECT * FROM quota WHERE project=? ORDER BY id', ('project-one',)) == before
    assert store.one('SELECT profile FROM quota_context')['profile'] == 'evaluation'


@pytest.mark.parametrize('blocker', ['concurrency', 'rpm', 'tpm'])
def test_transient_refusal_checks_other_project_before_waiting(monkeypatch, blocker):
    routes(monkeypatch)
    if blocker == 'concurrency':
        seed('project-one', model=models.BATCH, status='reserved', now=NOW)
    elif blocker == 'rpm':
        seed('project-one', model=models.BATCH, count=15, now=NOW)
    else:
        ids = seed('project-one', model=models.BATCH, count=3, now=NOW)
        for qid in ids:
            store.execute('UPDATE quota SET input_tokens=83333 WHERE id=?', (qid,))
    calls = upstream(monkeypatch)
    _, project = models.request(models.BATCH, 'generateContent', {}, None, 100)
    assert project == 'project-two'
    assert len(calls) == 1


def test_same_project_two_keys_attempted_once(monkeypatch):
    routes(monkeypatch, same_project=True)
    seed('project-one', model=models.BATCH, count=500)
    tried = []
    reserve = models.reserve

    def tracked(project, *args):
        tried.append(project)
        return reserve(project, *args)

    monkeypatch.setattr(models, 'reserve', tracked)
    with pytest.raises(models.QuotaRefusal) as caught:
        models.request(models.BATCH, 'generateContent', {}, None, 100)
    assert caught.value.scope == 'project'
    assert tried == ['project-one']
    assert store.one('SELECT COUNT(*) n FROM quota')['n'] == 500


def test_unconfigured_project_ids_and_reused_identical_keys_cannot_double_routes(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY2', 'fixture-key-two')
    assert len(list(models._choose(models.CORE))) == 1
    routes(monkeypatch)
    monkeypatch.setenv('GEMINI_API_KEY2', 'fixture-key-one')
    assert len(list(models._choose(models.CORE))) == 1


@pytest.mark.parametrize('configured', ['GEMINI_PROJECT_1', 'GEMINI_PROJECT_2'])
@pytest.mark.parametrize('missing_value', [None, '', '   '])
def test_only_one_explicit_project_id_keeps_both_keys_on_shared_quota(monkeypatch, configured, missing_value):
    monkeypatch.setenv('GEMINI_API_KEY2', 'fixture-key-two')
    monkeypatch.setenv(configured, 'explicit-project')
    missing = 'GEMINI_PROJECT_2' if configured == 'GEMINI_PROJECT_1' else 'GEMINI_PROJECT_1'
    if missing_value is not None:
        monkeypatch.setenv(missing, missing_value)
    assert [p for p, _ in models.credentials()] == ['explicit-project', 'explicit-project']
    assert len(list(models._choose(models.CORE))) == 1


def test_global_smoke_guard_precedes_project_failure_and_cannot_fall_through(monkeypatch):
    routes(monkeypatch)
    seed('project-one', count=4, status='reserved', now=NOW)
    tried = []
    reserve = models.reserve

    def tracked(project, *args):
        tried.append(project)
        return reserve(project, *args)

    monkeypatch.setattr(models, 'reserve', tracked)
    with pytest.raises(models.QuotaRefusal) as caught:
        models.request(models.CORE, 'generateContent', {}, None, 100)
    assert (caught.value.scope, caught.value.code) == ('global', 'profile_budget')
    assert tried == ['project-one']
    assert store.one('SELECT COUNT(*) n FROM quota')['n'] == 4


@pytest.mark.parametrize('profile', ['evaluation', 'judging'])
@pytest.mark.parametrize('configured', [None, '', '0', '-1', '1.5', 'true', 'NaN', '1e3', '99999999999999'])
def test_non_smoke_profiles_require_explicit_positive_integer_budget(monkeypatch, profile, configured):
    monkeypatch.setenv('RT_BUDGET_PROFILE', profile)
    if configured is not None:
        monkeypatch.setenv(models.PROFILE_LIMITS[profile], configured)
    with pytest.raises(models.QuotaRefusal) as caught:
        models.reserve('project-one', models.CORE, 100, None)
    assert (caught.value.scope, caught.value.code) == ('global', 'budget_configuration')
    assert store.rows('SELECT * FROM quota') == []


@pytest.mark.parametrize('profile', ['evaluation', 'judging'])
def test_explicit_profile_has_separate_global_budget_and_preserves_historical_four(monkeypatch, profile):
    seed('legacy-project', count=4, status='unknown')
    legacy = store.rows('SELECT * FROM quota ORDER BY id')
    monkeypatch.setenv('RT_BUDGET_PROFILE', profile)
    monkeypatch.setenv(models.PROFILE_LIMITS[profile], '1')
    qid = models.reserve('project-one', models.CORE, 100, None)
    assert store.one('SELECT * FROM quota_context WHERE quota_id=?', (qid,)) == {
        'quota_id': qid, 'profile': profile, 'workflow_limit': 2}
    with pytest.raises(models.QuotaRefusal, match='总预算'):
        models.reserve('project-two', models.CORE, 100, None)
    monkeypatch.setenv('RT_BUDGET_PROFILE', 'smoke')
    with pytest.raises(models.QuotaRefusal, match='冒烟预算'):
        models.reserve('project-two', models.CORE, 100, None)
    assert store.rows('SELECT * FROM quota WHERE project=? ORDER BY id', ('legacy-project',)) == legacy


def test_legacy_false_mode_alone_does_not_authorize_new_budget(monkeypatch):
    seed('legacy-project', count=4)
    monkeypatch.setenv('RT_SMOKE_MODE', 'false')
    assert models.budget_policy()['profile'] == 'smoke'
    with pytest.raises(models.QuotaRefusal, match='冒烟预算'):
        models.reserve('project-two', models.CORE, 100, None)


def test_workspace_daily_limit_spans_projects_profiles_and_runs(monkeypatch):
    first = run()
    second = run()
    seed('project-one', count=2, run_id=first)
    evaluation(monkeypatch)
    with pytest.raises(models.QuotaRefusal) as caught:
        models.reserve('project-two', models.CORE, 100, second)
    assert (caught.value.scope, caught.value.code) == ('global', 'workspace_budget')
    other_workspace = run('other-workspace')
    assert models.reserve('project-two', models.CORE, 100, other_workspace)


def test_workflow_cap_pins_before_environment_increase_and_across_days(monkeypatch):
    evaluation(monkeypatch)
    monkeypatch.setenv('HYDROGEN_WORKFLOW_LIMIT', '1')
    rid = run()
    qid = models.reserve('project-one', models.CORE, 100, rid)
    store.execute("UPDATE quota SET status='failed' WHERE id=?", (qid,))
    monkeypatch.setenv('HYDROGEN_WORKFLOW_LIMIT', '9')
    with pytest.raises(models.QuotaRefusal) as caught:
        models.reserve('project-two', models.CORE, 100, rid, NOW + 86400)
    assert caught.value.code == 'workflow_budget'
    assert models.workflow_budget(rid) == {'profile': 'evaluation', 'estimated_core_calls': 1,
                                         'limit': 1, 'used': 1, 'remaining': 0}


def test_lower_workflow_cap_stays_pinned_after_operator_increase(monkeypatch):
    evaluation(monkeypatch)
    rid = run()
    seed('project-one', model=models.BATCH, run_id=rid, profile='evaluation', workflow_limit=2)
    monkeypatch.setenv('HYDROGEN_WORKFLOW_LIMIT', '1')
    models.reserve('project-one', models.CORE, 100, rid)
    monkeypatch.setenv('HYDROGEN_WORKFLOW_LIMIT', '5')
    with pytest.raises(models.QuotaRefusal) as caught:
        models.reserve('project-two', models.CORE, 100, rid)
    assert caught.value.code == 'workflow_budget'
    assert models.workflow_budget(rid)['limit'] == 1


def test_existing_workflow_cannot_switch_profile_to_gain_budget(monkeypatch):
    rid = run()
    seed('project-one', run_id=rid)
    evaluation(monkeypatch)
    with pytest.raises(models.QuotaRefusal) as caught:
        models.reserve('project-two', models.CORE, 100, rid)
    assert caught.value.code == 'workflow_profile'


def test_cancelled_and_missing_run_refuse_globally_without_ledger_mutation():
    rid = run()
    store.execute("UPDATE runs SET status='cancelled' WHERE id=?", (rid,))
    for run_id, code in [(rid, 'cancelled'), ('missing-run', 'invalid_run')]:
        with pytest.raises(models.QuotaRefusal) as caught:
            models.reserve('project-one', models.BATCH, 100, run_id)
        assert (caught.value.scope, caught.value.code) == ('global', code)
    assert store.rows('SELECT * FROM quota') == []


@pytest.mark.parametrize('outcome', ['unknown', 'failed', 'disabled'])
def test_sent_requests_never_try_second_project_and_keep_budget(monkeypatch, outcome):
    routes(monkeypatch)

    def reply(request):
        if outcome == 'unknown':
            raise httpx.ReadTimeout('fixture-only unknown consumption', request=request)
        code = 401 if outcome == 'disabled' else 429
        return httpx.Response(code, json={'error': {'status': 'SECRET_fixture-key-one',
                                                   'message': 'secret fixture-key-one'}})

    calls = upstream(monkeypatch, reply)
    with pytest.raises(models.SentRequestError) as caught:
        models.request(models.CORE, 'generateContent', {}, None, 777)
    assert caught.value.outcome == outcome
    assert len(calls) == 1
    ledger = store.rows('SELECT * FROM quota')
    assert len(ledger) == 1
    assert ledger[0]['id'] == caught.value.quota_id
    assert (ledger[0]['project'], ledger[0]['status'], ledger[0]['input_tokens']) == ('project-one', outcome, 777)
    assert 'fixture-key' not in str(caught.value)
    assert 'SECRET_' not in str(caught.value)
    assert models.provider_report()['profiles'][0]['used'] == 1


def test_invalid_sent_json_never_uses_other_project(monkeypatch):
    routes(monkeypatch)
    calls = upstream(monkeypatch, lambda _: httpx.Response(200, text='{bad'))
    with pytest.raises(models.SentRequestError) as caught:
        models.request(models.CORE, 'generateContent', {}, None, 777)
    assert caught.value.outcome == 'failed'
    assert len(calls) == 1
    assert store.one('SELECT status FROM quota')['status'] == 'failed'


def test_legacy_adapter_daily_refusal_can_route_but_unknown_errors_fail_closed(monkeypatch):
    routes(monkeypatch)
    reserve = models.reserve

    def legacy(project, *args):
        if project == 'project-one':
            raise models.ModelError('project daily quota exhausted')
        return reserve(project, *args)

    monkeypatch.setattr(models, 'reserve', legacy)
    calls = upstream(monkeypatch)
    assert models.request(models.BATCH, 'generateContent', {}, None, 100)[1] == 'project-two'
    assert len(calls) == 1

    def unknown(*args):
        raise models.ModelError('unclassified reservation failure')

    monkeypatch.setattr(models, 'reserve', unknown)
    with pytest.raises(models.ModelError, match='unclassified'):
        models.request(models.BATCH, 'generateContent', {}, None, 100)
    assert len(calls) == 1


def test_all_transient_routes_wait_without_sending_and_are_bounded(monkeypatch):
    routes(monkeypatch)
    attempts, waits = [], []

    def blocked(project, *args):
        attempts.append(project)
        raise models.QuotaRefusal('fixture transient', scope='transient', code='project_window')

    monkeypatch.setattr(models, 'reserve', blocked)
    monkeypatch.setattr(models.time, 'sleep', waits.append)
    with pytest.raises(models.QuotaRefusal):
        models.request(models.BATCH, 'generateContent', {}, None, 100)
    assert len(attempts) == 30
    assert len(waits) == 14
    assert store.rows('SELECT * FROM quota') == []


@pytest.mark.parametrize('scope', ['profile', 'workspace', 'workflow'])
def test_parallel_reservations_do_not_overspend_across_projects(monkeypatch, scope):
    if scope == 'profile':
        seed('legacy', count=3)
        run_ids = [None] * 8
    else:
        evaluation(monkeypatch)
        if scope == 'workflow':
            monkeypatch.setenv('HYDROGEN_WORKFLOW_LIMIT', '1')
            run_ids = [run()] * 8
        else:
            monkeypatch.setenv('HYDROGEN_SESSION_LIMIT', '1')
            run_ids = [run() for _ in range(8)]

    def claim(i):
        try:
            return models.reserve(f'project-{i}', models.CORE, 100, run_ids[i])
        except models.QuotaRefusal:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(bool(qid) for qid in pool.map(claim, range(8))) == 1
    assert store.one('SELECT COUNT(*) n FROM quota_context')['n'] == 1


def test_report_profiles_and_pinned_caps_redacts_invalid_operator_values(monkeypatch):
    seed('legacy', count=4)
    evaluation(monkeypatch, '3')
    rid = run('private-workspace')
    qid = models.reserve('project-one', models.CORE, 100, rid)
    monkeypatch.setenv('HYDROGEN_WORKFLOW_LIMIT', '9')
    report = models.provider_report()
    profiles = {p['profile']: p for p in report['profiles']}
    assert (profiles['smoke']['used'], profiles['smoke']['remaining']) == (4, 0)
    assert (profiles['evaluation']['limit'], profiles['evaluation']['used'], profiles['evaluation']['remaining']) == (3, 1, 2)
    assert profiles['judging']['configured'] is False
    assert report['workflow_pinned_caps'] == [{'profile': 'evaluation', 'workflow_limit': 2, 'workflows': 1}]
    assert report['paid_fallback'] is False
    serialized = json.dumps(report)
    assert rid not in serialized and qid not in serialized
    assert 'fixture-key' not in serialized and 'private-workspace' not in serialized

    monkeypatch.setenv('HYDROGEN_EVALUATION_LIMIT', 'SECRET_fixture-key-one')
    invalid = models.provider_report()
    assert invalid['hydrogen_budget'] is None
    assert invalid['budget_configuration_error'] == 'budget_configuration'
    assert 'SECRET_' not in json.dumps(invalid)


def test_migration_is_idempotent_and_keeps_untagged_quota_unchanged():
    seed('legacy', count=4)
    before = store.rows('SELECT * FROM quota ORDER BY id')
    store.migrate()
    store.migrate()
    assert store.rows('SELECT * FROM quota ORDER BY id') == before
    assert store.rows('SELECT * FROM quota_context') == []
