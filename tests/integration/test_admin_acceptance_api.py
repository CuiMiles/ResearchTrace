"""Admin acceptance dashboard API authorization, path safety, and payload checks."""
from fastapi.testclient import TestClient
from services.api import app, documents, store


def _make_client(tmp_path, monkeypatch):
    for mod in (app, documents, store):
        monkeypatch.setattr(mod, 'DATA', tmp_path)
    monkeypatch.setattr(app, 'LOGIN_ATTEMPTS', {})
    monkeypatch.setenv('RT_ACCESS_CODE', 'reviewer-only-code')
    monkeypatch.setenv('RT_ADMIN_CODE', 'admin-only-code')
    return TestClient(app.app)


def test_admin_acceptance_requires_admin_and_serves_safe_evidence(tmp_path, monkeypatch):
    with _make_client(tmp_path, monkeypatch) as c:
        assert c.get('/api/v1/admin/acceptance').status_code == 401
        assert c.get('/api/v1/admin/evidence-file', params={'path': 'evidence/ubuntu24/acceptance.json'}).status_code == 401

        c.post('/api/v1/auth/login', json={'code': 'reviewer-only-code'}).raise_for_status()
        assert c.get('/api/v1/admin/acceptance').status_code == 403
        assert c.get('/api/v1/admin/evidence-file', params={'path': 'evidence/ubuntu24/acceptance.json'}).status_code == 403

        c.post('/api/v1/auth/login', json={'code': 'admin-only-code'}).raise_for_status()
        r = c.get('/api/v1/admin/acceptance')
        assert r.status_code == 200
        body = r.json()
        assert body['summary']['total'] == 64
        assert body['summary']['pass'] >= 1
        assert len(body['modules']) == 7
        assert len(body['cases']) == 64

        ok_json = c.get('/api/v1/admin/evidence-file', params={'path': 'evidence/ubuntu24/acceptance.json'})
        assert ok_json.status_code == 200
        ok_png = c.get('/api/v1/admin/evidence-file', params={'path': 'evidence/ubuntu24/browser/graph-20-nodes-1440.png'})
        assert ok_png.status_code == 200
        assert ok_png.headers['content-type'].startswith('image/png')

        for blocked in ('.env', '../.env', 'data/researchtrace.sqlite', 'services/api/app.py', 'evidence/private/secret.json'):
            assert c.get('/api/v1/admin/evidence-file', params={'path': blocked}).status_code == 404
