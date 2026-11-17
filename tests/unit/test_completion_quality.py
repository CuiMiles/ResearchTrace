import json
import pytest
from services.api import store,models,recommendations
from services.api.future_work import coverage_matrix
from services.api.embedding_providers import GeminiRetrievalProvider


def test_coverage_requires_same_paper_supported_claim_and_verified_later():
    contexts=[{'id':'later','title':'New paper'},{'id':'overlap','title':'Ambiguous date'}]
    claims={'claims':[{'id':'c','text':'Only a bounded claim.','review':{'status':'supported'},'evidence':[{'version_id':'later','block_id':'b'}]}]}
    raw={'coverage_assessments':[{'version_id':'later','category':'partial','claim_ids':['c']},{'version_id':'overlap','category':'direct','claim_ids':['c']}]}
    rows=coverage_matrix(raw,claims,contexts,[{'version_id':'later','status':'later'},{'version_id':'overlap','status':'overlap'}])
    assert [r['category'] for r in rows]==['partial','insufficient']
    claims['claims'][0]['review']['status']='insufficient'
    assert coverage_matrix(raw,claims,contexts,[{'version_id':'later','status':'later'}])[0]['category']=='insufficient'
    raw['coverage_assessments'][0]['version_id']='outside'
    with pytest.raises(ValueError):coverage_matrix(raw,claims,contexts,[])


def test_cloud_long_input_count_rejects_before_embedding(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path);store.migrate()
    attempts=[]
    monkeypatch.setattr(models,'request',lambda *a:({'totalTokens':2049},'fixture'))
    monkeypatch.setattr(models,'embed',lambda *a,**kw:attempts.append(a))
    with pytest.raises(ValueError):GeminiRetrievalProvider().embed(['中'*800],'RETRIEVAL_DOCUMENT')
    assert attempts==[]


def test_recommendation_reasons_bound_to_real_metadata_and_feedback(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path);store.migrate()
    store.execute('INSERT INTO workspaces VALUES(?,?,?)',('w','fixture',1))
    store.execute('INSERT INTO runs(id,workspace,kind,status,payload,created,updated) VALUES(?,?,?,?,?,?,?)',('r','w','recommendation','running','{}',1,1))
    from services.api import research
    monkeypatch.setattr(research,'_arxiv',lambda *a,**kw:[{'identity':'arxiv:2601.00001','title':'Paper','abstract':'Code https://github.com/example/paper','comments':'','published':'2026-01-01'}])
    monkeypatch.setattr(models,'generate',lambda *a,**kw:{'text':json.dumps({'reasons':[{'identity':'arxiv:2601.00001','reason':'The abstract is related; fulltext not reviewed.'}]}),'model':'fixture'})
    result=recommendations.run({'id':'r','workspace':'w','payload':{'query':'research'}})
    assert result['results'][0]['code_clues']==['https://github.com/example/paper']
    assert result['results'][0]['code_status']=='metadata_link_only_not_reproduction_verified'
    store.execute('INSERT INTO feedback VALUES(?,?,?)',('w','arxiv:2601.00001',-1))
    assert research._rank('w','research',result['source_candidates'])==[]
    assert store.one('SELECT count(*) n FROM artifacts')['n']==1


def test_embedding_batch_units_reserve_actual_item_count(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path);store.migrate()
    monkeypatch.setenv('RT_MODEL_DAILY_LIMITS',json.dumps({'gemini-embedding-001':32}))
    monkeypatch.setenv('RT_MODEL_PROJECT_LIMITS',json.dumps({'gemini-embedding-001':[100,30000,1000]}))
    first=models.reserve('fixture-project','gemini-embedding-001',100,None,now=10000,request_units=32)
    store.execute("UPDATE quota SET status='ok' WHERE id=?",(first,))
    with pytest.raises(models.QuotaRefusal) as refused:
        models.reserve('another-project','gemini-embedding-001',100,None,now=10061,request_units=1)
    assert refused.value.code=='model_daily'
    assert store.one('SELECT units FROM quota_request_units WHERE quota_id=?',(first,))['units']==32
    # Counting tokens remains a recorded HTTP attempt with separate request units.
    assert models.reserve('fixture-project','gemini-embedding-001',100,None,now=10061,request_units=0)


def test_cloud_bundle_preserves_every_original_span_with_bounded_unicode():
    from services.api.index_generations import packed_cloud_chunks
    blocks=[{'id':'a','type':'paragraph','text':'中文🙂 beta1 '*350},{'id':'b','type':'heading','text':'Conditions'},{'id':'c','type':'table','text':'GPU | 8\nunits: cards\n'},{'id':'d','type':'paragraph','text':'The final paragraph.'}]
    chunks=packed_cloud_chunks(blocks,'A long academic title',GeminiRetrievalProvider())
    assert chunks and all(len(c['retrieval_text'].encode())<=2048 for c in chunks)
    for b in blocks:
        spans=sorted((s,e) for c in chunks for bid,s,e in c['spans'] if bid==b['id'])
        cursor=0
        for start,end in spans:
            assert start<=cursor;cursor=max(cursor,end)
        assert cursor==len(b['text'])


