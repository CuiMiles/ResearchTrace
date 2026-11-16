"""Isolated reviewer identity regressions, with no provider or production data.

Helper checks use the agreed schema fixture. API cases run against the real
app and require the main-owned login/session/administration integration.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from services.api import reviewer_accounts as accounts, store


NOW = 1780000000


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    store.migrate()
    # The production migration is main-owned; the helper contract can be tested
    # before that disjoint file is integrated, without touching the real DB.
    with store.db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS review_accounts(
            id TEXT PRIMARY KEY,workspace TEXT NOT NULL UNIQUE,label TEXT NOT NULL,
            code_hash TEXT NOT NULL UNIQUE,created REAL NOT NULL,expires REAL NOT NULL,
            revoked INTEGER DEFAULT 0,last_login REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,
            workspace TEXT NOT NULL,role TEXT NOT NULL,expires REAL NOT NULL)''')
    clock = [NOW]
    monkeypatch.setattr(accounts.time, 'time', lambda: clock[0])
    yield clock


def session(workspace, role='reviewer'):
    token_hash = hashlib.sha256(store.uid().encode()).hexdigest()
    store.execute('INSERT INTO sessions VALUES(?,?,?,?)', (token_hash, workspace, role, NOW + 14 * 86400))
    return token_hash


def test_creation_returns_code_once_and_database_stores_only_hash():
    created = accounts.create_reviewer('  测试评审  ')
    code = created.pop('access_code')
    assert len(base64.urlsafe_b64decode(code + '=')) == 32
    assert created['label'] == '测试评审'
    assert created['expires'] == NOW + 7 * 86400
    assert created['status'] == 'active'
    assert created['last_login'] is None
    saved = store.one('SELECT * FROM review_accounts')
    assert len(saved['code_hash']) == 64
    assert code not in json.dumps(saved)
    assert 'code_hash' not in created
    assert accounts.list_reviewers() == [created]
    assert store.one('SELECT id FROM workspaces')['id'] == created['workspace']


def test_lookup_is_stable_updates_last_login_and_does_not_extend_expiry(isolated):
    created = accounts.create_reviewer('Fixture reviewer', days=2)
    first = accounts.lookup_reviewer(created['access_code'])
    isolated[0] += 3600
    second = accounts.lookup_reviewer(created['access_code'])
    assert first == second
    assert second == {'account_id': created['id'], 'workspace': created['workspace'],
                      'role': 'reviewer', 'expires': NOW + 2 * 86400}
    assert accounts.list_reviewers()[0]['last_login'] == NOW + 3600
    assert 'access_code' not in second and 'code_hash' not in second


def test_same_label_still_has_distinct_codes_accounts_and_workspaces():
    with ThreadPoolExecutor(max_workers=4) as pool:
        created = list(pool.map(lambda _: accounts.create_reviewer('Identical label'), range(8)))
    for field in ('id', 'workspace', 'access_code'):
        assert len({item[field] for item in created}) == 8
    assert store.one('SELECT COUNT(*) n FROM workspaces')['n'] == 8


def test_admin_can_explicitly_bind_existing_corpus_without_copying_or_rewriting():
    store.execute('INSERT INTO workspaces VALUES(?,?,?)',('prepared','Prepared corpus',NOW))
    assert accounts.available_workspaces()[0]['id']=='prepared'
    created=accounts.create_reviewer('Prepared reviewer',workspace_id='prepared')
    assert created['workspace']=='prepared'
    assert accounts.lookup_reviewer(created['access_code'])['workspace']=='prepared'
    assert store.one('SELECT count(*) n FROM workspaces')['n']==1
    assert accounts.available_workspaces()==[]
    with pytest.raises(ValueError,match='已有'):accounts.create_reviewer('Second',workspace_id='prepared')
    with pytest.raises(ValueError,match='不存在'):accounts.create_reviewer('Missing',workspace_id='missing')
    assert store.one('SELECT count(*) n FROM review_accounts')['n']==1


@pytest.mark.parametrize('label', [None, 42, '', '   ', 'x' * 121])
def test_invalid_labels_leave_no_partial_workspace(label):
    with pytest.raises(ValueError):
        accounts.create_reviewer(label)
    assert store.rows('SELECT * FROM workspaces') == []
    assert store.rows('SELECT * FROM review_accounts') == []


@pytest.mark.parametrize('days', [None, True, False, 0, -1, 91, 1.5, '7'])
def test_invalid_expiry_is_rejected_without_account_creation(days):
    with pytest.raises(ValueError):
        accounts.create_reviewer('Fixture reviewer', days)
    assert accounts.list_reviewers() == []


@pytest.mark.parametrize('code', [None, b'code', '', ' ', "' OR 1=1 --", 'x' * 42, 'x' * 44, '中' * 43, '!' * 43])
def test_malformed_and_unknown_codes_are_denied(code):
    accounts.create_reviewer('Fixture reviewer')
    assert accounts.lookup_reviewer(code) is None
    assert accounts.lookup_reviewer('x' * 43) is None
    assert accounts.list_reviewers()[0]['last_login'] is None


def test_expiration_boundary_denies_code_and_preserves_account_history(isolated):
    created = accounts.create_reviewer('Fixture reviewer', days=1)
    isolated[0] = created['expires'] - 1
    assert accounts.lookup_reviewer(created['access_code']) is not None
    isolated[0] = created['expires']
    assert accounts.lookup_reviewer(created['access_code']) is None
    assert accounts.list_reviewers()[0]['status'] == 'expired'
    assert store.one('SELECT COUNT(*) n FROM review_accounts')['n'] == 1


def test_revoke_only_target_workspace_reviewer_sessions_and_keep_documents():
    first = accounts.create_reviewer('First')
    second = accounts.create_reviewer('Second')
    removed = {session(first['workspace']), session(first['workspace'])}
    kept = {session(first['workspace'], 'admin'), session(second['workspace']), session('legacy-space')}
    artifact_id = store.artifact(first['workspace'], None, 'note', 'Retained fixture note', {'text': 'fixture'})
    result = accounts.revoke_reviewer(first['id'])
    assert result['revoked'] is True and result['status'] == 'revoked'
    assert not {'access_code', 'code_hash'} & result.keys()
    remaining = {row['token_hash'] for row in store.rows('SELECT token_hash FROM sessions')}
    assert remaining == kept and not remaining & removed
    assert accounts.lookup_reviewer(first['access_code']) is None
    assert accounts.lookup_reviewer(second['access_code']) is not None
    assert store.one('SELECT id FROM artifacts WHERE id=?', (artifact_id,)) is not None
    assert accounts.revoke_reviewer(first['id'])['revoked'] is True


def test_unknown_revoke_has_no_side_effects():
    created = accounts.create_reviewer('Fixture reviewer')
    token_hash = session(created['workspace'])
    assert accounts.revoke_reviewer('missing-account') is None
    assert store.one('SELECT token_hash FROM sessions')['token_hash'] == token_hash
    assert accounts.list_reviewers()[0]['status'] == 'active'


def test_account_insert_failure_rolls_back_new_workspace(monkeypatch):
    created = accounts.create_reviewer('Existing')
    monkeypatch.setattr(accounts.secrets, 'token_urlsafe', lambda _: created['access_code'])
    with pytest.raises(sqlite3.IntegrityError):
        accounts.create_reviewer('Must roll back')
    assert store.one('SELECT COUNT(*) n FROM workspaces')['n'] == 1
    assert store.one('SELECT COUNT(*) n FROM review_accounts')['n'] == 1


@pytest.fixture
def api(monkeypatch, tmp_path):
    from services.api import app as module
    monkeypatch.setattr(module, 'DATA', tmp_path)
    monkeypatch.setattr(module, 'LOGIN_ATTEMPTS', {})
    monkeypatch.setenv('RT_ADMIN_CODE', 'fixture-admin-code')
    monkeypatch.setenv('RT_ACCESS_CODE', 'fixture-legacy-code')
    monkeypatch.setenv('RT_SECURE_COOKIE', 'false')
    with TestClient(module.app) as client:
        yield client


def admin_login(api):
    result = api.post('/api/v1/auth/login', json={'code': 'fixture-admin-code'})
    assert result.status_code == 200


def test_real_api_reviewer_management_is_admin_only(api):
    for method, path, body in [('get', '/api/v1/admin/reviewers', None),
                               ('post', '/api/v1/admin/reviewers', {'label': 'No permission', 'days': 1}),
                               ('post', '/api/v1/admin/reviewers/missing/revoke', {})]:
        response = getattr(api, method)(path, **({'json': body} if body is not None else {}))
        assert response.status_code == 401
    assert api.post('/api/v1/auth/login', json={'code': 'fixture-legacy-code'}).status_code == 200
    assert api.get('/api/v1/admin/reviewers').status_code == 403
    assert api.post('/api/v1/admin/reviewers', json={'label': 'Forbidden', 'days': 1}).status_code == 403
    assert api.post('/api/v1/admin/reviewers/missing/revoke', json={}).status_code == 403
    assert accounts.list_reviewers() == []


def test_real_api_create_returns_secret_once_and_list_is_metadata_only(api):
    admin_login(api)
    result = api.post('/api/v1/admin/reviewers', json={'label': 'Fixture reviewer', 'days': 3})
    assert result.status_code in (200, 201)
    created = result.json()
    assert 'access_code' in created and 'code_hash' not in created
    listed = api.get('/api/v1/admin/reviewers')
    assert listed.status_code == 200
    assert created['access_code'] not in listed.text
    assert 'code_hash' not in listed.text
    assert listed.json()[0]['id'] == created['id']


@pytest.mark.parametrize('prior_code', ['fixture-legacy-code', 'fixture-admin-code'])
def test_real_api_invite_overrides_anonymous_workspace_and_ignores_supplied_id(api, prior_code):
    created = accounts.create_reviewer('Fixture reviewer')
    prior = api.post('/api/v1/auth/login', json={'code': prior_code}).json()['workspace']
    result = api.post('/api/v1/auth/login', json={'code': created['access_code'], 'workspace': prior})
    assert result.status_code == 200
    assert result.json()['workspace'] == created['workspace']
    assert result.json()['role'] == 'reviewer'
    assert api.get('/api/v1/auth/session').json()['workspace'] == created['workspace']


def test_real_api_valid_reviewer_invite_cannot_gain_admin_role_from_global_code_collision(api, monkeypatch):
    created = accounts.create_reviewer('Fixture reviewer')
    monkeypatch.setenv('RT_ADMIN_CODE', created['access_code'])
    result = api.post('/api/v1/auth/login', json={'code': created['access_code']})
    assert result.status_code == 200
    assert result.json()['role'] == 'reviewer'
    assert api.get('/api/v1/admin/reviewers').status_code == 403


def test_real_api_logout_and_new_browser_return_to_same_private_workspace(api):
    created = accounts.create_reviewer('Fixture reviewer')
    other = accounts.create_reviewer('Other reviewer')
    store.artifact(created['workspace'], None, 'note', 'Only first reviewer', {'text': 'fixture'})
    assert api.post('/api/v1/auth/login', json={'code': created['access_code']}).status_code == 200
    assert [item['title'] for item in api.get('/api/v1/artifacts').json()] == ['Only first reviewer']
    assert api.post('/api/v1/auth/logout').status_code == 200
    assert api.get('/api/v1/auth/session').status_code == 401
    api.cookies.clear()
    assert api.post('/api/v1/auth/login', json={'code': created['access_code']}).json()['workspace'] == created['workspace']
    from services.api import app as module
    with TestClient(module.app) as new_browser:
        assert new_browser.post('/api/v1/auth/login', json={'code': created['access_code']}).json()['workspace'] == created['workspace']
        assert new_browser.post('/api/v1/auth/login', json={'code': other['access_code'], 'workspace': created['workspace']}).json()['workspace'] == other['workspace']
        assert new_browser.get('/api/v1/artifacts').json() == []


def test_real_api_expired_and_revoked_invites_and_sessions_are_denied(api, isolated):
    created = accounts.create_reviewer('Fixture reviewer', days=1)
    assert api.post('/api/v1/auth/login', json={'code': created['access_code']}).status_code == 200
    assert store.one('SELECT expires FROM sessions WHERE workspace=?', (created['workspace'],))['expires'] == created['expires']
    isolated[0] = created['expires']
    assert api.get('/api/v1/auth/session').status_code == 401
    assert api.post('/api/v1/auth/login', json={'code': created['access_code']}).status_code == 401
    second = accounts.create_reviewer('Revoked reviewer')
    assert api.post('/api/v1/auth/login', json={'code': second['access_code']}).status_code == 200
    accounts.revoke_reviewer(second['id'])
    assert api.get('/api/v1/auth/session').status_code == 401
    assert api.post('/api/v1/auth/login', json={'code': second['access_code']}).status_code == 401


def test_real_api_revoke_does_not_revoke_admin_or_other_reviewer(api):
    admin_login(api)
    created = accounts.create_reviewer('Revoked reviewer')
    other = accounts.create_reviewer('Other reviewer')
    from services.api import app as module
    with TestClient(module.app) as reviewer:
        assert reviewer.post('/api/v1/auth/login', json={'code': other['access_code']}).status_code == 200
        result = api.post(f"/api/v1/admin/reviewers/{created['id']}/revoke", json={})
        assert result.status_code == 200
        assert result.json()['revoked'] is True
        assert 'access_code' not in result.text and 'code_hash' not in result.text
        assert api.get('/api/v1/admin/reviewers').status_code == 200
        assert reviewer.get('/api/v1/auth/session').status_code == 200
