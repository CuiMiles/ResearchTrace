"""The workflow must never infer a passed execution from missing/broken reports."""
import json
import pytest

from services.api import workflow_report
from tests.integration.test_admin_acceptance_api import _make_client


def test_workflow_auth_and_empty_report(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow_report, 'REPORT_PATH', tmp_path / 'missing.json')
    with _make_client(tmp_path, monkeypatch) as client:
        assert client.get('/api/v1/admin/workflow').status_code == 401
        client.post('/api/v1/auth/login', json={'code': 'reviewer-only-code'}).raise_for_status()
        assert client.get('/api/v1/admin/workflow').status_code == 403
        client.post('/api/v1/auth/login', json={'code': 'admin-only-code'}).raise_for_status()
        response = client.get('/api/v1/admin/workflow')
        response.raise_for_status()
        report = response.json()
        assert len(report['steps']) == 10
        assert all(s['status'] == 'NOT RUN' and s['runs'] == [] for s in report['steps'])
        assert report['test_execution_started'] is False
        assert report['dataset'] is None


def test_workflow_keeps_blocked_and_filters_evidence_links(tmp_path, monkeypatch):
    path = tmp_path / 'workflow.json'
    monkeypatch.setattr(workflow_report, 'REPORT_PATH', path)
    path.write_text(json.dumps({'test_execution_started': True, 'steps': [{
        'id': 'parse', 'runs': [{'id': 'actual-test', 'status': 'PASS',
          'evidence_files': ['.env', '../.env', 'https://invalid/evidence.json',
                            'evidence/ubuntu24/acceptance.json'], 'screenshots': []},
          {'id': 'guarded-gpu', 'status': 'BLOCKED', 'evidence_files': []}]}]}))
    result = workflow_report.build_workflow_report()
    parse = next(s for s in result['steps'] if s['id'] == 'parse')
    assert parse['status'] == 'BLOCKED'
    assert len(parse['runs']) == 2
    assert [x['path'] for x in parse['runs'][0]['evidence_files']] == ['evidence/ubuntu24/acceptance.json']
    path.write_text('partial invalid JSON')
    broken = workflow_report.build_workflow_report()
    assert broken['load_error']
    assert all(s['status'] == 'NOT RUN' for s in broken['steps'])


@pytest.mark.parametrize('replacement_status,replacement_hash,expected', [
    ('PASS', 'same-file', 'PASS'), ('FAIL', 'same-file', 'FAIL'),
    ('PASS', 'another-file', 'FAIL'),
])
def test_failed_history_resolves_only_with_passed_retest_of_same_file(tmp_path, monkeypatch, replacement_status, replacement_hash, expected):
    path = tmp_path/'workflow.json'
    monkeypatch.setattr(workflow_report, 'REPORT_PATH', path)
    path.write_text(json.dumps({'steps': [{'id': 'parse', 'runs': [
        {'id': 'first', 'status': 'FAIL', 'resolved_by': 'retest', 'files': [{'sha256': 'same-file'}]},
        {'id': 'retest', 'status': replacement_status, 'files': [{'sha256': replacement_hash}]},
    ]}]}))
    step = workflow_report.build_workflow_report()['steps'][2]
    assert step['status']==expected
    assert step['runs'][0]['status']=='FAIL'  # The original evidence remains visible.
