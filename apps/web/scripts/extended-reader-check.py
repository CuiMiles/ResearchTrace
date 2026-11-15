"""Read-only D02/D03/D05 audit; fixtures are isolated and explicitly labelled.
No HTTP mutation, parser submission, provider request, login POST, or new translation.
"""
import copy
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright
from browser_runtime import launch_chromium

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'apps/web/validation'
OUT.mkdir(exist_ok=True)
BASE = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:18980').rstrip('/')
STAMP = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
PREFIX = f'reader-extra-{STAMP}'
REPORT = {'base_url': BASE, 'created_utc': STAMP, 'cases': [], 'blocked_mutations': [],
          'blocked_external_requests': [], 'browser_errors': [], 'live_reads': [],
          'provider_requests': 0, 'parser_submissions': 0, 'fixtures_are_live_results': False}
COOKIE = json.loads((ROOT / 'data/smoke-session.json').read_text())['cookie']
if isinstance(COOKIE, dict):
    COOKIE = COOKIE.get('rt_session') or COOKIE.get('value')
if COOKIE.startswith('rt_session='):
    COOKIE = COOKIE.split('=', 1)[1].split(';', 1)[0]


def assertion(condition, message):
    if not condition:
        raise AssertionError(message)


def screenshot(page, label):
    path = OUT / f'{PREFIX}-{label}.png'
    page.screenshot(path=str(path), full_page=True)
    return str(path.relative_to(ROOT))


def get(context, path):
    response = context.request.get(BASE + '/api/v1' + path)
    REPORT['live_reads'].append({'path': path, 'status': response.status})
    if not response.ok:
        raise RuntimeError(f'GET {path} returned {response.status}')
    return response.json()


def metadata(block):
    value = block.get('metadata') or {}
    return json.loads(value) if isinstance(value, str) else value


def sha_text(value):
    return hashlib.sha256(value.encode()).hexdigest()


def context_for(browser, version=None, fixture=None, authenticated=True):
    context = browser.new_context(viewport={'width': 1600, 'height': 1000})
    if authenticated:
        context.add_cookies([{'name': 'rt_session', 'value': COOKIE, 'url': BASE,
                             'httpOnly': True, 'sameSite': 'Strict'}])
    if version:
        context.add_init_script('localStorage.setItem("rt-version", ' + json.dumps(version['id']) + ')')

    def guard(route):
        request = route.request
        if not request.url.startswith(BASE + '/'):
            REPORT['blocked_external_requests'].append(urlsplit(request.url).netloc)
            route.abort()
        elif fixture and fixture(route):
            return
        elif request.method not in ('GET', 'HEAD', 'OPTIONS'):
            REPORT['blocked_mutations'].append({'method': request.method, 'path': urlsplit(request.url).path})
            route.abort()
        else:
            route.continue_()
    context.route('**/*', guard)
    page = context.new_page()
    page.set_default_timeout(12000)
    page.on('pageerror', lambda e: REPORT['browser_errors'].append(str(e)))
    return context, page


def open_reader(page, parse_id=None):
    page.goto(BASE, wait_until='domcontentloaded')
    page.get_by_role('button', name='阅读与问答', exact=True).click()
    selector = page.get_by_label('选择解析快照', exact=True)
    selector.locator('option').nth(1).wait_for(state='attached')
    if parse_id:
        selector.select_option(parse_id)
    return selector


def parallel_page(page, index, blocks):
    page.get_by_role('button', name='中英对照', exact=True).click()
    page.get_by_label('页码', exact=True).fill(str(index + 1))
    expected = [b['id'] for b in blocks if b['page_index'] == index]
    assertion(expected, 'No stored blocks on selected page')
    page.locator(f'.parallel-column:not(.translated) [data-block="{expected[0]}"]').wait_for()
    actual = page.locator('.parallel-column:not(.translated) [data-block]').evaluate_all(
        '(els) => els.map(el => el.dataset.block)')
    assertion(actual == expected, 'Source page block order differs from live snapshot')


