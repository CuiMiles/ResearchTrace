"""Cloud spaces and seeded copies cannot mix models or spend new quota."""
import io
import json
import numpy as np
import pytest
from reportlab.pdfgen import canvas
from services.api import store,documents,jobs,models,index_generations as idx,reviewer_accounts
from services.api.embedding_providers import GeminiRetrievalProvider,fingerprint


@pytest.fixture
def parsed(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path);monkeypatch.setattr(documents,'DATA',tmp_path);store.migrate()
    store.execute('INSERT INTO workspaces VALUES(?,?,?)',('source','Public fixture corpus',1))
    buf=io.BytesIO();c=canvas.Canvas(buf);c.drawString(30,700,'Training uses eight GPUs, with numerical conditions and a source citation.');c.save()
    upload=documents.upload_document('source','unseen.pdf',buf.getvalue(),index_dense=False)
    jobs.work_once(pool='documents')
    def embed(texts,rid,task='RETRIEVAL_DOCUMENT'):
        return {'vectors':[[1.0]+[0.0]*767 for _ in texts],'model':'gemini-embedding-001','dimension':768}
    monkeypatch.setattr(models,'embed',embed)
    return upload['document']['id']


def test_cloud_generation_search_and_seed_preserve_vectors_and_scope(parsed,monkeypatch):
    p=GeminiRetrievalProvider();g=idx.build('source',[parsed],provider=p)
    before=store.rows('SELECT id,text,bbox FROM blocks WHERE workspace=?',('source',))
    original_vectors=store.rows('SELECT vector FROM retrieval_vectors ORDER BY chunk_id')
    account=reviewer_accounts.create_reviewer('Seeded fixture',seed_workspace_id='source')
    target=account['workspace'];assert target!='source'
    copied=store.one('SELECT * FROM versions WHERE workspace=?',(target,));assert copied['id']!=parsed
    copied_vectors=store.rows('SELECT v.vector FROM retrieval_vectors v JOIN retrieval_chunks c ON c.id=v.chunk_id WHERE c.workspace=? ORDER BY c.id',(target,))
    assert sorted(r['vector'] for r in copied_vectors)==sorted(r['vector'] for r in original_vectors)
    assert store.rows('SELECT id,text,bbox FROM blocks WHERE workspace=?',('source',))==before
    hits,info=idx.dense_search(target,[copied['id']],'GPU',provider=p)
    assert hits and all(b['workspace']==target for b in hits)
    assert all(b['id'] not in {r['id'] for r in before} for b in hits)
    with pytest.raises(ValueError):idx.build(target,[parsed],provider=p)
    assert not store.rows('SELECT * FROM quota')
    assert not store.rows('SELECT * FROM artifacts WHERE workspace=?',(target,))


def test_fixed_source_chunks_keep_same_inputs_but_not_other_model_vectors(parsed):
    p=GeminiRetrievalProvider();g=idx.build('source',[parsed],provider=p)
    other=GeminiRetrievalProvider()
    original=other.descriptor
    other.descriptor=lambda:{**original(),'revision':'different-provider-revision'}
    copied=idx.build('source',[parsed],provider=other,source_generation_id=g['id'])
    left=store.rows('SELECT text,retrieval_text FROM retrieval_chunks WHERE generation_id=? ORDER BY text',(g['id'],))
    right=store.rows('SELECT text,retrieval_text FROM retrieval_chunks WHERE generation_id=? ORDER BY text',(copied['id'],))
    assert left==right and g['fingerprint']!=copied['fingerprint']
    assert g['id']!=copied['id'] and copied['coverage_complete']


def test_multibyte_split_is_complete_with_declared_upper_bound():
    p=GeminiRetrievalProvider();text='中文🙂 formula β1 training '*200
    parts=p.split(text,64,12)
    assert parts[0]['start']==0 and parts[-1]['end']==len(text)
    for part in parts:
        assert text[part['start']:part['end']]==part['text']
        assert len(part['text'].encode())==part['token_count']<=64


def test_failed_seed_rolls_back_new_invitation(parsed):
    before=store.one('SELECT count(*) n FROM workspaces')['n']
    with pytest.raises(ValueError):reviewer_accounts.create_reviewer('Bad seed',seed_workspace_id='foreign-missing')
    assert store.one('SELECT count(*) n FROM workspaces')['n']==before
    assert not store.rows('SELECT * FROM review_accounts')