def test_native_counted_cloud_pack_resplits_and_keeps_original_offsets(monkeypatch):
    from services.api.index_generations import counted_cloud_chunks
    p=GeminiRetrievalProvider()
    monkeypatch.setattr(p,'content_token_bound',lambda value:len(value.encode())+1)
    blocks=[{'id':'a','type':'paragraph','text':'a'*7000},{'id':'b','type':'table','text':'中文🙂 units GPU '*400}]
    result=counted_cloud_chunks(blocks,'Fixture',p)
    assert len(result)>2 and all(c['token_count']<=2000 for c in result)
    for b in blocks:
        cursor=0
        for start,end in sorted((s,e) for c in result for bid,s,e in c['spans'] if bid==b['id']):
            assert start<=cursor;cursor=max(cursor,end)
        assert cursor==len(b['text'])


def test_cloud_packing_rejects_a_truncated_split(monkeypatch):
    from services.api.index_generations import counted_cloud_chunks
    from services.api.embedding_providers import RetrievalUnavailable
    p=GeminiRetrievalProvider()
    monkeypatch.setattr(p,'split',lambda *a,**k:[{'text':'abc','start':0,'end':3,'token_count':3}])
    with pytest.raises(RetrievalUnavailable,match='尾部'):
        counted_cloud_chunks([{'id':'a','type':'paragraph','text':'abcdef'}],'Fixture',p)


def test_free_token_count_survives_embedding_daily_cap_without_extra_units(tmp_path,monkeypatch):
    import httpx
    monkeypatch.setattr(store,'DATA',tmp_path);store.migrate()
    monkeypatch.setenv('RT_MODEL_DAILY_LIMITS',json.dumps({'gemini-embedding-001':1}))
    monkeypatch.setenv('RT_MODEL_PROJECT_LIMITS',json.dumps({'gemini-embedding-001':[100,30000,1]}))
    monkeypatch.setenv('GEMINI_PROJECT_1','fixture-project');monkeypatch.setenv('GEMINI_API_KEY','fixture-key')
    monkeypatch.delenv('GEMINI_API_KEY2',raising=False)
    q=models.reserve('fixture-project','gemini-embedding-001',10,None,now=models.time.time()-100,request_units=1)
    store.execute("UPDATE quota SET status='ok' WHERE id=?",(q,))
    monkeypatch.setattr(models,'client',lambda:httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'totalTokens':1500}))))
    response,_=models.request('gemini-embedding-001','countTokens',{'contents':[{'role':'user','parts':[{'text':'input'}]}]},None,5000)
    assert response['totalTokens']==1500
    assert store.one('SELECT sum(units) n FROM quota_request_units')['n']==1
    assert store.one('SELECT count(*) n FROM quota')['n']==2
    assert store.one('SELECT input_tokens FROM quota WHERE id=?',(response['_quota_id'],))['input_tokens']==0


def test_legacy_project_alias_keeps_earlier_quota_without_editing_ledger(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path);store.migrate()
    monkeypatch.setenv('RT_MODEL_PROJECT_LIMITS',json.dumps({'gemini-embedding-001':[100,30000,2]}))
    a=models.reserve('legacy-shared','gemini-embedding-001',10,None,now=20000,request_units=2)
    store.execute("update quota set status='ok' where id=?",(a,))
    monkeypatch.setenv('RT_LEGACY_PROJECT_MAP',json.dumps({'legacy-shared':'actual-project-one'}))
    with pytest.raises(models.QuotaRefusal) as refused:models.reserve('actual-project-one','gemini-embedding-001',10,None,now=20061)
    assert refused.value.code=='project_daily'
    assert store.one('select project from quota where id=?',(a,))['project']=='legacy-shared'
    assert models.reserve('user-confirmed-project-two','gemini-embedding-001',10,None,now=20061)


def test_unknown_publication_identity_is_unknown_not_a_date_or_error():
    from services.api.temporal import publication_window,compare_time
    assert publication_window({},None) is None
    assert compare_time({'published':'2020-01-01'},{'identity':None})['status']=='unknown'


def test_multi_paper_retrieval_cannot_fill_every_slot_with_one_paper(tmp_path,monkeypatch):
    from services.api import retrieval
    monkeypatch.setattr(store,'DATA',tmp_path);store.migrate()
    monkeypatch.setenv('RT_DISABLE_DENSE','true')
    store.execute('insert into workspaces values(?,?,?)',('w','Scope',1))
    for vid,n in [('a',12),('b',4)]:
        store.execute('insert into versions(id,workspace,title,filename,sha256,path,created,status) values(?,?,?,?,?,?,?,?)',(vid,'w',vid,vid+'.pdf',vid,'unused',1,'ready'))
        for i in range(n):
            text='GPU training context sequences tokens '+('GPU '*10 if vid=='a' else 'different conditions for evaluation ')*3+str(i)
            store.execute('insert into blocks values(?,?,?,?,?,?,?,?,?,?,?)',(vid+str(i),'w',vid,0,'[0,0,1,1]','paragraph',i,text,'fixture','test','{}'))
    result=retrieval.retrieve('w',['a','b'],'GPU training',limit=6)
    primary=[b for b in result['blocks'] if not b.get('neighbor_context')]
    assert len([b for b in primary if b['version_id']=='b'])==3


def test_split_provider_purpose_refuses_before_network_or_reservation(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path);store.migrate()
    monkeypatch.setenv('RT_PROVIDER_MODE','embedding_only')
    with pytest.raises(models.QuotaRefusal) as refused:models.request('gemini-3.6-flash','generateContent',{},None,1)
    assert refused.value.code=='purpose_disabled'
    assert not store.rows('select * from quota')
    monkeypatch.setenv('RT_PROVIDER_MODE','generation_only')
    with pytest.raises(models.QuotaRefusal):models.request(models.EMBED,'batchEmbedContents',{'requests':[{}]},None,1)
    assert not store.rows('select * from quota')
