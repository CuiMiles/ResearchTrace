"""Expiring operational checks; never makes an inference or paid request."""
import os
import time
from . import models,store
from .worker_health import read_worker_status


def inspect(workspace):
    components={'database':{'status':'PASS' if store.one('SELECT 1 n') else 'FAIL'}}
    for pool in ('documents','interactive'):
        item=read_worker_status(pool)
        components['worker_'+pool]={'status':'PASS' if item['healthy'] else 'BLOCKED',
                                   'busy':item.get('busy'),'reason':item.get('reason')}
    try:
        from .embedding_providers import LocalRetrievalProvider
        provider=LocalRetrievalProvider()
        manifest=provider._call('/manifest',timeout=3)
        wanted=(provider.model_id,os.getenv('RT_LOCAL_RERANK_MODEL','nvidia/Nemotron-3.5-Rerank-8B-BF16'))
        available=[{'model_id':m['model_id'],'revision':m['revision'],'weights_ready':m['weights_ready'],
                    'inference_verified':m.get('inference_verified',False)} for m in manifest['models'] if m['model_id'] in wanted]
        if os.getenv('RT_RERANK_BASE'):
            remote=LocalRetrievalProvider(wanted[1],os.getenv('RT_RERANK_BASE'))
            rerank_manifest=remote._call('/manifest',timeout=3)
            available=[m for m in available if m['model_id']!=wanted[1]]
            available.extend({k:m.get(k,False) for k in ('model_id','revision','weights_ready','inference_verified')} for m in rerank_manifest['models'] if m['model_id']==wanted[1])
        verified=len(available)==2 and all(m['weights_ready'] and m['inference_verified'] for m in available)
        components['local_models']={'status':'PASS' if verified else 'BLOCKED','reachable':True,'models':available}
    except (ValueError,OSError,KeyError):
        components['local_models']={'status':'BLOCKED','reachable':False,'reason':'模型服务未配置或当前不可达；未调用云端替代'}
    from .app import local_index_status
    versions=store.rows('SELECT id FROM versions WHERE workspace=? AND deleted=0',(workspace,))
    coverage=[local_index_status(workspace,v['id']) for v in versions]
    expected=sum(v['eligible_blocks'] for v in coverage);covered=sum(v['indexed_blocks'] for v in coverage)
    components['index']={'status':'PASS' if expected>0 and covered==expected else 'BLOCKED',
                         'eligible_blocks':expected,'indexed_blocks':covered,
                         'semantic_ready_documents':sum(v['semantic_ready'] for v in coverage),'documents':len(versions)}
    policy=models.budget_policy()
    used=store.one('SELECT count(*) n FROM quota WHERE model=? AND day=?',(models.CORE,models.quota_day(time.time())))['n']
    configured=any(bool(key) for _,key in models.credentials())
    components['analysis']={'status':'NOT RUN' if configured else 'BLOCKED','model':models.CORE,
                            'configured':configured,'profile':policy['profile'],'local_daily_attempts':used,
                            'reason':'此检查不发送模型请求；配置与账本不证明上游当前可用','paid_fallback':False}
    recent=store.one('SELECT status,started FROM quota WHERE model=? ORDER BY started DESC LIMIT 1',(models.CORE,))
    if configured and recent and recent['status']=='ok' and time.time()-recent['started']<300:
        components['analysis'].update(status='PASS',last_verified_at=recent['started'],reason='最近5分钟内有真实成功调用；本次检查未调用模型')
    components['public_https']={'status':'NOT RUN','reason':'本地健康检查不能证明外网新浏览器可达'}
    return {'status':'PASS' if all(c['status']=='PASS' for c in components.values()) else 'BLOCKED',
            'checked_at':time.time(),'valid_for_seconds':15,'provider_calls':0,'components':components}
