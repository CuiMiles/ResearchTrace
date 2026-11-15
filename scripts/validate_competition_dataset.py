"""No-provider real HTTP acceptance of the user supplied corpus.

Requires a successfully published/click-tested workflow first. Each completed
operation immediately updates that workflow. Secrets stay in private data/.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from dotenv import dotenv_values
from services.api import store

OUT = ROOT / 'evidence/competition-dataset'
STATE = OUT / 'workflow.json'
BASE = 'http://127.0.0.1:18980'


def now():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temp.replace(path)


def record(step_id, rid, label, status, summary, *, files=None, results=None, evidence=None, **kw):
    data = json.loads(STATE.read_text())
    step = next((s for s in data['steps'] if s['id'] == step_id), None)
    if step is None:
        step = {'id': step_id, 'runs': []}
        data['steps'].append(step)
    old = next((r for r in step['runs'] if r['id'] == rid), {})
    run = dict(id=rid, label=label, status=status, summary=summary, files=files or [],
               evidence_files=[{'path': str(p.relative_to(ROOT))} for p in evidence or []],
               screenshots=kw.pop('screenshots', []), started=old.get('started', now()), **kw)
    if status != 'NOT RUN':
        run['finished'] = now()
    if results is not None:
        run['results'] = results
    step['runs'] = [run if r['id'] == rid else r for r in step['runs']]
    if not old:
        step['runs'].append(run)
    data['updated_at'] = now()
    save_json(STATE, data)


def cookie():
    private = ROOT / 'data/competition-dataset-session.json'
    if private.is_file():
        return json.loads(private.read_text())['cookie']
    code = dotenv_values(ROOT / '.env')['RT_ADMIN_CODE']
    with httpx.Client(base_url=BASE, trust_env=False, timeout=30) as client:
        response = client.post('/api/v1/auth/login', json={'code': code})
        response.raise_for_status()
        data = dict(cookie=client.cookies.get('rt_session'), workspace=response.json()['workspace'])
    private.write_text(json.dumps(data))
    private.chmod(0o600)
    return data['cookie']


def fingerprint(vid, page_max=None):
    query = 'SELECT id,text,bbox,source,quality FROM blocks WHERE version_id=?'
    args = [vid]
    if page_max is not None:
        query += ' AND page_index<?'
        args.append(page_max)
    rows = store.rows(query + ' ORDER BY id', args)
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def ingest(resume=False):
    before = json.loads((OUT / 'browser-before.json').read_text())
    assert before['status'] == 'PASS' and before['phase'] == 'before'
    data = json.loads(STATE.read_text())
    if data.get('test_execution_started') and not resume:
        raise RuntimeError('Dataset acceptance already started; inspect durable results before rerunning')
    data.update(test_execution_started=True, published_at=before['observed_at'], testing_started_at=data.get('testing_started_at', now()), updated_at=now())
    save_json(STATE, data)
    manifest = data['dataset']
    files = [f for f in manifest['files'] if f.get('role') == 'test_input']
    order = ['1706.03762v7.pdf', '1706.03762v1.pdf', '1706.03762v1_img.pdf', 'UnderstandingDeepLearning_02_09_26_C.pdf']
    files.sort(key=lambda f: order.index(f['name']) if f['name'] in order else 10)
    quota = store.rows('SELECT * FROM quota ORDER BY id')
    results = json.loads((OUT/'ingestion.json').read_text()) if resume else {'status': 'NOT RUN', 'started': now(), 'provider_calls': 0, 'documents': []}
    save_json(OUT / 'ingestion.json', results)
    first_two = []
    with httpx.Client(base_url=BASE, cookies={'rt_session': cookie()}, trust_env=False, timeout=90) as client:
        for index, file in enumerate(files):
            src = ROOT / manifest['extracted_root'] / file['relative_path']
            raw = src.read_bytes()
            assert hashlib.sha256(raw).hexdigest() == file['sha256']
            renamed = f'corpus-{index+1:02d}-{file["sha256"][:8]}.pdf'
            started = time.monotonic()
            info = next((d for d in results['documents'] if d['file']['sha256'] == file['sha256']), None)
            if info is None:
                resp = client.post('/api/v1/documents?index_dense=false', files={'files': (renamed, raw, 'application/pdf')})
                resp.raise_for_status()
                uploaded = resp.json()
                vid = uploaded['documents'][0]['id']
                rid = uploaded['runs'][0]['id'] if uploaded['runs'] else None
                assert rid, 'Fresh isolated workspace should create an actual parse run'
                info = dict(file=file, upload_name=renamed, version_id=vid, run_id=rid, uploaded_at=now())
                results['documents'].append(info)
            else:
                vid, rid = info['version_id'], info['run_id']
            save_json(OUT / 'ingestion.json', results)
            record('upload', 'upload-' + vid, file['name'] + ' · 改名上传', 'PASS',
                   '实际 HTTP 上传成功；记录独立版本和解析任务，关闭 embedding。', files=[file],
                   results={'upload_name': renamed, 'version_id': vid, 'run_id': rid, 'index_dense': False}, run_ids=[rid], evidence=[OUT/'ingestion.json'])
            checkpoint_hash = None
            checkpoint_pages = None
            canceled = False
            last_progress = -1
            deadline = time.monotonic() + 2400
            while time.monotonic() < deadline:
                response = client.get('/api/v1/runs/' + rid)
                response.raise_for_status()
                run = response.json()
                revision = store.one('SELECT * FROM parses WHERE id=?', (vid,)) or {'parsed_pages': 0}
                if revision['parsed_pages'] != last_progress:
                    last_progress = revision['parsed_pages']
                    record('parse', 'native-' + vid, file['name'] + ' · 原生全文 / 扫描 OCR', 'NOT RUN',
                           f'正在实际处理 {last_progress}/{file["page_count"]} 页，尚未判定通过。', files=[file],
                           counts={'processed_pages': last_progress, 'expected_pages': file['page_count']}, run_ids=[rid], evidence=[OUT/'ingestion.json'])
                if file['page_count'] == 541 and not canceled and 30 <= last_progress < 541:
                    client.post('/api/v1/runs/' + rid + '/cancel').raise_for_status()
                    # Native page work may finish after cancel; wait until its execution lock is released.
                    for _ in range(300):
                        with store.run_execution_lock(rid) as acquired:
                            if acquired:
                                checkpoint_pages = store.one('SELECT parsed_pages FROM parses WHERE id=?', (vid,))['parsed_pages']
                                checkpoint_hash = fingerprint(vid, checkpoint_pages)
                                break
                        time.sleep(.1)
                    assert checkpoint_hash and checkpoint_pages >= 30
                    response = client.post('/api/v1/runs/' + rid + '/resume')
                    response.raise_for_status()
                    canceled = True
                    print(f'textbook cancelled/resumed at {checkpoint_pages} committed pages', flush=True)
                    time.sleep(.3)
                    continue
                if run['status'] not in ('queued', 'running'):
                    break
                time.sleep(.3)
            else:
                client.post('/api/v1/runs/' + rid + '/cancel')
                raise TimeoutError('Only this dataset parse job exceeded its test deadline')
            pages = store.rows('SELECT page_index,status,length(text) chars FROM pages WHERE version_id=? ORDER BY page_index', (vid,))
            counts = store.rows('SELECT source,quality,count(*) blocks FROM blocks WHERE version_id=? GROUP BY source,quality', (vid,))
            info.update(run_status=run['status'], error=run.get('error'), result=run.get('result'),
                        duration_seconds=round(time.monotonic()-started, 2), pages=pages, block_counts=counts)
            processed = len(pages) == file['page_count']
            info['status'] = 'PASS' if run['status'] == 'completed' and processed else 'FAIL'
            save_json(OUT/'ingestion.json', results)
            record('parse', 'native-' + vid, file['name'] + ' · 原生全文 / 扫描 OCR', info['status'],
                   f'实际处理 {len(pages)}/{file["page_count"]} 页；任务 {run["status"]}；原生逐页输出与 OCR 质量状态见原始记录。',
                   files=[file], results={'run_status': run['status'], 'error': run.get('error'), 'sources': counts},
                   counts={'processed_pages': len(pages), 'expected_pages': file['page_count']}, duration_seconds=info['duration_seconds'],
                   run_ids=[rid], evidence=[OUT/'ingestion.json'])
            if checkpoint_hash:
                after_hash = fingerprint(vid, checkpoint_pages)
                preserved = checkpoint_hash == after_hash
                record('recovery', 'textbook-native-resume', '541 页原教材 · 取消与检查点恢复',
                       'PASS' if preserved and processed else 'FAIL',
                       f'在已提交 {checkpoint_pages} 页时取消，等待执行锁释放后恢复；最终 {len(pages)} 页。', files=[file],
                       results={'checkpoint_pages': checkpoint_pages, 'hash_before': checkpoint_hash, 'hash_after': after_hash,
                                'checkpoint_unchanged': preserved, 'processed_pages': len(pages)}, run_ids=[rid], evidence=[OUT/'ingestion.json'])
            # Verify actual nonempty middle/back/end pages through authenticated FTS -> page API.
            located = []
            for desired in sorted({0, min(file['page_count']-1, file['page_count']//2), file['page_count']-1}):
                blocks = store.rows('SELECT * FROM blocks WHERE version_id=? AND page_index=? ORDER BY reading_order', (vid, desired))
                candidate = next((b for b in blocks if len(re.findall(r'[A-Za-z]{5,}', b['text'])) >= 2), None)
                if not candidate:
                    located.append({'page_index': desired, 'status': 'NOT RUN', 'reason': '该页无可搜索的英文正文块；未伪造词句'})
                    continue
                words = list(dict.fromkeys(re.findall(r'[A-Za-z]{5,}', candidate['text'])))
                query = words[0]
                hits = client.get(f'/api/v1/documents/{vid}/search', params={'q': query, 'parse_id': vid}).json()
                # Search has a bounded result window: try discriminating words until the intended page appears.
                hit = next((h for h in hits if h['page_index'] == desired), None)
                for word in words[1:12]:
                    if hit:
                        break
                    query = word
                    hits = client.get(f'/api/v1/documents/{vid}/search', params={'q': query, 'parse_id': vid}).json()
                    hit = next((h for h in hits if h['page_index'] == desired), None)
                if not hit:
                    located.append({'page_index': desired, 'status': 'FAIL', 'reason': '实际索引未返回目标页；保留失败'})
                    continue
                page = client.get(f'/api/v1/documents/{vid}/pages/{desired}', params={'parse_id': vid})
                page.raise_for_status()
                assert any(b['id'] == hit['id'] for b in page.json()['blocks'])
                located.append(dict(status='PASS', page_index=desired, printed_label=page.json().get('label'), query=query,
                                    block_id=hit['id'], parse_id=vid, bbox=hit['bbox'], quote=hit['text'][:250]))
            info['locations'] = located
            save_json(OUT/'ingestion.json', results)
            record('snapshots', 'fts-' + vid, file['name'] + ' · 首中末页索引与定位',
                   'FAIL' if any(x['status']=='FAIL' for x in located) else 'PASS',
                   '使用实际正文词语查询 FTS，并按 parse_id 核对页内块；无模型请求。', files=[file], results=located,
                   evidence=[OUT/'ingestion.json'])
            if index < 2:
                first_two.append(vid)
            if index == 1:
                duplicate = client.post('/api/v1/documents?index_dense=false', files={'files': ('again-different-name.pdf', raw, 'application/pdf')})
                duplicate.raise_for_status()
                assert duplicate.json()['documents'][0]['id'] == vid
                left, right = [client.get('/api/v1/documents/'+v+'/status').json() for v in first_two]
                assert left['work_id'] == right['work_id'] and left['id'] != right['id']
                compare = client.post('/api/v1/versions/compare', json={'left': first_two[0], 'right': first_two[1]})
                compare.raise_for_status()
                save_json(OUT/'version-comparison.json', compare.json())
                record('analysis', 'v7-v1-compare', 'Transformer v7 → v1 · 内容去重与版本比较', 'PASS',
                       '依次改名上传 v7/v1，识别为同 Work 的两个不可变版本；相同字节再次改名上传去重。实际比较未调用模型。',
                       files=files[:2], results={'same_work': True, 'distinct_versions': first_two, 'same_bytes_duplicate': True},
                       evidence=[OUT/'version-comparison.json'])
            print(f'{index+1}/{len(files)} {file["name"]}: {info["status"]} {len(pages)} pages {info["duration_seconds"]}s', flush=True)
    results.update(status='PASS' if all(d['status']=='PASS' for d in results['documents']) else 'FAIL',
                   finished=now(), quota_unchanged=quota==store.rows('SELECT * FROM quota ORDER BY id'))
    save_json(OUT/'ingestion.json', results)
    assert results['quota_unchanged'], 'Provider quota changed during no-provider test'
    print(json.dumps({'status': results['status'], 'documents': len(results['documents']), 'quota_unchanged': results['quota_unchanged']}), flush=True)


if __name__ == '__main__':
    ingest(resume='--resume' in sys.argv)
