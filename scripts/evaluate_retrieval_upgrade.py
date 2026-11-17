"""Fixed-source local model comparison; no generator calls or gold from answers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));load_dotenv(ROOT/'.env')
from services.api import store
from services.api.embedding_providers import LocalRetrievalProvider,fingerprint
from services.api.sparse_index import search as sparse_search

GOLD=ROOT/'evals/retrieval_upgrade_80.json'
SCOPES=json.loads((ROOT/'evals/review_upgrade_scopes.json').read_text())
WORKSPACE=SCOPES['workspace']
CORE_GENERATION='fcdff7af26f44e369897bf3ee452089f'
FULL_GENERATION='53ffb2e2e9c14cab81b122e9a4b50857'
MODELS={'qwen':'Qwen/Qwen3-Embedding-8B','nemotron':'nvidia/Nemotron-3.5-Embed-8B-BF16'}
OUT=ROOT/'evidence/review-upgrade'


def save(path,value):
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2));temp.replace(path)


def corpus(gid,require_vectors=True):
    generation=store.one('SELECT * FROM index_generations WHERE workspace=? AND id=?',(WORKSPACE,gid))
    if not generation or (require_vectors and generation['status']!='ready') or generation['expected_blocks']!=generation['covered_blocks']:raise ValueError('Comparison source generation is not fully ready')
    chunks=store.rows('SELECT * FROM retrieval_chunks WHERE generation_id=? ORDER BY version_id,ordinal,id',(gid,))
    spans=store.rows('SELECT s.* FROM retrieval_spans s JOIN retrieval_chunks c ON c.id=s.chunk_id WHERE c.generation_id=?',(gid,))
    mapping={}
    for span in spans:mapping.setdefault(span['chunk_id'],[]).append(span['block_id'])
    digest=hashlib.sha256(json.dumps([(c['id'],c['version_id'],c['parse_id'],c['retrieval_text']) for c in chunks],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    return generation,chunks,mapping,digest


def fixed_vectors(label,provider,generation,chunks,digest):
    desc=provider.descriptor();fp=fingerprint(desc)
    directory=ROOT/'data/retrieval-evaluation'/hashlib.sha256((fp+digest).encode()).hexdigest()[:24]
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    statefile=directory/'progress.json';matrixfile=directory/'documents.f32'
    state=json.loads(statefile.read_text()) if statefile.exists() else {'completed':0,'model_fingerprint':fp,'input_sha256':digest,'created':time.time()}
    if state['model_fingerprint']!=fp or state['input_sha256']!=digest:raise ValueError('Comparison cache fingerprint drift')
    expected_bytes=len(chunks)*desc['dimension']*4
    if matrixfile.exists() and matrixfile.stat().st_size!=expected_bytes:raise ValueError('Comparison matrix size mismatch')
    vectors=np.memmap(matrixfile,dtype=np.float32,mode='r+' if matrixfile.exists() else 'w+',shape=(len(chunks),desc['dimension']))
    if desc['fingerprint']==generation['fingerprint']:
        # Exact same pinned source generation: reuse actual existing vectors.
        for start in range(state['completed'],len(chunks),128):
            batch=chunks[start:start+128];marks=','.join('?' for _ in batch)
            saved={r['chunk_id']:r['vector'] for r in store.rows(f'SELECT chunk_id,vector FROM retrieval_vectors WHERE chunk_id IN ({marks})',tuple(c['id'] for c in batch))}
            vectors[start:start+len(batch)]=np.stack([np.frombuffer(saved[c['id']],dtype=np.float32) for c in batch]);vectors.flush()
            state['completed']=start+len(batch);save(statefile,state)
        state['reuse']='compatible actual production vectors, no embedding replay'
    else:
        # Every model sees exactly the same text and source spans. Its own query
        # and document templates/pooling remain those in its pinned descriptor.
        for start in range(state['completed'],len(chunks),32):
            batch=chunks[start:start+32];before=time.monotonic()
            response=provider.embed([c['retrieval_text'] for c in batch],'RETRIEVAL_DOCUMENT')
            vectors[start:start+len(batch)]=np.asarray(response['vectors'],dtype=np.float32);vectors.flush()
            state.update(completed=start+len(batch),execution=response.get('execution'),last_batch_seconds=round(time.monotonic()-before,3),updated=time.time())
            save(statefile,state)
            save(OUT/('retrieval-'+label+'-progress.json'),{'status':'NOT RUN' if state['completed']<len(chunks) else 'PASS',
                'phase':'document_vectors','completed':state['completed'],'expected':len(chunks),'source_generation':generation['id'],
                'identical_input_sha256':digest,'provider_llm_calls':0,'descriptor':desc,'latest_execution':state.get('execution')})
            if start%320==0:print(json.dumps({'model':label,'document_vectors':state['completed'],'expected':len(chunks)}),flush=True)
    save(statefile,state)
    return vectors,directory,desc


def ranked_blocks(scores,chunks,mapping,versions,limit=50):
    selected={};allowed=set(versions)
    for index,chunk in enumerate(chunks):
        if chunk['version_id'] not in allowed:continue
        for bid in mapping.get(chunk['id'],[]):selected[bid]=max(selected.get(bid,-float('inf')),float(scores[index]))
    return [bid for bid,_ in sorted(selected.items(),key=lambda pair:(-pair[1],pair[0]))[:limit]]


def metrics(ranking,gold):
    if not gold:return {'status':'NOT RUN','reason':'No-answer question excluded from evidence recall denominator'}
    return {f'recall@{k}':len(set(ranking[:k])&gold)/len(gold) for k in (5,10,20,50)}|{
        'all_gold@20':gold.issubset(ranking[:20]),'first_gold_rank':next((i+1 for i,b in enumerate(ranking) if b in gold),None)}


def evaluate(label,scope,rerank=False):
    reportfile=OUT/f'retrieval-{label}-{scope}{"-rerank" if rerank else ""}.json'
    gid=CORE_GENERATION if scope=='core' else FULL_GENERATION
    generation,chunks,mapping,digest=corpus(gid,require_vectors=label!='keyword')
    desc=None;vectors=None;directory=None
    questions=[q for q in json.loads(GOLD.read_text())['questions'] if scope=='all' or q['group']=='core']
    provider=LocalRetrievalProvider(MODELS.get(label),base='http://127.0.0.1:18988' if label=='qwen' else None) if label!='keyword' else None
    report={'started':time.time(),'model':label,'scope':scope,'source_generation':gid,'same_source_text_sha256':digest,
            'gold_sha256':hashlib.sha256(GOLD.read_bytes()).hexdigest(),'provider_llm_calls':0,'independent_human_gold_review':'NOT RUN',
            'no_answer_is_generation_test':False,'paraphrases_correlated':True,'cases':[]}
    if reportfile.exists():
        previous=json.loads(reportfile.read_text())
        if previous['same_source_text_sha256']!=digest or previous['gold_sha256']!=report['gold_sha256']:raise ValueError('Evaluation inputs changed, preserve previous report')
        report=previous
    try:
        if provider:
            vectors,directory,desc=fixed_vectors(label,provider,generation,chunks,digest)
            report['descriptor']=desc
            queryfile=directory/('queries-'+report['gold_sha256'][:16]+'-'+scope+'.npy')
            reused_queries=queryfile.exists()
            if reused_queries:queries=np.load(queryfile,allow_pickle=False)
            else:
                queries=np.asarray([v for start in range(0,len(questions),32) for v in provider.embed([q['question'] for q in questions[start:start+32]],'RETRIEVAL_QUERY')['vectors']],dtype=np.float32)
                np.save(queryfile,queries,allow_pickle=False)
            report['query_vectors']={'source':'same-fingerprint cached actual vectors' if reused_queries else 'live local embedding',
                                     'count':len(queries),'recomputed_this_execution':not reused_queries}
            report['document_vectors']={'source':'compatible actual production vectors' if desc['fingerprint']==generation['fingerprint'] else 'fixed-input model cache',
                                        'count':len(chunks)}
            # Multiplication is bounded by the fixed source matrix on disk.
            similarities=vectors@queries.T
        completed={c['id'] for c in report['cases']}
        reranker=LocalRetrievalProvider() if rerank else None
        for qi,q in enumerate(questions):
            if q['id'] in completed:continue
            before=time.monotonic();gold={g['block_id'] for g in q['gold']}
            for g in q['gold']:
                source=store.one('SELECT text FROM blocks WHERE id=? AND workspace=?',(g['block_id'],WORKSPACE))
                if not source or hashlib.sha256(source['text'].encode()).hexdigest()!=g['text_sha256']:raise ValueError('Gold original source changed')
            sparse,_=sparse_search(WORKSPACE,q['version_ids'],q['question'],limit=50)
            sparse_ids=list(dict.fromkeys(b['id'] for b in sparse))
            dense_ids=ranked_blocks(similarities[:,qi],chunks,mapping,q['version_ids']) if provider else []
            fused={}
            for candidate in (sparse_ids,dense_ids):
                for rank,bid in enumerate(candidate):fused[bid]=fused.get(bid,0)+1/(61+rank)
            hybrid=[bid for bid,_ in sorted(fused.items(),key=lambda item:(-item[1],item[0]))[:50]]
            case={'id':q['id'],'group':q['group'],'category':q['category'],'language':q['language'],
                  'answerable':q['answerable'],'gold_blocks':sorted(gold),'sparse':sparse_ids,'dense':dense_ids,'hybrid':hybrid,
                  'metrics':{'sparse':metrics(sparse_ids,gold),'dense':metrics(dense_ids,gold) if provider else None,'hybrid':metrics(hybrid,gold)}}
            if reranker and hybrid:
                texts=[store.one('SELECT text FROM blocks WHERE id=?',(bid,))['text'] for bid in hybrid]
                response=reranker.rerank(q['question'],texts)
                reranked=[bid for bid,_ in sorted(zip(hybrid,response['scores']),key=lambda pair:-pair[1])]
                case.update(reranked=reranked,reranker_revision=response.get('revision'))
                case['metrics']['reranked']=metrics(reranked,gold)
            case['seconds']=round(time.monotonic()-before,3);report['cases'].append(case);save(reportfile,report)
            print(json.dumps({'model':label,'scope':scope,'id':q['id'],'hybrid_recall20':case['metrics']['hybrid'].get('recall@20')}),flush=True)
        aggregates={}
        for group in ('core','expansion'):
            valid=[c for c in report['cases'] if c['group']==group and c['answerable'] and c['gold_blocks']]
            if not valid:continue
            aggregates[group]={}
            for stage in ('sparse','dense','hybrid','reranked'):
                items=[c['metrics'][stage] for c in valid if c['metrics'].get(stage)]
                if items:aggregates[group][stage]={'questions':len(items),'evidence_blocks':sum(len(c['gold_blocks']) for c in valid),
                    'mean_recall@20':sum(m['recall@20'] for m in items)/len(items),
                    'questions_all_gold@20':sum(m['all_gold@20'] for m in items),
                    'first_gold_top5':sum(m['first_gold_rank'] is not None and m['first_gold_rank']<=5 for m in items)}
        if report.get('error'):
            report.setdefault('prior_failures',[]).append({k:report.pop(k) for k in ('error_type','error','updated') if k in report})
        report.update(status='PASS',status_meaning='Evaluation executed; quality thresholds assessed separately',finished=time.time(),aggregates=aggregates)
        save(reportfile,report)
    except Exception as error:
        report.update(status='FAIL',error_type=type(error).__name__,error=str(error)[:350],updated=time.time());save(reportfile,report);raise
    finally:
        if provider:provider.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--model',choices=['keyword','qwen','nemotron'],required=True)
    parser.add_argument('--scope',choices=['core','all'],default='core');parser.add_argument('--rerank',action='store_true')
    args=parser.parse_args();evaluate(args.model,args.scope,args.rerank)
