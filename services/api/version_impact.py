"""New evidence maps; historical notes, quotes and parser blocks are read-only."""
import hashlib
import json
import re
from . import store
from .evidence_validation import canonical


def assess(workspace,left,right):
    from .snapshots import selected_parse,snapshot_blocks
    versions=[]
    for vid in (left,right):
        v=store.one('SELECT id,work_id,title,sha256 FROM versions WHERE id=? AND workspace=? AND deleted=0',(vid,workspace))
        if not v:raise ValueError('比较版本不存在或无权限')
        versions.append(v)
    if versions[0]['work_id']!=versions[1]['work_id']:raise ValueError('笔记影响分析需要同一作品的两个不可变版本')
    parse=selected_parse(workspace,right)
    blocks=snapshot_blocks(workspace,right,parse['id'])
    if len(blocks)>10000 or sum(len(b['text']) for b in blocks)>10*1024**2:
        raise ValueError('此文档超出同步笔记影响分析范围；需缩小所选版本')
    normalized=[(b,canonical(b['text'])[0]) for b in blocks]
    notes=store.rows("SELECT id,title,payload FROM artifacts WHERE workspace=? AND kind IN ('research_note','idea_audit') ORDER BY created DESC LIMIT 200",(workspace,))
    changes=[]
    for note in notes:
        payload=json.loads(note['payload'])
        for index,claim in enumerate(payload.get('claims',[])):
            old=[e for e in claim.get('evidence',[]) if e.get('version_id')==left]
            if not old:continue
            mappings=[]
            for evidence in old:
                quote=canonical(evidence['quote'])[0]
                matches=[b for b,text in normalized if quote and quote in text]
                if len(matches)==1:
                    b=matches[0]
                    mappings.append({'status':'source_unchanged','old':evidence,'new':{'version_id':right,'parse_id':parse['id'],'block_id':b['id'],'page_index':b['page_index'],'bbox':json.loads(b['bbox']) if isinstance(b['bbox'],str) else b['bbox'],'quote':evidence['quote']},
                                     'notice':'原引文在新版本仍能唯一定位；语义审查沿用原记录，尚未重新审查。'})
                elif len(matches)>1:
                    mappings.append({'status':'ambiguous','old':evidence,'candidate_block_ids':[b['id'] for b in matches[:10]],'notice':'新版本有多处相同引文，需要人工选择；不自动迁移。'})
                else:
                    terms=set(re.findall(r'[a-z]{3,}|[\u4e00-\u9fff]{2}',evidence['quote'].lower()))
                    ranked=[]
                    for b,_ in normalized:
                        words=set(re.findall(r'[a-z]{3,}|[\u4e00-\u9fff]{2}',b['text'].lower()))
                        score=len(terms & words)/max(1,len(terms|words))
                        if score>.2:ranked.append((score,b))
                    best=sorted(ranked,key=lambda item:item[0],reverse=True)[:2]
                    mappings.append({'status':'source_changed_requires_review' if best else 'source_not_found','old':evidence,
                                     'candidates':[{'block_id':b['id'],'version_id':right,'page_index':b['page_index'],'text':b['text'],'similarity':score} for score,b in best],
                                     'notice':'旧引文在新版本未完整匹配；相似段落只用于复核，不能证明结论被支持或推翻。'})
            changes.append({'artifact_id':note['id'],'title':note['title'],'claim_id':claim.get('id',str(index)),
                            'claim_text':claim['text'],'historical_review':claim.get('review'),
                            'status':'source_unchanged' if all(m['status']=='source_unchanged' for m in mappings) else 'needs_review','mappings':mappings})
    manifest={'versions':versions,'target_parse_id':parse['id'],'notes':[n['id'] for n in notes]}
    key=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    result={'status':'PASS','scope':'source_locations_only','fingerprint':key,'left':versions[0],'right':versions[1],
            'target_parse_id':parse['id'],'claims':changes,'unchanged':sum(c['status']=='source_unchanged' for c in changes),
            'needs_review':sum(c['status']=='needs_review' for c in changes),'provider_calls':0,
            'notice':'历史笔记和旧引文保持不变。本报告比较原文位置，不能代替新版本的独立语义审查。'}
    previous=store.one("SELECT id FROM artifacts WHERE workspace=? AND kind='version_impact' AND json_extract(payload,'$.fingerprint')=?",(workspace,key))
    result['artifact_id']=previous['id'] if previous else store.artifact(workspace,None,'version_impact','版本变化对笔记的影响',result)
    return result