def run_case(name, source, fn):
    case = {'id': name, 'source': source}
    REPORT['cases'].append(case)
    try:
        fn(case)
    except AssertionError as exc:
        case.update(status='FAIL', error=str(exc))
    except Exception as exc:
        case.update(status='BLOCKED', error=str(exc))
    else:
        case['status'] = 'PASS'
    print(json.dumps({'case': name, 'status': case['status'], 'error': case.get('error')}, ensure_ascii=False), flush=True)


with sync_playwright() as playwright:
    browser = launch_chromium(playwright)
    REPORT['browser_version'] = browser.version
    data_context, _ = context_for(browser)
    documents = get(data_context, '/documents')
    snapshots = {v['id']: get(data_context, f"/documents/{v['id']}/parses") for v in documents}

    def d02(case):
        chosen = None
        for version in documents:
            if 'Attention Is All You Need' not in version['title']:
                continue
            snap = next(s for s in snapshots[version['id']] if s['active'])
            query = '?parse_id=' + snap['id']
            blocks = get(data_context, f"/documents/{version['id']}/blocks{query}&limit=500")
            refs = get(data_context, f"/documents/{version['id']}/references{query}")
            for block in blocks:
                if block['type'] != 'paragraph':
                    continue
                for marker in metadata(block).get('citation_markers', [])[:8]:
                    numbers = [x.strip() for x in re.split(r'[,;–-]', marker.replace('[', '').replace(']', ''))]
                    ref = next((r for r in refs if str(r.get('marker', '')).strip('[] ') in numbers
                                and r['page_index'] != block['page_index']), None)
                    if ref:
                        chosen = (version, snap, blocks, block, marker, ref)
                        break
                if chosen:
                    break
            if chosen:
                break
        assertion(chosen is not None, 'No real source paragraph marker matched an off-page bibliography entry')
        version, snap, blocks, block, marker, ref = chosen
        case.update(version_id=version['id'], document_sha256=version['sha256'], parse_id=snap['id'],
                    source_block_id=block['id'], source_page=block['page_index'] + 1,
                    source_text_sha256=sha_text(block['text']), marker=marker,
                    bibliography_block_id=ref['block_id'], bibliography_page=ref['page_index'] + 1,
                    bibliography_text_sha256=sha_text(ref['text']))
        context, page = context_for(browser, version)
        try:
            selector = open_reader(page, snap['id'])
            parallel_page(page, block['page_index'], blocks)
            source = page.locator(f'.parallel-column:not(.translated) [data-block="{block["id"]}"]')
            marker_text = '[' + marker.replace('[', '').replace(']', '') + ']'
            source.get_by_role('button', name=marker_text, exact=True).click()
            bibliography = page.locator(f'.parallel-column:not(.translated) [data-block="{ref["block_id"]}"].focused')
            bibliography.wait_for()
            assertion(page.get_by_label('页码', exact=True).input_value() == str(ref['page_index'] + 1), 'Bibliography page differs')
            assertion(page.locator('.reference-row').filter(has_text=ref['text']).count() == 1, 'Exact bibliography entry absent')
            assertion(selector.input_value() == snap['id'], 'Citation changed parse identity')
            case['bibliography_screenshot'] = screenshot(page, 'd02-bibliography')
            page.get_by_role('button', name=f'返回正文第 {block["page_index"] + 1} 页', exact=True).click()
            source = page.locator(f'.parallel-column:not(.translated) [data-block="{block["id"]}"].focused')
            source.wait_for()
            assertion(page.get_by_label('页码', exact=True).input_value() == str(block['page_index'] + 1), 'Return page differs')
            assertion(source.locator('p').inner_text() == block['text'], 'Returned paragraph text differs')
            assertion(selector.input_value() == snap['id'], 'Return changed parse identity')
            case['return_screenshot'] = screenshot(page, 'd02-return')
            case['checks'] = ['real marker clicked', 'exact bibliography block/page', 'same snapshot retained',
                              'return to exact source block/page/text']
        finally:
            if not any(key.endswith('screenshot') for key in case):
                try:
                    case['final_screenshot'] = screenshot(page, case['id'] + '-final')
                except Exception:
                    pass
            context.close()

    run_case('D02-citation-bibliography-return', 'live stored document and reference records; no fixtures', d02)

    bitnet = next(v for v in documents if '1.58 Bits' in v['title'])
    translations = get(data_context, '/translations/' + bitnet['id'])
    translation_map = {t['block_id']: t for t in translations}
    candidates = []
    for snap in snapshots[bitnet['id']]:
        blocks = get(data_context, f"/documents/{bitnet['id']}/blocks?parse_id={snap['id']}&limit=500")
        candidates.append((sum(b['id'] in translation_map for b in blocks), snap, blocks))
    _, legacy, legacy_blocks = max(candidates, key=lambda candidate: candidate[0])

    def d03(case):
        source_ids = {b['id'] for b in legacy_blocks}
        aligned = [t for t in translations if t['block_id'] in source_ids]
        untranslated = [b for b in legacy_blocks if b['id'] not in translation_map]
        case.update(version_id=bitnet['id'], document_sha256=bitnet['sha256'], parse_id=legacy['id'],
                    snapshot_active=bool(legacy['active']), stored_translations=len(translations),
                    aligned_translation_count=len(aligned), source_blocks=len(legacy_blocks),
                    untranslated=[{'id': b['id'], 'type': b['type'], 'text': b['text']} for b in untranslated])
        assertion(len(aligned) == 120, 'Expected the actual 120 stored translations to match this snapshot')
        assertion(all(b['type'] == 'footer' and b['text'].strip().isdigit() for b in untranslated),
                  'Untranslated blocks include non-footer content')
        context, page = context_for(browser, bitnet)
        try:
            selector = open_reader(page, legacy['id'])
            page.get_by_role('button', name='中英对照', exact=True).click()
            page.get_by_text('中文 · 120 段已译', exact=True).wait_for()
            case['pages'] = []
            seen = set()
            for index in range(bitnet['page_count']):
                parallel_page(page, index, legacy_blocks)
                right = page.locator('.parallel-column.translated [data-block]').evaluate_all(
                    '(els) => els.map(el => ({id: el.dataset.block, text: el.querySelector("p").textContent, model: el.querySelector("small").textContent}))')
                verified = []
                for item in right:
                    if item['id'] not in translation_map:
                        continue
                    expected = translation_map[item['id']]
                    assertion(item['text'] == expected['text'], f'Translation text mismatch: {item["id"]}')
                    assertion(item['model'] == expected['model'], f'Translation provenance mismatch: {item["id"]}')
                    verified.append(item['id'])
                    seen.add(item['id'])
                case['pages'].append({'physical_page': index + 1, 'verified_translation_ids': verified})
            assertion(len(seen) == 120, 'Not all 120 translations verified in rendered DOM')
            parallel_page(page, 0, legacy_blocks)
            case['scroll_checks'] = []
            metrics = '''(side) => {
              const columns = document.querySelectorAll('.parallel-column');
              const from = columns[side], to = columns[1-side];
              const top = from.getBoundingClientRect().top;
              const visible = [...from.querySelectorAll('[data-block]')].find(el => el.getBoundingClientRect().bottom > top+12);
              const matching = [...to.querySelectorAll('[data-block]')].find(el => el.dataset.block === visible?.dataset.block);
              return {anchor: visible?.dataset.block, from_scroll: from.scrollTop, to_scroll: to.scrollTop,
                from_max: from.scrollHeight-from.clientHeight, to_max: to.scrollHeight-to.clientHeight,
                source_offset: visible?.getBoundingClientRect().top-top,
                target_offset: matching?.getBoundingClientRect().top-to.getBoundingClientRect().top};
            }'''
            for side, delta, label in [(0, 540, 'source-down'), (1, 260, 'translation-down'),
                                       (0, -210, 'source-up'), (1, -180, 'translation-up')]:
                page.wait_for_timeout(150)
                before = page.evaluate(metrics, side)
                column = page.locator('.parallel-column').nth(side)
                column.hover(position={'x': 60, 'y': 150})
                page.mouse.wheel(0, delta)
                page.wait_for_timeout(450)
                after = page.evaluate(metrics, side)
                offset_error = abs(after['source_offset'] - after['target_offset'])
                result = {'direction': label, 'before': before, 'after': after, 'offset_error_px': offset_error}
                case['scroll_checks'].append(result)
                assertion(abs(after['from_scroll'] - before['from_scroll']) > 10, f'Origin did not scroll: {label}')
                assertion(abs(after['to_scroll'] - before['to_scroll']) > 10, f'Corresponding column did not scroll: {label}')
                assertion(offset_error <= 3, f'Block alignment drift {offset_error:.1f}px: {label}')
            assertion(selector.input_value() == legacy['id'], 'Stored translation reading changed snapshot')
            if not legacy['active']:
                assertion(page.get_by_role('button', name='翻译本页', exact=True).is_disabled(), 'Historical translation action enabled')
                assertion(page.get_by_role('button', name='发送问题', exact=True).is_disabled(), 'Historical model action enabled')
            case['screenshot'] = screenshot(page, 'd03-aligned-scroll')
            case['verified_dom_translations'] = len(seen)
            case['translation_texts_sha256'] = sha_text(json.dumps([(t['block_id'], t['text']) for t in aligned], ensure_ascii=False))
        finally:
            if not any(key.endswith('screenshot') for key in case):
                try:
                    case['final_screenshot'] = screenshot(page, case['id'] + '-final')
                except Exception:
                    pass
            context.close()

    run_case('D03-stored-translation-and-scroll', 'live stored BitNet translations and legacy snapshot; no fixtures', d03)

    def d05_loading(case):
        pending = []
        def fixture(route):
            if urlsplit(route.request.url).path == f"/api/v1/documents/{bitnet['id']}/file":
                pending.append(route)
                return True
            return False
        context, page = context_for(browser, bitnet, fixture)
        try:
            open_reader(page)
            page.get_by_text('正在载入原文', exact=True).wait_for()
            for _ in range(50):
                if pending:
                    break
                page.wait_for_timeout(50)
            assertion(pending, 'No PDF request held by loading fixture')
            case['screenshot'] = screenshot(page, 'd05-loading-fixture')
            case['fixture'] = {'method': 'GET', 'path': f"/documents/{bitnet['id']}/file", 'behavior': 'hold then continue original request'}
            for route in pending:
                route.continue_()
            page.locator('.pdf-loading').wait_for(state='hidden')
            assertion(page.locator('.pdf-scroller .error-box').count() == 0, 'PDF failed after releasing delayed read')
            case['recovered_screenshot'] = screenshot(page, 'd05-loading-recovered')
        finally:
            if not any(key.endswith('screenshot') for key in case):
                try:
                    case['final_screenshot'] = screenshot(page, case['id'] + '-final')
                except Exception:
                    pass
            context.close()

    run_case('D05-loading', 'isolated browser route fixture delays real PDF GET; no server state changed', d05_loading)

    def d05_partial(case):
        partial = copy.deepcopy(bitnet)
        partial.update(parsed_pages=1, status='parsing')
        fixture_snapshots = copy.deepcopy(snapshots[bitnet['id']])
        active = next(s for s in fixture_snapshots if s['active'])
        active.update(parsed_pages=1, status='partial')
        hits = []
        def fixture(route):
            path = urlsplit(route.request.url).path
            value = None
            status = 200
            if path == '/api/v1/documents':
                value = [partial if v['id'] == bitnet['id'] else v for v in documents]
            elif path == f"/api/v1/documents/{bitnet['id']}/parses":
                value = fixture_snapshots
            elif path == f"/api/v1/documents/{bitnet['id']}/pages/1":
                status, value = 404, {'detail': 'reader-extra isolated fixture: page not parsed yet'}
            if value is None:
                return False
            hits.append({'path': path, 'status': status})
            route.fulfill(status=status, json=value)
            return True
        context, page = context_for(browser, bitnet, fixture)
        try:
            open_reader(page)
            page.get_by_text('部分完成 · ' + active.get('device', 'cpu'), exact=True).wait_for()
            page.get_by_role('button', name='中英对照', exact=True).click()
            page.get_by_label('页码', exact=True).fill('2')
            page.get_by_text('这一页的文字还没有准备好', exact=True).wait_for()
            assertion(page.get_by_role('button', name='翻译本页', exact=True).is_disabled(), 'Unparsed page translation enabled')
            case['screenshot'] = screenshot(page, 'd05-partial-fixture')
            case['fixture_hits'] = hits
        finally:
            if not any(key.endswith('screenshot') for key in case):
                try:
                    case['final_screenshot'] = screenshot(page, case['id'] + '-final')
                except Exception:
                    pass
            context.close()

    run_case('D05-partial', 'isolated browser GET fixtures for progress and an unparsed page; not a live parse', d05_partial)

    def d05_error(case):
        hits = []
        def fixture(route):
            path = urlsplit(route.request.url).path
            status, detail = None, None
            if path == f"/api/v1/documents/{bitnet['id']}/parses":
                status, detail = 503, 'reader-extra isolated fixture: snapshot service unavailable'
            elif path == f"/api/v1/documents/{bitnet['id']}/pages/0":
                status, detail = 500, 'reader-extra isolated fixture: page read failed'
            if status is None:
                return False
            hits.append({'path': path, 'status': status})
            route.fulfill(status=status, json={'detail': detail})
            return True
        context, page = context_for(browser, bitnet, fixture)
        try:
            page.goto(BASE, wait_until='domcontentloaded')
            page.get_by_role('button', name='阅读与问答', exact=True).click()
            page.get_by_text('reader-extra isolated fixture: page read failed', exact=True).wait_for()
            page.get_by_text(re.compile('解析快照暂不可用：reader-extra isolated fixture: snapshot service unavailable')).wait_for()
            assertion(page.get_by_role('button', name='创建解析快照', exact=True).is_disabled(), 'Snapshot submission enabled on fetch error')
            case['screenshot'] = screenshot(page, 'd05-error-fixture')
            case['fixture_hits'] = hits
        finally:
            if not any(key.endswith('screenshot') for key in case):
                try:
                    case['final_screenshot'] = screenshot(page, case['id'] + '-final')
                except Exception:
                    pass
            context.close()

    run_case('D05-error', 'isolated browser GET 500/503 fixtures; not actual service failure', d05_error)

    def d05_noauth(case):
        context, page = context_for(browser, authenticated=False)
        responses = []
        page.on('response', lambda response: responses.append(response.status)
                if urlsplit(response.url).path == '/api/v1/auth/session' else None)
        try:
            page.goto(BASE, wait_until='domcontentloaded')
            page.get_by_role('heading', name='打开研究工作区', exact=True).wait_for()
            assertion(page.get_by_label('访问码', exact=True).is_visible(), 'Login input absent')
            assertion(401 in responses, 'Expected real anonymous session 401')
            assertion(page.locator('.reader-workspace').count() == 0, 'Protected Reader visible without auth')
            case['session_statuses'] = responses
            case['screenshot'] = screenshot(page, 'd05-noauth-live')
        finally:
            if not any(key.endswith('screenshot') for key in case):
                try:
                    case['final_screenshot'] = screenshot(page, case['id'] + '-final')
                except Exception:
                    pass
            context.close()

    run_case('D05-noauth', 'real anonymous browser context, no cookie and no login POST', d05_noauth)

    def d05_empty(case):
        hits = []
        def fixture(route):
            path = urlsplit(route.request.url).path
            if path in ('/api/v1/documents', '/api/v1/runs'):
                hits.append({'path': path, 'status': 200})
                route.fulfill(status=200, json=[])
                return True
            return False
        context, page = context_for(browser, None, fixture)
        try:
            page.goto(BASE, wait_until='domcontentloaded')
            page.get_by_text('把第一篇论文放进来', exact=True).wait_for()
            page.get_by_role('button', name='阅读与问答', exact=True).click()
            page.get_by_text('打开一篇论文，开始验证你的问题', exact=True).wait_for()
            case['screenshot'] = screenshot(page, 'd05-empty-fixture')
            case['fixture_hits'] = hits
        finally:
            context.close()

    run_case('D05-empty', 'isolated browser empty library and reader GET [] fixtures', d05_empty)

    def d05_429(case):
        hits = []
        def fixture(route):
            path = urlsplit(route.request.url).path
            if route.request.method == 'POST' and path == f"/api/v1/documents/{bitnet['id']}/parses":
                hits.append({'method': 'POST', 'path': path, 'status': 429})
                route.fulfill(status=429, json={'detail': 'reader-extra isolated fixture: 429 rate limited'})
                return True
            return False
        context, page = context_for(browser, bitnet, fixture)
        try:
            open_reader(page)
            page.get_by_role('button', name='创建解析快照', exact=True).click()
            page.get_by_role('alert').filter(has_text='reader-extra isolated fixture: 429 rate limited').wait_for()
            case['screenshot'] = screenshot(page, 'd05-429-fixture')
            case['fixture_hits'] = hits
        finally:
            context.close()

    run_case('D05-429', 'isolated browser POST 429 fixture; never sent to server', d05_429)

    def d05_parse_failed(case):
        failed_doc = copy.deepcopy(bitnet)
        failed_doc.update(status='failed', parsed_pages=0)
        failed_snaps = copy.deepcopy(snapshots[bitnet['id']])
        active = next(s for s in failed_snaps if s['active'])
        active.update(status='failed', parsed_pages=0, error='reader-extra isolated fixture: mineru unavailable; broker HTTP 503')
        hits = []
        def fixture(route):
            path = urlsplit(route.request.url).path
            if path == '/api/v1/documents':
                hits.append({'path': path, 'status': 200})
                route.fulfill(status=200, json=[failed_doc if v['id'] == bitnet['id'] else v for v in documents])
                return True
            if path == f"/api/v1/documents/{bitnet['id']}/parses":
                hits.append({'path': path, 'status': 200})
                route.fulfill(status=200, json=failed_snaps)
                return True
            return False
        context, page = context_for(browser, bitnet, fixture)
        try:
            open_reader(page)
            page.get_by_role('alert').filter(has_text='reader-extra isolated fixture: mineru unavailable').wait_for()
            page.get_by_text('失败 · ' + active.get('device', 'cpu'), exact=True).wait_for()
            case['screenshot'] = screenshot(page, 'd05-parse-failed-fixture')
            case['fixture_hits'] = hits
        finally:
            context.close()

    run_case('D05-parse-failed', 'isolated browser GET failed snapshot fixture', d05_parse_failed)
    data_context.close()
    browser.close()

REPORT['status'] = ('FAIL' if any(c['status'] == 'FAIL' for c in REPORT['cases'])
                    or REPORT['blocked_mutations'] or REPORT['browser_errors']
                    else 'BLOCKED' if any(c['status'] == 'BLOCKED' for c in REPORT['cases']) else 'PASS')
path = OUT / f'{PREFIX}.json'
path.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2))
print(json.dumps({'status': REPORT['status'], 'report': str(path.relative_to(ROOT)),
                  'blocked_mutations': len(REPORT['blocked_mutations']), 'browser_errors': len(REPORT['browser_errors'])}))
sys.exit(0 if REPORT['status'] == 'PASS' else 1)
