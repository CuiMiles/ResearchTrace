"""Actual FTS5 + provider dense retrieval, with per-workspace immutable version scope."""
import json
import os
import re
import time

import numpy as np

from .store import cancelled, db, event, one, rows


def _decode(block):
    block = dict(block)
    for key in ("bbox", "metadata"):
        if isinstance(block.get(key), str):
            block[key] = json.loads(block[key])
    block.pop("workspace", None)
    return block


def index_dense(workspace, version_id, run_id):
    if os.getenv('RT_EMBED_PROVIDER','gemini') in ('local','auto','gemini'):
        from .index_generations import build
        return build(workspace,[version_id],run_id=run_id)
    if os.environ.get("ENABLE_DENSE", "true").lower() == "false" or os.environ.get("RT_DISABLE_DENSE", "false").lower() == "true":
        return {"status": "disabled", "model": None, "dense_pages": 0, "notice": "密集索引已关闭；仅使用关键词检索"}
    from .models import embed
    version = one("SELECT * FROM versions WHERE workspace=? AND id=? AND deleted=0", (workspace, version_id))
    if not version:
        raise ValueError("文档不存在")
    model = os.environ.get("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    blocks = rows("SELECT b.* FROM current_blocks b WHERE b.workspace=? AND b.version_id=? AND length(b.text)>10 AND b.type NOT IN ('header','footer') AND NOT EXISTS(SELECT 1 FROM embeddings e WHERE e.block_id=b.id AND e.model=?) ORDER BY b.page_index,b.reading_order", (workspace, version_id, model))
    completed = 0
    # Bound by the adapter's conservative UTF-8-byte input reservation, not only count.
    batches = []
    current = []
    byte_budget = 0
    for block in blocks:
        text = block["text"][:5000]
        size = len(text.encode("utf-8"))
        if current and (len(current) >= 16 or byte_budget + size > 24000):
            batches.append(current)
            current, byte_budget = [], 0
        current.append(block)
        byte_budget += size
    if current:
        batches.append(current)
    for batch in batches:
        if cancelled(run_id):
            break
        waited = 0
        while True:
            try:
                response = embed([b["text"][:5000] for b in batch], run_id, task="RETRIEVAL_DOCUMENT")
                break
            except Exception as exc:
                # Only a locally rejected reservation can be safely waited/retried.
                # No actual failed HTTP call is repeated here.
                if "分钟额度/并发预算不足" not in str(exc) or waited >= 70:
                    raise
                if cancelled(run_id):
                    return {"status": "cancelled", "new_blocks": completed, "model": model}
                if waited == 0:
                    event(run_id, "dense_quota_wait", {"model": model, "reason": "等待项目级分钟窗口，不重复上游请求"})
                time.sleep(5)
                waited += 5
        actual_model = response["model"].removeprefix("models/")
        vectors = response["vectors"]
        if len(vectors) != len(batch):
            raise ValueError("embedding response count mismatch")
        with db() as conn:
            for block, vector in zip(batch, vectors, strict=True):
                array = np.asarray(vector, dtype=np.float32)
                if array.ndim != 1 or len(array) < 1 or not np.isfinite(array).all():
                    raise ValueError("invalid embedding vector")
                conn.execute("INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?,?,?)", (block["id"], workspace, version_id, actual_model, len(array), array.tobytes()))
            covered = conn.execute("SELECT count(*) FROM current_pages p WHERE p.version_id=? AND p.status IN ('ready','ocr','ocr_review_required') AND NOT EXISTS(SELECT 1 FROM current_blocks b WHERE b.version_id=p.version_id AND b.page_index=p.page_index AND length(b.text)>10 AND b.type NOT IN ('header','footer') AND NOT EXISTS(SELECT 1 FROM embeddings e WHERE e.block_id=b.id AND e.model=?))", (version_id, actual_model)).fetchone()[0]
            conn.execute("UPDATE versions SET dense_pages=? WHERE id=?", (covered, version_id))
        completed += len(batch)
        event(run_id, "dense_batch_indexed", {"tool": "embed_document", "model": actual_model, "dimension": response["dimension"], "blocks": completed, "dense_pages": covered, "page_count": version["page_count"]})
    return {"status": "complete" if completed == len(blocks) else "partial", "new_blocks": completed, "model": model, "dense_pages": one("SELECT dense_pages FROM versions WHERE id=?", (version_id,))["dense_pages"]}


def retrieve(workspace, version_ids, question, limit=16, queries=None, allow_cloud_dense=True):
    """Hybrid retrieval over immutable blocks.

    `queries` are extra keyword queries (e.g. English rewrites of a Chinese
    question); each is searched per document and fused by RRF as its own list.
    """
    limit = min(max(int(limit), 1), 50)
    if not version_ids:
        return {"blocks": [], "sparse": [], "dense": [], "mode": "keyword", "notice": "请选择文档版本"}
    requested = list(dict.fromkeys(version_ids))
    placeholders = ",".join("?" for _ in requested)
    allowed = rows(f"SELECT id FROM versions WHERE workspace=? AND deleted=0 AND id IN ({placeholders})", (workspace, *requested))
    if len(allowed) != len(requested):
        raise ValueError("检索版本不存在或不属于当前工作区")
    from .document_workflows import retrieval_version_ids
    requested=retrieval_version_ids(workspace,requested)
    if not requested:
        return {'blocks':[],'sparse':[],'dense':[],'mode':'keyword','notice':'所选版本已被版本选择排除；请保留两个版本或改选当前版本。'}
    placeholders=','.join('?' for _ in requested)
    boundaries={}
    if not re.search(r'references?|bibliograph|appendi|参考文献|附录|索引|末页|\bindex\b',question,re.I):
        headings=rows(f"SELECT version_id,page_index,reading_order,text FROM current_blocks WHERE workspace=? AND version_id IN ({placeholders}) AND type='heading'",(workspace,*requested))
        for heading in headings:
            if re.match(r'^\s*(?:\d+[.\s]+)?(?:references|bibliography|appendix|参考文献|附录)\b',heading['text'],re.I):
                position=(heading['page_index'],heading['reading_order'])
                boundaries[heading['version_id']]=min(boundaries.get(heading['version_id'],position),position)
    if re.search(r'上下文|context|sequence.{0,12}length',question,re.I):
        queries=list(dict.fromkeys(list(queries or [])+['context size tokens','contiguous sequences tokens']))[:4]
    from .sparse_index import search as sparse_search
    sparse,expanded_terms=sparse_search(workspace,requested,question,limit=min(150,limit*3))
    if len(requested)>1:
        seen={b['id'] for b in sparse}
        for vid in requested:
            per_doc,_=sparse_search(workspace,[vid],question,limit=max(2,limit//len(requested)))
            if vid in boundaries:
                body,_=sparse_search(workspace,[vid],question,limit=max(2,limit//len(requested)),before=boundaries[vid]);per_doc+=body
            for item in per_doc:
                if item['id'] not in seen:
                    sparse.append(item);seen.add(item['id'])
    rewritten=[]
    for extra in [q for q in (queries or []) if isinstance(q,str) and q.strip()][:4]:
        ranked=[]
        for vid in requested:
            per_doc,_=sparse_search(workspace,[vid],extra[:300],limit=max(3,limit//len(requested)))
            if vid in boundaries:
                body,_=sparse_search(workspace,[vid],extra[:300],limit=max(3,limit//len(requested)),before=boundaries[vid]);per_doc+=body
            ranked.extend(per_doc)
        ranked.sort(key=lambda b:b['sparse_score'])
        rewritten.append(ranked)
    dense=[];dense_metadata={'status':'unindexed'};reranker=None
    notice='当前使用对称分词的关键词索引；向量覆盖尚未完成'
    selected_provider=os.getenv('RT_EMBED_PROVIDER','gemini')
    if selected_provider in ('local','auto'):
        try:
            from .embedding_providers import LocalRetrievalProvider
            from .index_generations import dense_search
            reranker=LocalRetrievalProvider()
            if os.environ.get('RT_DISABLE_DENSE','false').lower()!='true':
                dense,dense_metadata=dense_search(workspace,requested,question,limit=50,provider=reranker)
                notice='本地模型独立索引与BM25经RRF融合；相关性不代表证据支持' if dense else '本地模型没有兼容的完整活动索引；当前为关键词降级'
        except Exception as exc:
            dense_metadata={'status':'unavailable','reason':type(exc).__name__}
            notice='本地向量服务不可用；仅关键词与明确标识的术语扩展，未调用云端替代'
    if not dense and selected_provider in ('gemini','auto') and allow_cloud_dense and os.getenv('RT_DISABLE_DENSE','false').lower()!='true':
        try:
            from .embedding_providers import GeminiRetrievalProvider
            from .index_generations import dense_search
            local_state=dense_metadata
            dense,dense_metadata=dense_search(workspace,requested,question,limit=50,provider=GeminiRetrievalProvider())
            dense_metadata.update(provider='gemini',local_fallback=local_state if selected_provider=='auto' else None)
            notice='Gemini独立代际向量与BM25经RRF融合；本地服务可用时优先使用其独立索引' if dense else 'Gemini语义索引尚未完整，当前仅关键词检索'
        except Exception as exc:
            dense_metadata={'status':'unavailable','provider':'gemini','reason':type(exc).__name__}
            notice='云向量查询暂不可用；保留关键词结果，不冒充语义召回'
    if not dense and selected_provider=='gemini' and dense_metadata.get('status')=='unindexed':
        model=os.environ.get('GEMINI_EMBEDDING_MODEL','gemini-embedding-001')
        # One joined read replaces a per-vector block lookup. This legacy index
        # remains independent of model-fingerprinted local generations.
        dense_rows=rows(f"SELECT cb.*,e.model,e.dimension,e.vector FROM embeddings e JOIN current_blocks cb ON cb.id=e.block_id JOIN versions v ON v.id=e.version_id WHERE e.workspace=? AND e.version_id IN ({placeholders}) AND v.deleted=0 AND e.model=?",(workspace,*requested,model)) if allow_cloud_dense else []
        if dense_rows and os.environ.get('RT_DISABLE_DENSE','false').lower()!='true':
            try:
                from .models import embed
                response=embed([question],None,task='RETRIEVAL_QUERY')
                vector=np.asarray(response['vectors'][0],dtype=np.float32)
                actual_model=response['model'].removeprefix('models/')
                compatible=[r for r in dense_rows if r['dimension']==len(vector) and r['model']==actual_model]
                if compatible and np.isfinite(vector).all() and np.linalg.norm(vector)>0:
                    matrix=np.stack([np.frombuffer(r['vector'],dtype=np.float32) for r in compatible])
                    scores=(matrix@vector)/np.maximum(np.linalg.norm(matrix,axis=1)*np.linalg.norm(vector),1e-9)
                    order=np.argsort(-scores)[:limit*3]
                    dense=[{**{k:v for k,v in compatible[int(i)].items() if k!='vector'},'dense_score':float(scores[int(i)])} for i in order]
                    dense_metadata={'status':'ready','model_id':actual_model,'dimension':len(vector),'provider':'gemini'}
                    notice='Gemini独立索引与FTS5候选经RRF合并；覆盖率见版本详情'
            except Exception as exc:
                notice='密集查询不可用（'+type(exc).__name__+'）；当前为关键词检索'
    by_id = {}
    scores = {}
    for candidates in (sparse, *rewritten, dense):
        seen=set();rank=0
        for block in candidates:
            if block['id'] in seen:continue
            seen.add(block['id'])
            by_id[block["id"]] = block
            scores[block["id"]] = scores.get(block["id"], 0) + 1 / (60 + rank + 1)
            rank+=1
    def main_body(b):
        return (b['page_index'],b['reading_order'])<boundaries.get(b['version_id'],(10**9,10**9))
    for bid in scores:
        if not main_body(by_id[bid]):scores[bid]*=.35
    ordered=sorted(scores,key=scores.get,reverse=True)
    rerank_metadata={'status':'NOT RUN'}
    if reranker is not None and dense_metadata.get('status')!='unavailable' and ordered and os.getenv('RT_ENABLE_RERANK','true')=='true':
        try:
            top=ordered[:50]
            response=reranker.rerank(question,[by_id[k].get('retrieval_text',by_id[k]['text']) for k in top])
            ranked=sorted(zip(top,response['scores']),key=lambda pair:pair[1],reverse=True)
            ordered=[k for k,_ in ranked]+ordered[50:]
            rerank_metadata={'status':'PASS','model_id':response.get('model_id'),'revision':response.get('revision'),'candidates':len(top),'score_semantics':'relevance_not_truth'}
        except Exception as exc:
            rerank_metadata={'status':'BLOCKED','reason':type(exc).__name__}
    picked=[]
    # Reserve evidence slots for each requested document before filling globally.
    reserved=max(1,limit//len(requested))
    anchors={vid:[] for vid in requested}
    # Preserve a precise rewrite's best hit for each paper, even when generic
    # query consensus favours repetitive appendices or sample-output blocks.
    for ranked in rewritten:
        for vid in requested:
            best=next((b['id'] for b in ranked if b['version_id']==vid and main_body(b)),None)
            if best and best not in anchors[vid]:anchors[vid].append(best)
    per_document={vid:(anchors[vid][:min(2,reserved)]+[k for k in ordered if by_id[k]['version_id']==vid and k not in anchors[vid][:min(2,reserved)]])[:reserved] for vid in requested}
    for slot in range(reserved):
        for vid in requested:
            if slot<len(per_document[vid]) and len(picked)<limit:picked.append(per_document[vid][slot])
    picked.extend(k for k in ordered if k not in picked)
    picked=picked[:limit]
    blocks=[{**_decode(by_id[k]),'rrf_score':scores[k]} for k in picked]
    for block in blocks:
        if 'span_start' in block:
            block['evidence_text']=block['text'][block['span_start']:block['span_end']]
    # Adjacent blocks recover table headers/conditions without changing evidence identities.
    added = set(picked)
    for item in blocks[:max(1, limit // 3)]:
        neighbors = rows("SELECT * FROM current_blocks WHERE workspace=? AND version_id=? AND page_index=? AND reading_order BETWEEN ? AND ? AND length(text)>0 ORDER BY reading_order", (workspace, item["version_id"], item["page_index"], item["reading_order"] - 1, item["reading_order"] + 1))
        for neighbor in neighbors:
            if neighbor["id"] not in added and len(blocks) < limit + 6:
                blocks.append({**_decode(neighbor), "neighbor_context": True})
                added.add(neighbor["id"])
    sparse_all = sparse + [b for ranked in rewritten for b in ranked]
    return {"rewritten_queries": [q for q in (queries or [])][:4], "blocks": blocks, "sparse": [{"block_id": b["id"], "score": b["sparse_score"]} for b in sparse_all], "dense": [{"block_id": b["id"], "score": b["dense_score"]} for b in dense], "mode": "hybrid" if dense else "keyword", "notice": notice, "version_ids": requested, "method": "FTS5_BM25+cosine+RRF" if dense else "FTS5_BM25", "dense_index":dense_metadata, "rerank":rerank_metadata, "query_term_expansion":expanded_terms}
