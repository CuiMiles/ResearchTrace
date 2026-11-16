"""Browser fixture only. Intercepts all API traffic, never contacts a provider.

Start isolated Vite: npm run dev -- --port 19049 --strictPort
RT_WRITING_FIXTURE_URL=http://127.0.0.1:19049 python tests/e2e/writing_workflows_fixture.py
"""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.api.writing_workflows import diagram_sources

BASE = os.getenv('RT_WRITING_FIXTURE_URL', 'http://127.0.0.1:19049')
OUT = Path(os.getenv('RT_WRITING_FIXTURE_OUT', '/tmp/rt-writing-browser-evidence'))
OUT.mkdir(parents=True, exist_ok=True)
versions = [{'id': 'v1', 'work_id': 'w1', 'title': 'Fixture attention paper', 'filename': 'fixture.pdf',
             'label': 'fixture v1', 'status': 'ready', 'page_count': 5, 'parsed_pages': 5, 'dense_pages': 0,
             'metadata': {}, 'sha256': 'fixture', 'created': 1}]
requests, errors, checks = [], [], []
graph_spec = {'nodes': [{'id': 'Input', 'label': '输入'}, {'id': 'Encoder', 'label': 'Attention编码器'}],
              'edges': [{'source': 'Input', 'target': 'Encoder', 'label': '特征'}]}
sources = diagram_sources(graph_spec)

def intercept(route):
    request = route.request
    path = urlsplit(request.url).path.removeprefix('/api/v1')
    if path.endswith('/events'):
        return route.fulfill(content_type='text/event-stream', body='event: done\ndata: {}\n\n')
    if request.method == 'POST':
        body = request.post_data_json
        requests.append({'path': path, 'body': body})
    if path == '/auth/session': data = {'workspace': 'fixture', 'role': 'reviewer'}
    elif path == '/capabilities': data = {'model_configured': True}
    elif path == '/documents': data = versions
    elif path == '/graphs': data = {'nodes': [{'id': 'w1', 'title': 'Fixture attention paper', 'rank': 1, 'indegree': 0, 'outdegree': 0, 'degree': 0, 'betweenness': 0, 'role_label': '未形成引用连接', 'role_reason': '当前集合没有真实引用边'}], 'edges': [], 'scope': 'Fixture local scope', 'role_rules': {'scope': '仅局部集合'}}
    elif path.startswith('/writing/') or path in ['/text/translations', '/translations']: data = {'id': 'fixture-diagram' if 'diagrams' in path else 'fixture-run'}
    elif path.startswith('/runs/'):
        is_diagram = 'diagram' in path
        data = {'id': path.split('/')[2], 'kind': 'writing', 'status': 'completed', 'payload': {}, 'created': 1, 'updated': 1, 'steps': [], 'error': None,
                'result': {'answer': 'Fixture result, not a live answer', **({'sources': sources, 'graph_spec': graph_spec} if is_diagram else {})}}
    elif path in ['/artifacts', '/batches', '/runs']: data = []
    else: data = {}
    return route.fulfill(content_type='application/json', body=json.dumps(data, ensure_ascii=False))

