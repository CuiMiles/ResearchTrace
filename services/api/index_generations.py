"""Resumable derived indexes, snapshot-scoped activation and bounded exact search."""
import hashlib
import heapq
import json
import time

import numpy as np

from . import store
from .embedding_providers import LocalRetrievalProvider, RetrievalUnavailable, fingerprint

CHUNKER='source-spans-v1'


def corpus(workspace,version_ids):
    versions=[]
    for vid in sorted(set(version_ids)):
        version=store.one('SELECT v.*,COALESCE(a.parse_id,v.id) parse_id FROM versions v LEFT JOIN active_parses a ON a.version_id=v.id WHERE v.id=? AND v.workspace=? AND v.deleted=0',(vid,workspace))
        if not version:
            raise ValueError('索引文档不存在或无权限')
        parse=store.one('SELECT status FROM parses WHERE id=?',(version['parse_id'],))
        if not parse or parse['status']!='ready':
            raise ValueError('索引需要完整的活动解析快照')
        versions.append(version)
    return versions


def eligible(block):
    return bool(block['text'].strip()) and block['type'] not in ('header','footer')


def snapshots(versions):
    return [{'version_id':v['id'],'parse_id':v['parse_id'],'sha256':v['sha256']} for v in versions]


def packed_cloud_chunks(blocks,title,provider):
    """Pack complete source spans; each input stays within a UTF-8 token bound.

    This is a different retrieval chunker, never a same-input model comparison.
    A hit still resolves to each original immutable block and physical page.
    """
    prefix=('Title: '+title+'\n').encode()[:120].decode('utf-8',errors='ignore')
    cap=2048-len(prefix.encode());groups=[];parts=[];spans=[];size=0
    def flush():
        nonlocal parts,spans,size
        if parts:
            text='\n\n'.join(parts);groups.append({'text':text,'retrieval_text':prefix+text,'spans':spans,'kind':'source_bundle'})
        parts=[];spans=[];size=0
    for b in blocks:
        if not eligible(b):continue
        for piece in provider.split(b['text'],cap,32):
            length=len(piece['text'].encode());separator=2 if parts else 0
            if parts and size+separator+length>cap:flush();separator=0
            parts.append(piece['text']);size+=separator+length
            spans.append((b['id'],piece['start'],piece['end']))
    flush()
    return groups


