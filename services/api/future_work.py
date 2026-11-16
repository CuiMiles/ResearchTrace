"""Discover -> legal public arXiv download -> document pool -> dated evidence audit."""
import json
import os
import time
from . import models,store
from .dependencies import child_statuses,PENDING
from .temporal import compare_time


def audit(run):
    from .jobs import checkpoint,source_context,SYSTEM,validate_answer
    from .research import search_papers,import_paper,normalize_identity
    w,rid,p=run['workspace'],run['id'],run['payload']
    block=store.one('SELECT b.*,COALESCE(bp.parse_id,b.version_id) AS parse_id FROM blocks b LEFT JOIN block_parses bp ON bp.block_id=b.id JOIN versions v ON v.id=b.version_id WHERE b.id=? AND b.workspace=? AND b.version_id=? AND v.deleted=0',(p['block_id'],w,p['version_id']))
    if not block:raise ValueError('旧建议来源不存在或已删除')
    snap=json.loads(store.one('SELECT checkpoint FROM runs WHERE id=?',(rid,))['checkpoint'] or '{}')
    old=source_context(w,[p['version_id']])[0]
    if 'search' not in snap:
        store.event(rid,'searching',{'query':p['question'],'sources':['arxiv','crossref'],'metadata_is_fulltext':False})
        snap['search']=search_papers(w,p['question'],limit=8,fresh=True)
        checkpoint(run,{'search':snap['search']})
    search=snap['search'];candidates=search.get('results',[])
    downloads=snap.get('audit_downloads',[])
    if os.getenv('RT_FUTURE_FULLTEXT','false').lower()=='true':
        attempted={d['identity'] for d in downloads}
        selected=[];seen=set()
        for candidate in candidates:
            identity=normalize_identity(candidate['identity'])
            if identity in seen or identity==normalize_identity(old.get('identity')):continue
            seen.add(identity)
            if candidate.get('source')=='arxiv' and compare_time(old,candidate)['status']=='later':selected.append(candidate)
        for paper in selected[:3]:
            if store.cancelled(rid):return {}
            if paper['identity'] in attempted:continue
            row={'identity':paper['identity'],'time_comparison':compare_time(old,paper),'attempted_at':time.time()}
            try:
                imported=import_paper(w,paper,index_dense=False,metadata_only=False)
                row.update(imported)
                child=imported.get('run_id')
                if child and not imported.get('duplicate'):
                    with store.db() as conn:
                        saved=conn.execute('SELECT payload FROM runs WHERE id=? AND workspace=?',(child,w)).fetchone()
                        if not saved:raise ValueError('全文解析子任务不属于本工作区')
                        payload=json.loads(saved['payload']);payload.update(parent_run_id=rid,provider_budget=0,index_dense=False)
                        conn.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(payload,ensure_ascii=False),child))
                row['status']='downloaded' if not imported.get('metadata_only',True) else 'metadata_only'
            except (ValueError,OSError) as error:
                row.update(status='failed',error=str(error)[:300])
            downloads.append(row);checkpoint(run,{'audit_downloads':downloads})
            store.event(rid,'candidate_fulltext',{'identity':paper['identity'],'status':row['status'],'run_id':row.get('run_id')})
    pending=[c['id'] for c in child_statuses(w,[d['run_id'] for d in downloads if d.get('run_id')]) if c['status'] in PENDING]
    checkpoint(run,{'waiting_children':pending})
    if pending:
        return {'status':'waiting_children','answer':'候选全文已下载，正在独立解析池处理；完成后继续时间和条件核查。','claims':[],'downloads':downloads}
    all_context=source_context(w,[v['id'] for v in store.rows('SELECT id FROM versions WHERE workspace=? AND deleted=0 AND work_id<>?',(w,old['work_id']))])
    comparisons=[{'version_id':c['id'],**compare_time(old,c)} for c in all_context]
    later=[c['version_id'] for c in comparisons if c['status']=='later']
    excluded=[c for c in comparisons if c['status']!='later']
    available=[]
    for vid in later:
        if store.one("SELECT 1 FROM current_blocks b JOIN versions v ON v.id=b.version_id WHERE b.workspace=? AND b.version_id=? AND v.status='ready' LIMIT 1",(w,vid)):available.append(vid)
    result={'source':block,'source_versions':[old]+all_context,'query':p['question'],'searched_at':search.get('searched_at'),
            'search':search,'downloads':downloads,'excluded_by_time':excluded,'time_comparisons':comparisons,
            'scope_notice':'仅覆盖本次检索来源及可访问全文；日期区间重叠和未知记录不当作已确认后续工作。没有全球首次结论。'}
    if not available:
        result.update(answer='当前检索范围内没有可用于判断的、更晚且已完成解析的全文证据。候选标题或摘要不能证明问题已被解决。',
                      status='partial',claims=[],model=None,coverage='insufficient')
    else:
        if 'audit_evidence' not in snap:
            from .retrieval import retrieve
            ret=retrieve(w,available,p['question'],limit=14)
            snap['audit_evidence']=[block]+ret.get('blocks',[]);checkpoint(run,{'audit_evidence':snap['audit_evidence']})
        evidence=snap['audit_evidence']
        if 'model_response' not in snap:
            prompt={'old_suggestion':block,'source_versions':[old]+[c for c in all_context if c['id'] in available],
                    'question':p['question'],'time_comparisons':comparisons,'available_fulltext_evidence':evidence,
                    'requirements':'逐项比较发表日期精度、任务、数据、模型与适用条件，说明覆盖什么和尚未覆盖什么。各项只允许直接相关证据/部分覆盖/当前范围证据不足/尚未完成无法判断。引用必须来自实际全文，摘要和标题不是结论证据；最多6条原子主张，不宣称彻底解决或全球首次。'}
            snap['model_response']=models.generate(SYSTEM,json.dumps(prompt,ensure_ascii=False),rid,core=True)
            checkpoint(run,{'model_response':snap['model_response']})
        response=snap['model_response']
        validated=validate_answer(json.loads(response['text']),evidence,workspace=w,version_ids=[p['version_id']]+available)
        from .evidence_validation import review_live
        validated=review_live(run,validated,evidence,[p['version_id']]+available,p['question'])
        result.update(validated,model=response['model'],usage=response['usage'])
    with store.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        current=conn.execute('SELECT status FROM runs WHERE id=? AND workspace=?',(rid,w)).fetchone()
        if not current or current['status']=='cancelled':return {}
        existing=conn.execute("SELECT id FROM artifacts WHERE workspace=? AND run_id=? AND kind='idea_audit'",(w,rid)).fetchone()
        aid=existing['id'] if existing else store.uid()
        if not existing:conn.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)',(aid,w,rid,'idea_audit',p['question'][:100],json.dumps(result,ensure_ascii=False),time.time()))
    result['artifact_id']=aid
    return result
