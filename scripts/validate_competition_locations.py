"""Source-derived FTS location checks, excluding repeated running headers."""
from collections import Counter
import json
from pathlib import Path
import random
import re
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from validate_competition_dataset import BASE, OUT, cookie, save_json, now
sys.path.insert(0,str(ROOT))
from services.api import store
import httpx


def locations():
    ingestion=json.loads((OUT/'ingestion.json').read_text())
    enhanced=json.loads((OUT/'enhanced.json').read_text())
    book=next((r for r in enhanced if r.get('engine')=='native' and r.get('status')=='PASS'),None)
    assert book
    report={'status':'NOT RUN','started':now(),'provider_calls':0,'documents':[]}
    with httpx.Client(base_url=BASE,cookies={'rt_session':cookie()},trust_env=False,timeout=60) as client:
        for doc in ingestion['documents']:
            vid=doc['version_id'];file=doc['file'];pid=book['parse_id'] if file['page_count']==541 else vid
            blocks=store.rows('SELECT b.* FROM blocks b LEFT JOIN block_parses m ON m.block_id=b.id WHERE b.version_id=? AND COALESCE(m.parse_id,b.version_id)=? ORDER BY page_index,reading_order',(vid,pid))
            body=[b for b in blocks if b['type'] not in ('header','footer','figure')]
            frequencies=Counter(w.lower() for b in body for w in re.findall(r'[A-Za-z]{5,}',b['text']))
            desired={0,file['page_count']//2,file['page_count']-1}
            if file['page_count']==541:
                desired.update(random.Random(file['sha256']).sample(range(271,541),3))
                desired.update((300,499))
            found=[]
            for page_index in sorted(desired):
                candidates=[b for b in body if b['page_index']==page_index]
                words={w for b in candidates for w in re.findall(r'[A-Za-z]{5,}',b['text'])}
                choices=sorted(words,key=lambda w:(frequencies[w.lower()],-len(w),w))[:30]
                if not choices:
                    found.append({'status':'NOT RUN','page_index':page_index,'reason':'本页没有可检索的英文正文词，未使用重复页眉作为正文覆盖证明。'})
                    continue
                hit=None
                for query in choices:
                    response=client.get(f'/api/v1/documents/{vid}/search',params={'q':query,'parse_id':pid})
                    response.raise_for_status()
                    hit=next((b for b in response.json() if b['page_index']==page_index),None)
                    if hit:break
                if not hit:
                    found.append({'status':'FAIL','page_index':page_index,'queries':choices})
                    continue
                response=client.get(f'/api/v1/documents/{vid}/pages/{page_index}',params={'parse_id':pid})
                response.raise_for_status();page=response.json()
                assert page['parse_id']==pid and any(b['id']==hit['id'] for b in page['blocks'])
                found.append(dict(status='PASS',page_index=page_index,parse_id=pid,query=query,block_id=hit['id'],bbox=hit['bbox'],quote=hit['text'][:350]))
            report['documents'].append(dict(file=file,version_id=vid,parse_id=pid,locations=found))
    statuses=Counter(l['status'] for d in report['documents'] for l in d['locations'])
    report.update(status='FAIL' if statuses['FAIL'] else 'PASS',counts=dict(statuses),finished=now(),
                  scope='只验证实际正文词的 FTS → 版本/页/块/bbox 定位；不声称密集索引或模型问答质量。')
    save_json(OUT/'location-recheck.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='documents'},ensure_ascii=False))


if __name__=='__main__':locations()