def build(workspace,version_ids,*,provider=None,run_id=None,generation_id=None,activate=True,chunks_only=False,source_generation_id=None,pack_cloud=False):
    if provider is None:
        from .embedding_providers import configured_provider
        provider=configured_provider(run_id=run_id)
    desc=provider.descriptor();fp=fingerprint(desc)
    versions=corpus(workspace,version_ids)
    stable={k:v for k,v in desc.items() if k not in ('weights_ready','tokenizer_ready','inference_verified')}
    manifest={'provider':stable,'fingerprint':fp,'chunker':CHUNKER,'snapshots':snapshots(versions),'max_tokens':512,
              'exclusions':['empty_text','header','footer'],'context_is_source_evidence':False}
    if pack_cloud:
        if desc.get('provider')!='gemini':raise ValueError('显式云片段合并只适用于Gemini独立索引')
        manifest.update(chunker='source-bundles-byte-bound-v1',input_byte_limit=2048,max_tokens=2048,
                        token_count_kind='conservative_utf8_byte_upper_bound',identical_retrieval_inputs=False,source_spans_preserved=True)
    if source_generation_id:
        source=store.one('SELECT * FROM index_generations WHERE id=? AND workspace=?',(source_generation_id,workspace))
        if not source or source['covered_blocks']!=source['expected_blocks'] or not source['chunk_count']:
            raise ValueError('同条件对照需要完整源片段，不需要源向量已完成')
        if json.loads(source['manifest'])['snapshots']!=manifest['snapshots']:
            raise ValueError('对照源索引的文档及解析快照必须完全相同')
        manifest.update(chunker='fixed-source-spans-v1',source_generation_id=source_generation_id,
                        token_count_kind='source_chunker_count_not_cloud_tokenizer')
        if desc.get('provider')=='gemini' and not pack_cloud:
            manifest.update(chunker='source-spans-cloud-byte-bound-v1',input_byte_limit=2048,
                            identical_retrieval_inputs=False,source_spans_preserved=True)
        if pack_cloud:manifest['chunker']='source-bundles-byte-bound-v1'
    gid=generation_id or store.uid()
    previous=store.one('SELECT * FROM index_generations WHERE id=? AND workspace=?',(gid,workspace))
    if previous:
        prior_manifest=json.loads(previous['manifest'])
        prior_manifest['provider']={k:v for k,v in prior_manifest['provider'].items() if k not in ('weights_ready','tokenizer_ready','inference_verified')}
        if prior_manifest!=manifest:
            raise ValueError('续建时模型、切分或解析快照已改变；需新建索引代')
        if previous['status']=='ready':
            if activate:activate_generation(workspace,gid)
            return generation_status(workspace,gid)
        store.execute("UPDATE index_generations SET status='building',error=NULL,manifest=? WHERE id=?",(json.dumps(manifest,ensure_ascii=False),gid))
    else:
        store.execute('INSERT INTO index_generations(id,workspace,model_id,revision,fingerprint,manifest,status,dimension,created) VALUES(?,?,?,?,?,?,?,?,?)',
                      (gid,workspace,desc['model_id'],desc['revision'],fp,json.dumps(manifest,ensure_ascii=False),'building',desc['dimension'],time.time()))
    def stop():
        if run_id and store.cancelled(run_id):
            store.execute("UPDATE index_generations SET status='cancelled' WHERE id=?",(gid,))
            raise RetrievalUnavailable('索引已取消，已持久化片段可继续同代恢复')
    try:
        expected=excluded=covered=0
        if source_generation_id and not pack_cloud:
            with store.db() as c:
                for chunk in c.execute('SELECT * FROM retrieval_chunks WHERE generation_id=?',(source_generation_id,)).fetchall():
                    spans=c.execute('SELECT * FROM retrieval_spans WHERE chunk_id=?',(chunk['id'],)).fetchall()
                    pieces=[{'text':chunk['text'],'start':0,'end':len(chunk['text']),'token_count':chunk['token_count']}]
                    prefix=chunk['retrieval_text'][:-len(chunk['text'])] if chunk['text'] and chunk['retrieval_text'].endswith(chunk['text']) else None
                    changed=desc.get('provider')=='gemini' and len(chunk['retrieval_text'].encode())>2048
                    if changed:
                        if prefix is None or len(spans)!=1 or spans[0]['end']-spans[0]['start']!=len(chunk['text']):
                            raise ValueError('超长源片段无法无损映射，拒绝静默截断')
                        # Context is never evidence. Bound it while retaining the
                        # complete original source through overlapping spans.
                        prefix=prefix.encode()[:1024].decode('utf-8',errors='ignore')
                        pieces=provider.split(chunk['text'],2048-len(prefix.encode()),32)
                    for pi,piece in enumerate(pieces):
                        cid=hashlib.sha256((gid+':fixed:'+chunk['id']+':'+str(pi)).encode()).hexdigest()
                        text=prefix+piece['text'] if changed else chunk['retrieval_text']
                        c.execute('INSERT OR IGNORE INTO retrieval_chunks VALUES(?,?,?,?,?,?,?,?,?,?)',
                                  (cid,gid,workspace,chunk['version_id'],chunk['parse_id'],chunk['ordinal']*100+pi,piece['text'],text,piece['token_count'],chunk['kind']))
                        for span in spans:
                            start=span['start']+piece['start'] if changed else span['start']
                            end=span['start']+piece['end'] if changed else span['end']
                            c.execute('INSERT OR IGNORE INTO retrieval_spans VALUES(?,?,?,?)',(cid,span['block_id'],start,end))
        for version in versions:
            from .snapshots import snapshot_blocks
            blocks=snapshot_blocks(workspace,version['id'],version['parse_id'])
            existing={r['block_id'] for r in store.rows('SELECT DISTINCT s.block_id FROM retrieval_spans s JOIN retrieval_chunks c ON c.id=s.chunk_id WHERE c.generation_id=? AND c.version_id=?',(gid,version['id']))}
            if pack_cloud and not existing:
                packed=packed_cloud_chunks(blocks,version['title'],provider)
                with store.db() as c:
                    for ordinal,item in enumerate(packed):
                        cid=hashlib.sha256((gid+':packed:'+version['id']+':'+str(ordinal)).encode()).hexdigest()
                        c.execute('INSERT OR IGNORE INTO retrieval_chunks VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (cid,gid,workspace,version['id'],version['parse_id'],ordinal,item['text'],item['retrieval_text'],len(item['retrieval_text'].encode()),item['kind']))
                        for bid,start,end in item['spans']:c.execute('INSERT OR IGNORE INTO retrieval_spans VALUES(?,?,?,?)',(cid,bid,start,end))
                existing={b['id'] for b in blocks if eligible(b)}
            prepared={}
            if hasattr(provider,'split_many'):
                for cap in (512,2048):
                    pending=[b for b in blocks if eligible(b) and b['id'] not in existing and (2048 if b['type']=='table' else 512)==cap]
                    for offset in range(0,len(pending),32):
                        stop()
                        batch=pending[offset:offset+32]
                        parts=provider.split_many([b['text'] for b in batch],max_tokens=cap,overlap=32)
                        if len(parts)!=len(batch):raise RetrievalUnavailable('批量切分数量与源块不一致')
                        prepared.update({b['id']:p for b,p in zip(batch,parts)})
            section=''
            for block in blocks:
                stop()
                if not eligible(block):
                    excluded+=1
                    continue
                expected+=1
                if block['type']=='heading':section=block['text'][:500]
                if block['id'] in existing:
                    covered+=1
                    continue
                # Full original text is split by the actual selected tokenizer.
                # Tables remain intact up to2048 tokens; larger source tables are
                # separately spanned, with the original first rows as context.
                cap=2048 if block['type']=='table' else 512
                parts=prepared[block['id']] if block['id'] in prepared else provider.split(block['text'],max_tokens=cap,overlap=32)
                cursor=0
                for part in parts:
                    start,end=part['start'],part['end']
                    if start>cursor or part['text']!=block['text'][start:end] or not 0<=start<end<=len(block['text']) or not 0<part['token_count']<=cap:
                        raise RetrievalUnavailable('切分跨度或token长度无效')
                    cursor=max(cursor,end)
                if cursor!=len(block['text']):
                    raise RetrievalUnavailable('长块尾部未覆盖')
                with store.db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    for order,part in enumerate(parts):
                        cid=hashlib.sha256((gid+':'+block['id']+':'+str(order)).encode()).hexdigest()
                        prefix=f"Title: {version['title'][:500]}\nSection: {section}\nKind: {block['type']}\n"
                        if block['type']=='table' and len(parts)>1:
                            prefix+='Table headers/context: '+'\n'.join(block['text'].splitlines()[:2])[:1000]+'\n'
                        text=prefix+'Text: '+part['text']
                        c.execute('INSERT INTO retrieval_chunks VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,gid,workspace,version['id'],version['parse_id'],order,part['text'],text,part['token_count'],block['type']))
                        c.execute('INSERT INTO retrieval_spans VALUES(?,?,?,?)',(cid,block['id'],part['start'],part['end']))
                    covered+=1
                    c.execute('UPDATE index_generations SET expected_blocks=?,covered_blocks=?,excluded_blocks=? WHERE id=?',(expected,covered,excluded,gid))
            if run_id:store.event(run_id,'index_chunks',{'generation_id':gid,'covered_blocks':covered,'excluded_blocks':excluded})
        store.execute('UPDATE index_generations SET expected_blocks=?,covered_blocks=?,excluded_blocks=? WHERE id=?',(expected,covered,excluded,gid))
        count=store.one('SELECT count(*) n FROM retrieval_chunks WHERE generation_id=?',(gid,))['n']
        store.execute('UPDATE index_generations SET chunk_count=? WHERE id=?',(count,gid))
        if chunks_only:
            store.execute("UPDATE index_generations SET status='staged' WHERE id=?",(gid,))
            return generation_status(workspace,gid)
        # Core4 can activate first. The full39 generation may reuse only exact
        # same-snapshot/text spans from a verified, same-fingerprint generation.
        with store.db() as c:
            c.execute('''INSERT OR IGNORE INTO retrieval_vectors(chunk_id,dimension,vector)
              SELECT current.id,prior_vector.dimension,prior_vector.vector
              FROM retrieval_chunks current JOIN retrieval_spans cs ON cs.chunk_id=current.id
              JOIN retrieval_spans ps ON ps.block_id=cs.block_id AND ps.start=cs.start AND ps.end=cs.end
              JOIN retrieval_chunks prior ON prior.id=ps.chunk_id AND prior.workspace=current.workspace
                AND prior.parse_id=current.parse_id AND prior.retrieval_text=current.retrieval_text
              JOIN index_generations pg ON pg.id=prior.generation_id AND pg.fingerprint=?
              JOIN retrieval_vectors prior_vector ON prior_vector.chunk_id=prior.id AND prior_vector.dimension=?
              WHERE current.generation_id=? AND current.workspace=? AND NOT EXISTS(SELECT 1 FROM retrieval_vectors v WHERE v.chunk_id=current.id)
              GROUP BY current.id''',(fp,desc['dimension'],gid,workspace))
            c.execute('UPDATE index_generations SET vector_count=(SELECT count(*) FROM retrieval_vectors v JOIN retrieval_chunks c ON c.id=v.chunk_id WHERE c.generation_id=?) WHERE id=?',(gid,gid))
        # Read bounded batches. Successful batches persist before the next call.
        completed_batches=0
        while True:
            stop()
            if run_id and completed_batches and store.one("SELECT 1 FROM runs WHERE status='queued' AND kind IN ('parse','parse_document','reparse') LIMIT 1"):
                # Release the document executor at a persisted batch boundary.
                # Activation still requires all vectors and unchanged snapshots.
                status=generation_status(workspace,gid)
                store.event(run_id,'index_yielded',{'generation_id':gid,'vector_count':status['vector_count'],
                                                   'reason':'让待解析全文先执行；相同索引代继续恢复'})
                return {**status,'generation_status':status['status'],'status':'queued','coverage_complete':False}
            candidates=store.rows('SELECT c.id,c.retrieval_text FROM retrieval_chunks c LEFT JOIN retrieval_vectors v ON v.chunk_id=c.id WHERE c.generation_id=? AND v.chunk_id IS NULL ORDER BY c.id LIMIT 32',(gid,))
            batch=[];size=0
            maximum=32 if desc.get('provider')=='gemini' else 16
            for candidate in candidates:
                length=len(candidate['retrieval_text'].encode())
                if batch and (size+length>24000 or len(batch)>=maximum):break
                batch.append(candidate);size+=length
            if not batch:break
            response=provider.embed([b['retrieval_text'] for b in batch],'RETRIEVAL_DOCUMENT')
            if response.get('fingerprint')!=fp:
                raise RetrievalUnavailable('实际模型配置发生变化，拒绝混用索引')
            vectors=np.asarray(response.get('vectors'),dtype=np.float32)
            if vectors.shape!=(len(batch),desc['dimension']) or not np.isfinite(vectors).all() or (np.linalg.norm(vectors,axis=1)==0).any():
                raise RetrievalUnavailable('实际向量批次数量或维度非法')
            stop()
            with store.db() as c:
                c.execute('BEGIN IMMEDIATE')
                for block,vector in zip(batch,vectors):
                    c.execute('INSERT INTO retrieval_vectors VALUES(?,?,?)',(block['id'],desc['dimension'],vector.tobytes()))
                c.execute('UPDATE index_generations SET vector_count=(SELECT count(*) FROM retrieval_vectors v JOIN retrieval_chunks c ON c.id=v.chunk_id WHERE c.generation_id=?) WHERE id=?',(gid,gid))
            completed_batches+=1
            if run_id:
                progress=store.one('SELECT vector_count,chunk_count FROM index_generations WHERE id=?',(gid,))
                calls=store.one('SELECT count(*) n FROM quota WHERE run_id=?',(run_id,))['n'] if desc.get('provider')=='gemini' else 0
                store.event(run_id,'index_embedding',{'generation_id':gid,**progress,'model_id':desc['model_id'],'cloud_requests':calls})
        count=store.one('SELECT count(*) n FROM retrieval_chunks WHERE generation_id=?',(gid,))['n']
        actual=store.one('SELECT vector_count FROM index_generations WHERE id=?',(gid,))['vector_count']
        if not expected or expected!=covered or actual!=count:
            raise RetrievalUnavailable('索引覆盖不完整，不能激活')
        store.execute("UPDATE index_generations SET status='ready',chunk_count=?,error=NULL WHERE id=?",(count,gid))
        if activate:activate_generation(workspace,gid)
        return generation_status(workspace,gid)
    except Exception as exc:
        status='cancelled' if run_id and store.cancelled(run_id) else 'failed'
        store.execute('UPDATE index_generations SET status=?,error=? WHERE id=?',(status,type(exc).__name__,gid))
        raise


def activate_generation(workspace,generation_id):
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        generation=c.execute('SELECT * FROM index_generations WHERE id=? AND workspace=?',(generation_id,workspace)).fetchone()
        if not generation or generation['status']!='ready' or generation['covered_blocks']!=generation['expected_blocks'] or generation['vector_count']!=generation['chunk_count']:
            raise ValueError('索引尚未完整，无法切换')
        manifest=json.loads(generation['manifest'])
        for snap in manifest['snapshots']:
            current=c.execute('SELECT COALESCE(a.parse_id,v.id) parse_id FROM versions v LEFT JOIN active_parses a ON a.version_id=v.id WHERE v.id=? AND v.workspace=? AND v.deleted=0',(snap['version_id'],workspace)).fetchone()
            if not current or current['parse_id']!=snap['parse_id']:
                raise ValueError('活动解析已变化；旧索引保留，需构建新代')
        for snap in manifest['snapshots']:
            c.execute('INSERT OR REPLACE INTO active_retrieval_indices VALUES(?,?,?,?)',(workspace,snap['version_id'],generation['model_id'],generation_id))
        c.execute('UPDATE index_generations SET activated=? WHERE id=?',(time.time(),generation_id))


def generation_status(workspace,gid):
    row=store.one('SELECT * FROM index_generations WHERE id=? AND workspace=?',(gid,workspace))
    if not row:raise ValueError('索引代不存在或无权限')
    row['manifest']=json.loads(row['manifest'])
    row['coverage_complete']=row['status']=='ready' and row['expected_blocks']==row['covered_blocks'] and row['vector_count']==row['chunk_count']
    return row


def dense_search(workspace,version_ids,question,limit=50,provider=None):
    provider=provider or LocalRetrievalProvider();desc=provider.descriptor();fp=fingerprint(desc)
    placeholders=','.join('?' for _ in version_ids)
    valid=store.rows(f'SELECT DISTINCT g.id FROM index_generations g JOIN active_retrieval_indices a ON a.generation_id=g.id WHERE a.workspace=? AND a.version_id IN ({placeholders}) AND a.model_id=? AND g.status=? AND g.fingerprint=?',(workspace,*version_ids,desc['model_id'],'ready',fp))
    if not valid:return [],{'status':'unindexed','model_id':desc['model_id'],'notice':'所选模型尚无兼容活动索引，未调用云端替代。'}
    response=provider.embed([question],'RETRIEVAL_QUERY')
    if response.get('fingerprint')!=fp:raise RetrievalUnavailable('问题向量与索引指纹不匹配')
    query=np.asarray(response['vectors'][0],dtype=np.float32)
    if query.shape!=(desc['dimension'],) or not np.isfinite(query).all() or np.linalg.norm(query)==0:
        raise RetrievalUnavailable('问题向量非法')
    query/=np.linalg.norm(query)
    top=[]
    per_doc={vid:[] for vid in version_ids}
    quota=max(1,limit//max(1,len(version_ids)))
    # Exact matrix inner products in <=8MiB batches, no per-block SQL lookups.
    batch_size=max(1,(8*1024**2)//(desc['dimension']*4))
    with store.db() as c:
        cursor=c.execute(f'SELECT c.id,c.version_id,v.vector FROM retrieval_chunks c JOIN retrieval_vectors v ON v.chunk_id=c.id JOIN active_retrieval_indices a ON a.generation_id=c.generation_id AND a.version_id=c.version_id AND a.workspace=c.workspace LEFT JOIN active_parses p ON p.version_id=c.version_id JOIN versions d ON d.id=c.version_id WHERE c.workspace=? AND c.version_id IN ({placeholders}) AND a.model_id=? AND c.parse_id=COALESCE(p.parse_id,c.version_id) AND d.deleted=0 AND c.generation_id IN (SELECT id FROM index_generations WHERE fingerprint=? AND status=?)',(workspace,*version_ids,desc['model_id'],fp,'ready'))
        while batch:=cursor.fetchmany(batch_size):
            matrix=np.stack([np.frombuffer(row['vector'],dtype=np.float32) for row in batch])
            scores=(matrix@query)/np.maximum(np.linalg.norm(matrix,axis=1),1e-9)
            for row,score in zip(batch,scores):
                entry=(float(score),row['id'])
                doc_top=per_doc[row['version_id']]
                if len(doc_top)<quota:heapq.heappush(doc_top,entry)
                elif entry>doc_top[0]:heapq.heapreplace(doc_top,entry)
                if len(top)<limit:heapq.heappush(top,entry)
                elif entry>top[0]:heapq.heapreplace(top,entry)
    if not top:return [],{'status':'stale','model_id':desc['model_id']}
    rank={cid:score for score,cid in top}
    for entries in per_doc.values():
        rank.update({cid:score for score,cid in entries})
    ids=list(rank);marks=','.join('?' for _ in ids)
    rows=store.rows(f'SELECT b.*,s.chunk_id,s.start AS span_start,s.end AS span_end,c.retrieval_text,c.parse_id FROM retrieval_spans s JOIN retrieval_chunks c ON c.id=s.chunk_id JOIN blocks b ON b.id=s.block_id JOIN versions d ON d.id=b.version_id WHERE s.chunk_id IN ({marks}) AND b.workspace=? AND d.deleted=0',( *ids,workspace))
    result=sorted(({**row,'dense_score':rank[row['chunk_id']]} for row in rows),key=lambda b:b['dense_score'],reverse=True)
    return result,{'status':'ready','model_id':desc['model_id'],'revision':desc['revision'],'fingerprint':fp,'dimension':desc['dimension'],'method':'bounded_exact_matrix'}