def check(name, condition):
    checks.append({'name': name, 'status': 'PASS' if condition else 'FAIL', 'scope': 'browser_fixture'})
    if not condition: raise AssertionError(name)

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.getenv('RT_BROWSER_EXECUTABLE', '/home/cui/projects/competition/传智杯2026/apps/web/.browser-runtime/chrome-linux/chrome'), headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    page.route('**/api/v1/**', intercept)
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        page.goto(BASE + '/studio')
        page.get_by_role('button', name='idea 论文框架', exact=True).click()
        form = page.get_by_role('region', name='idea论文框架工作流') if page.get_by_role('region', name='idea论文框架工作流').count() else page.locator('[aria-label="idea论文框架工作流"]')
        form.get_by_role('textbox', name='研究 idea').fill('attention with robust evidence')
        form.get_by_role('textbox', name='学术检索词').fill('evidence attention')
        form.get_by_role('button', name='选择前20篇').click()
        form.get_by_role('button', name='检索并生成论文框架').click()
        page.get_by_text('Fixture result, not a live answer', exact=True).wait_for()
        check('outline_dedicated_route', requests[-1]['path'] == '/writing/outlines')
        check('outline_scope_and_query', requests[-1]['body']['version_ids'] == ['v1'] and requests[-1]['body']['search_query'] == 'evidence attention')
        page.get_by_role('button', name='领域综述', exact=True).click()
        form = page.locator('[aria-label="领域综述工作流"]')
        form.get_by_role('textbox', name='综述主题与范围').fill('Compare evidence based architectures')
        form.get_by_role('button', name='选择前20篇').click()
        form.get_by_role('button', name='生成领域综述', exact=True).click()
        page.get_by_text('Fixture result, not a live answer', exact=True).wait_for()
        check('survey_dedicated_route', requests[-1]['path'] == '/writing/surveys')
        for width in [1280, 1440, 1920, 390]:
            page.set_viewport_size({'width': width, 'height': 900})
            check('survey_no_overflow_' + str(width), page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            page.screenshot(path=OUT / f'survey-{width}.png', full_page=True)
        page.set_viewport_size({'width': 1440, 'height': 900})
        page.get_by_role('button', name='中英翻译', exact=True).click()
        form = page.locator('[aria-label="写作中英翻译"]')
        form.get_by_role('textbox', name='粘贴摘要或论文段落').fill('我们研究可核验的科研助手。')
        form.get_by_role('button', name='翻译文本并保存').click()
        page.get_by_text('Fixture result, not a live answer', exact=True).wait_for()
        check('text_translation_contract', requests[-1]['path'] == '/text/translations' and requests[-1]['body']['target_language'] == 'en')
        form.locator('summary').click()
        form.get_by_role('combobox', name='已解析 PDF').select_option('v1')
        check('whole_translation_requires_confirm', form.get_by_role('button', name='开始全文翻译').is_disabled())
        form.get_by_role('checkbox', name='确认翻译所选整篇文档').check()
        form.get_by_role('button', name='开始全文翻译').click()
        page.wait_for_timeout(100)
        check('whole_translation_reuses_contract', requests[-1]['path'] == '/translations' and requests[-1]['body']['version_id'] == 'v1')
        page.get_by_role('button', name='结构图', exact=True).click()
        form = page.locator('[aria-label="结构图生成工作流"]')
        form.get_by_role('textbox', name='架构设想').fill('Input data flows into attention encoder')
        form.get_by_role('button', name='生成结构图与四种源码').click()
        form.get_by_role('button', name='Graphviz DOT', exact=True).wait_for()
        check('diagram_dedicated_route', requests[-1]['path'] == '/writing/diagrams')
        form.get_by_role('button', name='Graphviz DOT', exact=True).click()
        form.get_by_role('button', name='更新 DOT 预览', exact=True).click()
        form.locator('.diagram-preview svg').wait_for(timeout=40000)
        check('real_graphviz_wasm_svg', form.locator('.diagram-preview svg').count() == 1)
        check('dot_contains_actual_label', 'Attention编码器' in form.locator('.diagram-preview').inner_text())
        for lang in ['TikZ', 'Matplotlib']:
            form.get_by_role('button', name=lang, exact=True).click()
            check('editable_' + lang, 'Attention编码器' in form.get_by_role('textbox', name=lang + ' 源码').input_value())
        form.get_by_role('button', name='Graphviz DOT', exact=True).click()
        form.get_by_role('textbox', name='Graphviz DOT 源码').fill('digraph { a [image="https://evil.invalid/x.svg"]; }')
        form.get_by_role('button', name='更新 DOT 预览', exact=True).click()
        check('external_dot_resource_blocked', form.get_by_text('DOT 超过大小限制或包含外部资源、HTML、链接属性。', exact=True).is_visible())
        page.goto(BASE + '/insights')
        page.get_by_text('未形成引用连接', exact=True).wait_for()
        check('local_role_shown', page.get_by_text('当前集合没有真实引用边', exact=True).is_visible())
        page.get_by_text('局部角色划分规则', exact=True).click()
        check('role_rules_visible', page.get_by_text('仅局部集合', exact=False).is_visible())
        page.get_by_role('button', name='生成领域综述', exact=True).click()
        check('graph_survey_form', page.locator('[aria-label="领域综述工作流"]').is_visible())
        check('no_page_errors', errors == [])
    finally:
        (OUT / 'report.json').write_text(json.dumps({'scope': 'explicit browser fixtures, actual local WASM renderer', 'checks': checks, 'page_errors': errors, 'requests': requests, 'provider_calls': 0}, ensure_ascii=False, indent=2))
        browser.close()
print(json.dumps({'checks': len(checks), 'failed': [c for c in checks if c['status'] != 'PASS'], 'page_errors': errors, 'out': str(OUT)}, ensure_ascii=False))
