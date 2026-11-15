"""Deterministic synthetic parsing tests; never claim these as live library runs."""
import io
import json

import pytest
from reportlab.pdfgen import canvas

from services.api import documents, retrieval, snapshots, store


@pytest.fixture
def parsed(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path)
    monkeypatch.setattr(documents,'DATA',tmp_path)
    monkeypatch.setenv('RT_DISABLE_DENSE','true')
    store.migrate()
    f=io.BytesIO();p=canvas.Canvas(f)
    for i in range(2):
        p.drawString(40,700,'Legacy immutable evidence from page '+str(i));p.showPage()
    p.save()
    u=documents.upload_document('a','fresh.pdf',f.getvalue())
    documents.parse_document(store.one('SELECT * FROM runs WHERE id=?',(u['run_id'],)))
    return u['document']['id']


def fake_page(path,index,engine,**kwargs):
    return {'engine':engine,'version':'UNIT_TEST_ONLY','device':'cpu','models':['fixture'],
            'lines':[{'text':'Updated snapshot evidence page '+str(index),'confidence':.99,'bbox':[.1,.1,.8,.2]}]}


def test_reparse_keeps_cited_blocks_and_search_scope(parsed,monkeypatch):
    from services.api import enhanced_parsing
    monkeypatch.setattr(enhanced_parsing,'external_page',fake_page)
    old=store.rows('SELECT * FROM blocks WHERE version_id=?',(parsed,))
    store.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?)',('e','a','c',parsed,old[0]['id'],0,old[0]['text'],'located'))
    queued=snapshots.queue_parse('a',parsed,'paddleocr','cpu','revision-one')
    again=snapshots.queue_parse('a',parsed,'paddleocr','cpu','revision-one')
    assert queued['id']==again['id']
    with pytest.raises(ValueError):snapshots.queue_parse('a',parsed,'native','cpu','revision-one')
    result=documents.parse_document(store.one('SELECT * FROM runs WHERE id=?',(queued['id'],)))
    assert result['status']=='ready'
    assert old==store.rows('SELECT * FROM blocks WHERE version_id=? AND id NOT IN (SELECT block_id FROM block_parses)',(parsed,))
    assert snapshots.selected_parse('a',parsed)['id']==queued['parse_id']
    current=retrieval.retrieve('a',[parsed],'Updated')['blocks']
    assert current and all(b['parse_id']==queued['parse_id'] for b in current)
    assert all('Legacy' not in b['text'] for b in current)
    assert snapshots.snapshot_blocks('a',parsed,parsed)[0]['id']==old[0]['id']
    assert json.loads(old[0]['bbox'])==json.loads(store.one('SELECT bbox FROM blocks WHERE id=?',(old[0]['id'],))['bbox'])
    store.migrate()
    assert snapshots.selected_parse('a',parsed)['id']==queued['parse_id']
    assert len(snapshots.list_parses('a',parsed))==2
    with pytest.raises(ValueError):snapshots.snapshot_blocks('b',parsed,queued['parse_id'])


def test_cancel_resume_checkpoints_and_failed_revision_never_publishes(parsed,monkeypatch):
    from services.api import enhanced_parsing
    q=snapshots.queue_parse('a',parsed,'paddleocr','cpu','cancelled-revision')
    def cancel_first(*args,**kwargs):
        value=fake_page(*args,**kwargs)
        store.execute("UPDATE runs SET status='cancelled' WHERE id=?",(q['id'],))
        return value
    monkeypatch.setattr(enhanced_parsing,'external_page',cancel_first)
    run=store.one('SELECT * FROM runs WHERE id=?',(q['id'],))
    result=documents.parse_document(run)
    assert result['status']=='cancelled'
    assert snapshots.selected_parse('a',parsed)['id']==parsed
    before=snapshots.snapshot_blocks('a',parsed,q['parse_id'])
    monkeypatch.setattr(enhanced_parsing,'external_page',fake_page)
    store.execute("UPDATE runs SET status='running' WHERE id=?",(q['id'],))
    result=documents.parse_document(run)
    assert result['status']=='ready'
    after=snapshots.snapshot_blocks('a',parsed,q['parse_id'])
    assert after[:len(before)]==before
    assert len(after)==2


def test_existing_native_snapshot_is_never_rewritten(parsed):
    before=store.rows('SELECT * FROM blocks WHERE version_id=?',(parsed,))
    run={'id':store.one('SELECT id FROM runs WHERE json_extract(payload,\'$.version_id\')=?',(parsed,))['id'],'workspace':'a','payload':{'version_id':parsed}}
    assert documents.parse_document(run)['reused']
    assert before==store.rows('SELECT * FROM blocks WHERE version_id=?',(parsed,))
