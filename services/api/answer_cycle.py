"""One evidence-driven revision, with durable receipts and no sent retry."""
import copy
import json
import os

from . import models, store


def _snapshot(rid):
    return json.loads(store.one('SELECT checkpoint FROM runs WHERE id=?',(rid,))['checkpoint'] or '{}')


def _checked(run,response,blocks,versions,question):
    from .evidence_validation import validate,review_live
    try:
        result=validate(json.loads(response['text']),blocks,workspace=run['workspace'],version_ids=versions)
    except ValueError as error:
        # The original response stays in the checkpoint/trace, never in the
        # published free text when deterministic validation has rejected it.
        text='回答未通过原文、数值或正文绑定检查，当前证据不足以发布该结论。'
        return {'answer':text,'answer_segments':[{'text':text,'claim_ids':['validation-blocked']}],
                'claims':[{'id':'validation-blocked','text':text,'type':'insufficient','evidence':[],
                           'review':{'status':'not_checked','method':'deterministic_rejection'}}],
                'status':'partial','evidence_review':'deterministic_rejection',
                'validation_failure':{'type':type(error).__name__,'reason':str(error).splitlines()[0][:500]}}
    return review_live(run,result,blocks,versions,question)


def complete(run,response,blocks,versions,question,retrieval):
    from .jobs import answer_role,checkpoint,SYSTEM,source_context
    rid=run['id'];snap=_snapshot(rid)
    if 'answer_revision_result' in snap:
        saved=snap['answer_revision_result']
        return saved['result'],saved['response'],saved['blocks'],saved['retrieval']
    first=_checked(run,response,blocks,versions,question)
    # A missing/unavailable critic alone does not justify another generation.
    needs_revision=first.get('evidence_review')=='deterministic_rejection' or (
        first.get('evidence_review')=='machine_reviewed' and first.get('status')=='partial')
    if os.getenv('RT_ANSWER_REVISION','true').lower()!='true' or not needs_revision or store.cancelled(rid):
        return first,response,blocks,retrieval
    checkpoint(run,{'answer_first_review':first})
    if 'answer_revision_response' not in snap and snap.get('answer_revision_attempted'):
        first['revision']={'status':'BLOCKED','reason':'修订请求已尝试但没有可恢复的响应；不自动重发。'}
        return first,response,blocks,retrieval
    if 'answer_revision_response' not in snap and models.workflow_budget(rid)['remaining']<1:
        first['revision']={'status':'BLOCKED','reason':'本工作流核心调用预算已用尽，保留待复核结果。'}
        return first,response,blocks,retrieval
    if 'answer_revision_retrieval' not in snap:
        from .retrieval import retrieve
        issues=[{'id':c['id'],'text':c.get('original_text',c['text']),
                 'review':c.get('review',{})} for c in first['claims']
                if c.get('review',{}).get('status')!='supported'][:8]
        query=(question[:700]+' '+ ' '.join(c['text'] for c in issues)[:700])[:1000]
        store.event(rid,'answer_gap_detected',{'issues':len(issues),'validation_rejected':bool(first.get('validation_failure')),'max_revisions':1})
        if run['kind']=='agent':
            from .tool_registry import ToolContext,execute_tool
            tool=execute_tool(ToolContext(workspace=run['workspace'],run_id=rid,call_id='answer-gap-retrieval'),
                              'retrieve_evidence',{'version_ids':versions,'question':query,'limit':12})
            supplemental=tool['result'] if tool['status']=='PASS' else {'blocks':[],'mode':'budget_or_tool_blocked','notice':tool['summary']}
        else:
            supplemental=retrieve(run['workspace'],versions,query,limit=12)
        by_id={b['id']:b for b in blocks}
        for block in supplemental.get('blocks',[]):
            if block['id'] not in by_id:by_id[block['id']]=block
        revised_blocks=list(by_id.values())[:40]
        snap['answer_revision_retrieval']={'blocks':revised_blocks,'supplemental':supplemental,'query':query,'issues':issues}
        checkpoint(run,{'answer_revision_retrieval':snap['answer_revision_retrieval']})
        store.event(rid,'answer_gap_retrieved',{'previous_blocks':len(blocks),'combined_blocks':len(revised_blocks),
                                              'new_blocks':len(set(by_id)-{b['id'] for b in blocks})})
    revision=snap['answer_revision_retrieval'];revised_blocks=revision['blocks']
    if store.cancelled(rid):return first,response,blocks,retrieval
    if 'answer_revision_response' not in snap:
        prompt={'task':question,'mode':run['kind'],'versions':source_context(run['workspace'],versions),
                'evidence':[{k:b[k] for k in ('id','version_id','page_index','text')} for b in revised_blocks],
                'previous_draft':response['text'][:30000],
                'validation_failure':first.get('validation_failure'),'review_findings':revision['issues'],
                'requirements':'根据真实补检索与审查反馈修订一次。此前草稿不是证据。只回答所问事实，拆成简短原子主张，删除未获支持的附加解释；证据仍不足则明确说明。逐字引用不要手抄block_id、页码到事实正文；输出仍严格符合原JSON主张/正文绑定契约。'}
        checkpoint(run,{'answer_revision_attempted':True})
        store.event(rid,'answer_revising',{'revision':1,'max_revisions':1,'received_response_is_checkpointed':True})
        try:
            snap['answer_revision_response']=models.generate(SYSTEM,json.dumps(prompt,ensure_ascii=False),rid,role=answer_role(run))
        except models.ModelError as error:
            checkpoint(run,{'answer_revision_error':{'type':type(error).__name__}})
            first['revision']={'status':'BLOCKED','reason':'修订调用未得到有效响应，调用已计账，不自动重发。'}
            return first,response,blocks,retrieval
        checkpoint(run,{'answer_revision_response':snap['answer_revision_response']})
    revised_response=snap['answer_revision_response']
    result=_checked(run,revised_response,revised_blocks,versions,question)
    result['revision']={'status':'PASS' if result.get('status')=='ready' else 'FAIL','attempts':1,
                        'first_review_status':first.get('status'),'original_response_preserved':True,
                        'supplemental_mode':revision['supplemental'].get('mode'),
                        'new_evidence_blocks':len({b['id'] for b in revised_blocks}-{b['id'] for b in blocks})}
    final_retrieval={**retrieval,'revision':{'query':revision['query'],'supplemental':revision['supplemental']},'blocks':revised_blocks}
    checkpoint(run,{'answer_revision_result':{'result':copy.deepcopy(result),'response':revised_response,
                                            'blocks':revised_blocks,'retrieval':final_retrieval}})
    store.event(rid,'answer_revision_checked',{'status':result['revision']['status'],'answer_status':result.get('status'),'max_revisions':1})
    return result,revised_response,revised_blocks,final_retrieval
