"""No providers: model output fixtures exercise persistence and cancellation races."""
import io
import json

import pytest
from reportlab.pdfgen import canvas
from services.api import documents, enhanced_parsing, snapshots, store


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    monkeypatch.setattr(documents, 'DATA', tmp_path)
    monkeypatch.setenv('RT_DISABLE_DENSE', 'true')
    store.migrate()
    f = io.BytesIO(); pdf = canvas.Canvas(f)
    for i in range(2):
        pdf.drawString(40, 700, f'Immutable source evidence page {i}'); pdf.showPage()
    pdf.save()
    u = documents.upload_document('w', 'source.pdf', f.getvalue(), index_dense=False)
    documents.parse_document(store.one('SELECT * FROM runs WHERE id=?', (u['run_id'],)))
    return u['document']['id']


def response(text):
    return {'engine': 'mineru', 'version': 'FIXTURE_ONLY', 'device': 'cpu',
            'models': ['fixture'], 'blocks': [{'text': text, 'type': 'paragraph',
            'bbox': [.1, .1, .9, .2], 'metadata': {}}]}


def queue(vid, key):
    q = snapshots.queue_parse('w', vid, 'mineru', 'cpu', key)
    return q, store.one('SELECT * FROM runs WHERE id=?', (q['id'],))


def test_interruption_after_failed_page_can_resume_without_rewriting(source, monkeypatch):
    q, run = queue(source, 'empty-page-checkpoint')
    def first(path, index, engine, **kwargs):
        if index == 1:
            raise ValueError('Fixture interruption after committed low-quality page')
        return response('')
    monkeypatch.setattr(enhanced_parsing, 'external_page', first)
    with pytest.raises(ValueError, match='interruption'):
        documents.parse_document(run)
    before = snapshots.snapshot_blocks('w', source, q['parse_id'])
    page_before = store.one('SELECT * FROM parse_pages WHERE parse_id=? AND page_index=0', (q['parse_id'],))
    calls = []
    def resume(path, index, engine, **kwargs):
        calls.append(index); return response('Resumed page evidence')
    monkeypatch.setattr(enhanced_parsing, 'external_page', resume)
    result = documents.parse_document(run)
    assert result['status'] == 'partial'
    assert calls == [1]  # Already committed low-quality output is immutable too.
    assert snapshots.snapshot_blocks('w', source, q['parse_id'])[:len(before)] == before
    assert store.one('SELECT * FROM parse_pages WHERE parse_id=? AND page_index=0', (q['parse_id'],)) == page_before
    assert snapshots.selected_parse('w', source)['id'] == source
    assert result['failed_pages'] == [{'page_index': 0, 'status': 'empty_or_failed'}]


@pytest.mark.parametrize('action', ['cancel', 'delete'])
def test_last_page_cancellation_or_deletion_never_publishes(source, monkeypatch, action):
    q, run = queue(source, 'last-page-' + action)
    def parse(path, index, engine, **kwargs):
        if index == 1:
            if action == 'delete':
                store.execute('UPDATE versions SET deleted=1 WHERE id=?', (source,))
                store.execute('DELETE FROM block_fts WHERE id IN (SELECT id FROM blocks WHERE version_id=?)', (source,))
            store.execute("UPDATE runs SET status='cancelled' WHERE id=?", (q['id'],))
        return response('Unpublished new revision')
    monkeypatch.setattr(enhanced_parsing, 'external_page', parse)
    result = documents.parse_document(run)
    assert result['status'] == 'cancelled'
    assert store.one('SELECT parse_id FROM active_parses WHERE version_id=?', (source,))['parse_id'] == source
    assert store.one('SELECT status FROM parses WHERE id=?', (q['parse_id'],))['status'] == 'cancelled'
    assert store.one('SELECT count(*) n FROM parse_pages WHERE parse_id=?', (q['parse_id'],))['n'] == 1
    if action == 'delete':
        assert store.one('SELECT count(*) n FROM block_fts WHERE id IN (SELECT id FROM blocks WHERE version_id=?)', (source,))['n'] == 0


def test_publication_does_not_overwrite_concurrent_document_edits(source, monkeypatch):
    q, run = queue(source, 'concurrent-metadata')
    def parse(path, index, engine, **kwargs):
        if index == 1:
            # Edit while parser runs: user changes belong to the document, not parser.
            meta=json.loads(store.one('SELECT metadata FROM versions WHERE id=?',(source,))['metadata'])
            meta.update(tags=['user-edited'], custom_field='preserve-me')
            store.execute('UPDATE versions SET metadata=? WHERE id=?',(json.dumps(meta),source))
        return response('Parsed evidence')
    monkeypatch.setattr(enhanced_parsing, 'external_page', parse)
    assert documents.parse_document(run)['status'] == 'ready'
    meta=json.loads(store.one('SELECT metadata FROM versions WHERE id=?',(source,))['metadata'])
    assert meta['tags'] == ['user-edited'] and meta['custom_field'] == 'preserve-me'


def test_resume_rejects_mixed_parser_versions(source, monkeypatch):
    q, run = queue(source, 'pinned-parser-version')
    def interrupted(path, index, engine, **kwargs):
        if index == 1:
            raise ValueError('interrupted')
        return response('First page from engine version A')
    monkeypatch.setattr(enhanced_parsing, 'external_page', interrupted)
    with pytest.raises(ValueError, match='interrupted'):
        documents.parse_document(run)
    before=snapshots.snapshot_blocks('w', source, q['parse_id'])
    def upgraded(*args, **kwargs):
        data=response('Second page from engine version B');data['version']='CHANGED_VERSION'
        return data
    monkeypatch.setattr(enhanced_parsing, 'external_page', upgraded)
    with pytest.raises(ValueError, match='版本、模型或设备已变化'):
        documents.parse_document(run)
    assert snapshots.snapshot_blocks('w', source, q['parse_id']) == before
    assert snapshots.selected_parse('w', source)['id'] == source
