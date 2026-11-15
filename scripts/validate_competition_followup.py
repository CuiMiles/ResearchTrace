"""Real CPU/parser revisions and downstream checks on the extracted corpus."""
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from validate_competition_dataset import OUT, BASE, cookie, now, record, save_json
sys.path.insert(0, str(ROOT))
import httpx
from pypdf import PdfReader, PdfWriter
from services.api import store


def snapshot_hash(vid, pid):
    rows = store.rows('SELECT b.id,b.text,b.bbox FROM blocks b LEFT JOIN block_parses m ON m.block_id=b.id WHERE b.version_id=? AND COALESCE(m.parse_id,b.version_id)=? ORDER BY b.id', (vid, pid))
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def wait(client, rid, seconds=2400, progress=None):
    deadline = time.monotonic() + seconds
    last = -1
    while time.monotonic() < deadline:
        response = client.get('/api/v1/runs/' + rid)
        response.raise_for_status()
        run = response.json()
        if progress:
            revision = store.one('SELECT parsed_pages,page_count FROM parses WHERE id=?', (progress[0],))
            if revision and revision['parsed_pages'] != last:
                last = revision['parsed_pages']
                progress[1](revision)
        if run['status'] not in ('queued', 'running'):
            return run
        time.sleep(.5)
    client.post('/api/v1/runs/' + rid + '/cancel').raise_for_status()
    raise TimeoutError('Only this project test exceeded its deadline and was cancelled')


def reparse(client, entry, engine, device='cpu', test_id=None):
    file, vid = entry['file'], entry['version_id']
    tid = test_id or f'{engine}-{device}-{vid}'
    path = OUT / (tid + '.json')
    snapshots = client.get(f'/api/v1/documents/{vid}/parses').json()
    old = {p['id']: snapshot_hash(vid, p['id']) for p in snapshots}
    start = time.monotonic()
    wall_start = time.time()
    response = client.post(f'/api/v1/documents/{vid}/parses', json={'engine': engine, 'device': device, 'idempotency_key': 'dataset-' + tid})
    response.raise_for_status()
    queued = response.json()
    pid, rid = queued['parse_id'], queued['id']
    result = dict(status='NOT RUN', engine=engine, device=device, version_id=vid, parse_id=pid,
                  run_id=rid, input_file=file, started=now(), provider_calls=0,
                  source=entry.get('derivative_source'), prior_hashes=old)
    def progress(revision):
        save_json(path, result)
        record('parse', tid, f'{file["name"]} · {engine} {device}', 'NOT RUN',
               f'实际解析中：{revision["parsed_pages"]}/{revision["page_count"]} 页，尚未判定通过。',
               files=[file], counts=revision, run_ids=[rid], evidence=[path])
    run = wait(client, rid, progress=(pid, progress))
    result.update(finished=now(), duration_seconds=round(time.monotonic()-start, 2),
                  run_status=run['status'], result=run.get('result'), error=run.get('error'))
    blocked = any(s in (run.get('error') or '') for s in ('GPU', 'WSL', 'time limit exceeded', 'free memory insufficient'))
    result['status'] = 'PASS' if run['status'] == 'completed' else 'BLOCKED' if blocked else 'FAIL'
    result['old_snapshots_unchanged'] = all(snapshot_hash(vid, p) == h for p, h in old.items())
    assert result['old_snapshots_unchanged'], 'Published old snapshot drifted'
    blocks = store.rows('SELECT b.* FROM blocks b LEFT JOIN block_parses m ON m.block_id=b.id WHERE b.version_id=? AND COALESCE(m.parse_id,b.version_id)=? ORDER BY page_index,reading_order', (vid, pid))
    from collections import Counter
    result['counts'] = dict(blocks=len(blocks), types=dict(Counter(b['type'] for b in blocks)),
                             sources=dict(Counter(b['source'] for b in blocks)))
    result['provenance'] = json.loads(store.one('SELECT provenance FROM parses WHERE id=?', (pid,))['provenance'])
    result['monitors'] = []
    # Fixed single main worker runs these requests serially. Retain matching engine
    # monitors within this operation's wall interval; no logs/credentials copied.
    for monitor in (ROOT/'data/parsing').glob('*/result.monitor.json'):
        if monitor.stat().st_mtime >= wall_start:
            data = json.loads(monitor.read_text())
            if data.get('engine') == engine and data.get('device') == device:
                result['monitors'].append(data)
    if engine == 'native' and run['status'] == 'completed':
        result['blank_pages'] = store.rows("SELECT page_index,status FROM parse_pages WHERE parse_id=? AND status='blank'", (pid,))
    result['examples'] = {kind: next(({'page_index': b['page_index'], 'id': b['id'], 'bbox': json.loads(b['bbox']), 'text': b['text'][:3000]} for b in blocks if b['type']==kind), None)
                          for kind in ('table', 'equation', 'paragraph')}
    result['examples']['formula'] = result['examples']['equation']
    if result['status']=='PASS':
        assert blocks and result['provenance']['engine'] == engine
        assert all(b['source']==engine for b in blocks) if engine!='native' else True
        assert all(len(json.loads(b['bbox']))==4 and all(0<=v<=1 for v in json.loads(b['bbox'])) for b in blocks)
    save_json(path, result)
    record('parse', tid, f'{file["name"]} · {engine} {device}', result['status'],
           f'实际任务 {run["status"]}；{len(blocks)} 块；旧快照文字和 bbox 保持原样。'+ (' '+str(run.get('error')) if run.get('error') else ''),
           files=[file], results={'run_status': run['status'], 'error': run.get('error'), 'provenance': result['provenance'],
                                'old_snapshots_unchanged': True, 'blank_pages': result.get('blank_pages'), 'examples': result['examples']},
           counts=result['counts'], run_ids=[rid], duration_seconds=result['duration_seconds'], evidence=[path])
    record('snapshots', 'protected-' + tid, f'{engine} {device} · 旧快照保护', 'PASS',
           '逐个核对本次任务前的解析快照；原块 ID、文字、bbox 哈希全部不变。GPU 失败也未切换活动快照。' if result['status']!='PASS' else '新快照单独保存；旧块 ID、文字、bbox 哈希全部不变。',
           files=[file], results={'prior_hashes': old, 'after_hashes': {p: snapshot_hash(vid,p) for p in old}}, evidence=[path])
    print(f'{tid}: {result["status"]} {result["duration_seconds"]}s {len(blocks)} blocks', flush=True)
    return result


