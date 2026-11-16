"""Explicit provider fixtures test index safety, not real-model retrieval quality."""
import io
import json
import numpy as np
import pytest
from reportlab.pdfgen import canvas
from services.api import documents,index_generations as indices,store,retrieval
from services.api.embedding_providers import fingerprint,RetrievalUnavailable


class FixtureProvider:
    model='FIXTURE_NOT_A_REAL_MODEL'
    revision='a'*40
    fail=False
    def descriptor(self):
        return dict(model_id=self.model,revision=self.revision,tokenizer_revision=self.revision,
                    query_template='fixture-query',document_template='fixture-document',pooling='fixture',normalization='l2',dimension=3,dtype='float32')
    def split(self,text,max_tokens,overlap=32):
        # Character slicing is intentionally a fixture, never the production tokenizer.
        return [{'text':text[start:start+80],'start':start,'end':min(len(text),start+80),'token_count':40} for start in range(0,len(text),80)]
    def embed(self,texts,task):
        if self.fail:raise RetrievalUnavailable('fixture failure, no inference')
        vectors=[]
        for text in texts:
            vector=np.asarray([1+text.lower().count('gpu'),1+text.lower().count('author'),1],dtype=float)
            vectors.append((vector/np.linalg.norm(vector)).tolist())
        return {'vectors':vectors,'fingerprint':fingerprint(self.descriptor())}


@pytest.fixture
def corpus(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path);monkeypatch.setattr(documents,'DATA',tmp_path);store.migrate()
    pdf=io.BytesIO();c=canvas.Canvas(pdf)
    c.drawString(50,700,'Authors and institutions are listed in the frontmatter.')
    c.drawString(50,650,'The trained model used eight GPUs. This is an explicit fixture.')
    c.save()
    upload=documents.upload_document('workspace','random.pdf',pdf.getvalue(),index_dense=False)
    documents.parse_document(store.one('SELECT * FROM runs WHERE id=?',(upload['run_id'],)))
    return upload['document']['id']


def test_generation_complete_activate_and_exact_search(corpus):
    provider=FixtureProvider();before=store.rows('SELECT id,text,bbox FROM blocks ORDER BY id')
    result=indices.build('workspace',[corpus],provider=provider)
    assert result['coverage_complete'] and result['vector_count']>0
    assert result['expected_blocks']==result['covered_blocks']
    hits,info=indices.dense_search('workspace',[corpus],'GPU',provider=provider)
    assert hits and all(b['version_id']==corpus for b in hits)
    assert info['fingerprint']==fingerprint(provider.descriptor())
    assert before==store.rows('SELECT id,text,bbox FROM blocks ORDER BY id')


def test_failed_staging_index_never_replaces_active_generation(corpus):
    provider=FixtureProvider();old=indices.build('workspace',[corpus],provider=provider)['id']
    provider.revision='b'*40  # New model cannot reuse old-fingerprint vectors.
    provider.fail=True
    with pytest.raises(RetrievalUnavailable):indices.build('workspace',[corpus],provider=provider)
    assert store.one('SELECT generation_id FROM active_retrieval_indices')['generation_id']==old
    failed=store.one("SELECT * FROM index_generations WHERE status='failed'")
    provider.fail=False
    new=indices.build('workspace',[corpus],provider=provider,generation_id=failed['id'])
    assert new['coverage_complete']
    indices.activate_generation('workspace',old)
    assert store.one('SELECT generation_id FROM active_retrieval_indices')['generation_id']==old


def test_revision_mismatch_and_workspace_are_never_mixed(corpus):
    provider=FixtureProvider();generation=indices.build('workspace',[corpus],provider=provider)['id']
    provider.revision='b'*40
    hits,info=indices.dense_search('workspace',[corpus],'GPU',provider=provider)
    assert not hits and info['status']=='unindexed'
    with pytest.raises(ValueError):indices.activate_generation('other',generation)
    with pytest.raises(ValueError):indices.build('other',[corpus],provider=provider)


def test_silent_tail_truncation_cannot_activate(corpus,monkeypatch):
    provider=FixtureProvider()
    monkeypatch.setattr(provider,'split',lambda text,**kw:[{'text':text[:3],'start':0,'end':3,'token_count':3}])
    with pytest.raises(RetrievalUnavailable,match='尾部'):indices.build('workspace',[corpus],provider=provider)
    assert not store.rows('SELECT * FROM active_retrieval_indices')


def test_active_parse_change_prevents_stale_activation(corpus):
    provider=FixtureProvider();generation=indices.build('workspace',[corpus],provider=provider,activate=False)['id']
    store.execute('UPDATE active_parses SET parse_id=? WHERE version_id=?',('different-immutable-parse',corpus))
    with pytest.raises(ValueError,match='解析已变化'):indices.activate_generation('workspace',generation)
    assert not store.rows('SELECT * FROM active_retrieval_indices')


def test_symmetric_chinese_sparse_index_and_literal_source(corpus):
    from services.api import sparse_index
    block=store.one('SELECT * FROM blocks WHERE version_id=? LIMIT 1',(corpus,))
    store.execute('INSERT INTO blocks VALUES(?,?,?,?,?,?,?,?,?,?,?)',('chinese','workspace',corpus,0,'[0,0,1,1]','paragraph',500,'本文使用检索增强生成方法进行问答','fixture','native','{}'))
    result,_=sparse_index.search('workspace',[corpus],'检索增强',limit=10)
    assert any(b['id']=='chinese' and b['text']=='本文使用检索增强生成方法进行问答' for b in result)
    assert store.one('SELECT text FROM blocks WHERE id=?',(block['id'],))['text']==block['text']


def test_missing_local_service_degrades_without_cloud_request(corpus,monkeypatch):
    from services.api import models
    monkeypatch.setenv('RT_EMBED_PROVIDER','local');monkeypatch.delenv('RT_RETRIEVAL_BASE',raising=False)
    monkeypatch.setattr(models,'embed',lambda *a,**k:pytest.fail('Local index cannot silently call a cloud embedder'))
    result=retrieval.retrieve('workspace',[corpus],'训练用了多少张显卡')
    assert result['blocks'] and result['mode']=='keyword'
    assert result['dense_index']['status']=='unavailable'
    assert result['query_term_expansion']
    assert not store.rows('SELECT * FROM quota')