def followup():
    ingestion = json.loads((OUT/'ingestion.json').read_text())
    assert len(ingestion['documents']) == 39 and ingestion.get('finished')
    quota = store.rows('SELECT * FROM quota ORDER BY id')
    manifest = json.loads((OUT/'manifest.json').read_text())
    by_name = {d['file']['name']: d for d in ingestion['documents']}
    enhanced = []
    with httpx.Client(base_url=BASE, cookies={'rt_session': cookie()}, trust_env=False, timeout=120) as client:
        # The textbook regression creates a new v2 revision; old partial v1 stays intact.
        book = reparse(client, by_name['UnderstandingDeepLearning_02_09_26_C.pdf'], 'native', test_id='textbook-native-v2')
        enhanced.append(book)
        save_json(OUT/'enhanced.json', enhanced)
        if book['status']=='PASS':
            state = json.loads((OUT/'workflow.json').read_text())
            for step in state['steps']:
                if step['id']=='parse':
                    for run in step['runs']:
                        if run['id']=='native-'+book['version_id']:
                            run['resolved_by']='textbook-native-v2'
            save_json(OUT/'workflow.json', state)
        # Run full original scan with both OCR and structured parsing.
        for engine in ('paddleocr', 'mineru'):
            enhanced.append(reparse(client, by_name['1706.03762v1_img.pdf'], engine))
            save_json(OUT/'enhanced.json', enhanced)
        # Explicitly labelled one-page crop for the larger CPU VL model.
        source = ROOT/manifest['extracted_root']/'pdf/1706.03762v1_img.pdf'
        derived = ROOT/'evals/files'/manifest['id']/'derivatives'
        derived.mkdir(parents=True, exist_ok=True)
        reader = PdfReader(source)
        page = reader.pages[3]
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        page.cropbox.lower_left = (width*.07, height*.43)
        page.cropbox.upper_right = (width*.93, height*.72)
        writer = PdfWriter()
        writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        raw = buf.getvalue()
        cropped = derived/'scan-page4-attention-crop.pdf'
        cropped.write_bytes(raw)
        response = client.post('/api/v1/documents?index_dense=false', files={'files': (cropped.name, raw, 'application/pdf')})
        response.raise_for_status()
        uploaded = response.json()
        if uploaded['runs']:
            wait(client, uploaded['runs'][0]['id'], 90)
        entry = dict(version_id=uploaded['documents'][0]['id'],
                     file=dict(name=cropped.name, sha256=hashlib.sha256(raw).hexdigest(), page_count=1),
                     derivative_source=dict(source_sha256=by_name['1706.03762v1_img.pdf']['file']['sha256'],
                                            source_page_index=3, crop_normalized_xy_from_bottom=[.07,.43,.93,.72],
                                            derived=True, scope='仅第4物理页的裁剪区域；不代表全篇 VL 验收'))
        enhanced.append(reparse(client, entry, 'paddleocr_vl', test_id='scan-crop-paddleocr-vl-cpu'))
        save_json(OUT/'enhanced.json', enhanced)
        enhanced.append(reparse(client, entry, 'mineru', 'gpu', test_id='scan-crop-mineru-gpu'))
        save_json(OUT/'enhanced.json', enhanced)

        graph = client.post('/api/v1/graphs')
        graph.raise_for_status()
        graph = graph.json()
        assert len(graph['nodes']) >= 20 and graph['edges']
        for edge in graph['edges']:
            assert edge['block_id'] and edge['version_id'] and edge['ref_id']
            assert store.one('SELECT id FROM refs WHERE id=? AND block_id=?', (edge['ref_id'], edge['block_id']))
        save_json(OUT/'graph.json', graph)
        record('graph', 'corpus-real-references', '39 篇资料 · 全文参考文献引用图谱', 'PASS',
               '从本次解析的 PDF 参考文献构图；逐边核对真实 ref_id、源版本、块和页码。PageRank 仅代表当前集合。',
               files=[d['file'] for d in ingestion['documents']], counts={'nodes': len(graph['nodes']), 'reference_entries': len(graph['edges'])},
               evidence=[OUT/'graph.json'])

        watch = client.post('/api/v1/watch-queries', json={'query': 'Attention Is All You Need', 'enabled': False})
        watch.raise_for_status()
        wid = watch.json()['id']
        checked = client.post('/api/v1/watch-queries/'+wid+'/check')
        checked.raise_for_status()
        checked = checked.json()
        save_json(OUT/'discovery.json', checked)
        record('discovery', 'corpus-live-watch', '从资料主题进行实时公开来源检查', 'BLOCKED' if checked.get('errors') else 'PASS',
               '真实调用公开来源；保留来源错误和检查时间。测试追踪保持关闭，未用离线结果替代在线检索。',
               results=checked, evidence=[OUT/'discovery.json'])

        ledger = store.rows('SELECT model,count(*) calls,sum(input_tokens) input_tokens,sum(output_tokens) output_tokens FROM quota GROUP BY model')
        assert next(r['calls'] for r in ledger if 'hydrogen' in r['model']) == 4
        record('analysis', 'new-model-evaluation-budget', '本资料集新增核心问答与翻译质量评测', 'BLOCKED',
               'Hydrogen 原 4 次冒烟上限已用尽。此次未提交新问答或译文请求；旧真实调用不算本批新测试，批量模型测试也未额外执行。',
               results={'provider_calls_this_batch': 0, 'ledger': ledger, 'paid_fallback': False})

        # Use measured corpus inventory as CSV input, clearly separate from supplied PDFs.
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['document_index', 'pages', 'processed_pages'])
        for i, doc in enumerate(ingestion['documents'], 1):
            writer.writerow([i, doc['file']['page_count'], len(doc.get('pages', []))])
        csv_raw = buf.getvalue().encode()
        csv_path = ROOT/'evals/files'/manifest['id']/'corpus-page-counts.csv'
        csv_path.write_bytes(csv_raw)
        response = client.post('/api/v1/charts', files={'file': (csv_path.name, csv_raw, 'text/csv')},
                               data={'spec': json.dumps({'kind': 'bar', 'x': 'document_index', 'y': ['pages'], 'title': 'Corpus physical page counts', 'y_unit': 'pages'})})
        response.raise_for_status()
        chart = response.json()
        save_json(OUT/'csv-chart.json', chart)
        record('export', 'corpus-statistics-chart', '本次原始资料清单 → CSV → 实际统计与图表导出', 'PASS',
               'RAR 中没有 CSV；此 CSV 由本次 39 份 PDF 的实测页数生成，明确属于衍生输入。按受控模板生成图与可复现数据。',
               files=[{'name': csv_path.name, 'sha256': hashlib.sha256(csv_raw).hexdigest()}], results=chart,
               evidence=[OUT/'csv-chart.json'])

        # Actual malformed input, no-session and another-workspace checks.
        damaged = client.post('/api/v1/documents?index_dense=false', files={'files': ('broken.pdf', b'%PDF-1.7\ncorrupted', 'application/pdf')})
        vid = by_name['1706.03762v7.pdf']['version_id']
        with httpx.Client(base_url=BASE, trust_env=False) as stranger:
            unauth = stranger.get(f'/api/v1/documents/{vid}/file').status_code
        old_cookie = json.loads((ROOT/'data/smoke-session.json').read_text())['cookie']
        cross = httpx.get(BASE+f'/api/v1/documents/{vid}/file', cookies={'rt_session': old_cookie}, trust_env=False).status_code
        escapes = {p: client.get('/api/v1/admin/evidence-file', params={'path': p}).status_code for p in ('.env', '../.env', 'data/researchtrace.sqlite')}
        assert damaged.status_code==422 and unauth==401 and cross==404 and all(v==404 for v in escapes.values())
        safety = dict(status='PASS', damaged_pdf_http=damaged.status_code, unauth_file_http=unauth, cross_workspace_http=cross,
                      evidence_path_escapes=escapes, quota_unchanged=quota==store.rows('SELECT * FROM quota ORDER BY id'), ledger=ledger)
        assert safety['quota_unchanged']
        save_json(OUT/'safety-and-quota.json', safety)
        record('recovery', 'dataset-security-quota', '实际异常文件、权限边界与账本增量', 'PASS',
               '损坏 PDF 422，未登录文件 401，跨工作区文件 404，证据路径逃逸 404；完整 quota 行保持不变。',
               results=safety, evidence=[OUT/'safety-and-quota.json'])
    print('Downstream dataset checks complete', flush=True)


if __name__ == '__main__':
    followup()
