"""Record the v3 walkthrough on the public site with the reviewer account (CDP screencast).
Run: film3.py [scene ids...]   Each successful scene is saved to v3/scenes/<id>/ with frame times."""
import base64, json, os, shutil, sys, time
from playwright.sync_api import sync_playwright

ROOT = '/home/dev/projects/ResearchTrace'
SP = os.environ.get('RT_VIDEO_WORK', '/tmp/rt-video')
F = f'{SP}/v3'; OUT = f'{F}/rec'
B = 'https://researchtrace.sluna.xyz'
V7 = '766a29679f72469b8bd763b365ca918b'; SCAN = 'da72ec99236c42f6ade08eb3b4ac687c'
CODE = json.load(open(f'{ROOT}/data-migrated/completion-deployment/reviewer-full-ready-20261117.json'))['access_code']
UPLOAD = f'{F}/paper-upload.pdf'
if not os.path.exists(UPLOAD): shutil.copy(f'{ROOT}/evals/pdfs/core/1706.03762v1.pdf', UPLOAD)
CSV = f'{F}/检索评测.csv'
if not os.path.exists(CSV): shutil.copy(f'{ROOT}/scripts/video/retrieval_eval.csv', CSV)
QUESTION = 'Transformer base 模型是怎么训练的？优化器参数、warmup 步数和正则化分别是多少？'
TESTS = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
args = [a for a in sys.argv[1:] if not a.isdigit()]
TL = json.load(open(f'{F}/timeline.json')); SC = {s['id']: s for s in TL['scenes']}; only = set(args)
shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)

CURSOR = r"""(()=>{const boot=()=>{if(document.getElementById('rt-cur')||!document.documentElement)return;const c=document.createElement('div');c.id='rt-cur';c.popover='manual';c.style.cssText='position:fixed;left:0;top:0;right:auto;bottom:auto;width:30px;height:30px;margin:0;padding:0;border:0;background:transparent;pointer-events:none;overflow:visible;transform:translate(-80px,-80px)';c.innerHTML='<svg width="30" height="30" viewBox="0 0 24 24"><path d="M4 2l15 11.5-6.6.9 3.7 7.1-3 1.5-3.6-7.2L5 20z" fill="#fff" stroke="#0b0c0e" stroke-width="1.5" stroke-linejoin="round"/></svg>';document.documentElement.appendChild(c);const up=()=>{try{c.hidePopover()}catch(e){}try{c.showPopover()}catch(e){}};up();let m=false;addEventListener('mousemove',e=>{c.style.transform=`translate(${e.clientX-4}px,${e.clientY-2}px)`},true);addEventListener('mousedown',()=>{c.firstChild.style.transform='scale(.82)'},true);addEventListener('mouseup',()=>{c.firstChild.style.transform=''},true);setInterval(()=>{const d=!!document.querySelector('dialog[open],.drawer-backdrop');if(d!==m){m=d;up()}},100)};if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot()})()"""

CSS = """*{box-sizing:border-box;margin:0}html,body{width:1920px;height:1080px;overflow:hidden;background:#0b0c0e;color:#f6f6f2;font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif}
.w{position:absolute;inset:0;padding:96px 130px 200px;display:flex;flex-direction:column;gap:38px}.eye{color:#c9f23a;font-size:26px;font-weight:600;letter-spacing:.14em}h1{font-size:76px;line-height:1.14;font-weight:700}
.r{opacity:0;transform:translateY(22px);transition:opacity .55s ease,transform .55s ease}.on{opacity:1;transform:none}.row{display:flex;gap:26px}.c{flex:1;background:#15171b;border:1px solid #2b2e34;border-radius:18px;padding:30px 34px}.c b{display:block;font-size:34px;font-weight:700}.c span{display:block;margin-top:12px;color:#a6a9b0;font-size:25px}.n{font-size:72px;font-weight:700;color:#c9f23a;line-height:1.05}.chips{display:flex;flex-wrap:wrap;gap:16px}.chip{padding:12px 26px;border-radius:999px;border:1px solid #3a3e45;font-size:27px;color:#e7e7e2}.chip.l{background:#c9f23a;color:#0b0c0e;border-color:#c9f23a;font-weight:600}
.bar{display:grid;grid-template-columns:330px 1fr 150px;gap:24px;align-items:center;font-size:29px;margin:12px 0}.t{height:30px;background:#1c1f24;border-radius:7px;overflow:hidden}.t i{display:block;height:100%;width:0;background:#6d7178;border-radius:7px;transition:width 1.3s cubic-bezier(.2,.7,.2,1)}.t i.h{background:#c9f23a}.on .t i{width:var(--v)}.bar em{font-style:normal;font-weight:700;text-align:right}.mark{width:96px;height:96px;border-radius:22px;background:#c9f23a;display:grid;place-items:center;color:#0b0c0e;font-size:50px;font-weight:800}
.ar{align-self:center;color:#c9f23a;font-size:34px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:22px}.mod{background:#15171b;border:1px solid #2b2e34;border-radius:18px;padding:28px 32px}.mod b{font-size:36px;display:block}.mod span{display:block;margin-top:10px;color:#a6a9b0;font-size:25px}
.chain{display:flex;align-items:center;gap:16px;font-size:30px}.chain .k2{padding:16px 28px;border-radius:14px;background:#c9f23a;color:#0b0c0e;font-weight:700}.chain .k1{padding:16px 28px;border-radius:14px;border:1px solid #3a3e45}
.layer{display:grid;grid-template-columns:230px 1fr;gap:26px;align-items:center;background:#15171b;border:1px solid #2b2e34;border-radius:18px;padding:26px 32px}.layer>b{font-size:34px;color:#c9f23a}"""

chain = lambda xs: '<div class="chain">' + '<span class="ar">→</span>'.join(f'<span class="{"k2" if i == len(xs) - 1 else "k1"}">{x}</span>' for i, x in enumerate(xs)) + '</div>'
SLIDE = {
'cover': '<div class="w" style="justify-content:center;gap:34px"><div class="mark r" data-s="0">[·]</div><div class="eye r" data-s="0">科研小助手 Agent · 参赛作品</div><h1 class="r" data-s="0" style="font-size:112px">研证 ResearchTrace</h1><div class="r" data-s="1" style="font-size:50px;color:#d9dad5">每个结论，都能回到原文</div><div class="chips r" data-s="1"><div class="chip l">版本感知</div><div class="chip">逐句核验</div><div class="chip">混合检索</div><div class="chip">引用图谱</div><div class="chip">有界智能体</div></div></div>',
'overview': '<div class="w" style="gap:34px"><div class="eye r" data-s="0">六大模块 · 一条证据链</div><div class="grid r" data-s="0">' + ''.join(f'<div class="mod"><b>{a}</b><span>{b}</span></div>' for a, b in [('文档解析', '版本识别 · 扫描件 · 长书'), ('知识问答', '单篇 · 跨论文 · 多轮'), ('阅读翻译', '原版 · 中英对照 · 划词'), ('检索推荐', 'arXiv · Crossref · 订阅'), ('图谱综述', '真实引用 · 核心节点'), ('写作绘图', '框架 · Related Work · 图表')]) + '</div><div class="r" data-s="1">' + chain(['论文版本', '页码', '原文段落', '逐字引文', '一键回到原文']) + '</div></div>',
'architecture': '<div class="w" style="gap:26px;justify-content:center"><div class="eye r" data-s="0">AI 技术方案</div><div class="layer r" data-s="0"><b>解析层</b><div class="chips"><div class="chip">原生文字层</div><div class="chip">PP-OCRv5</div><div class="chip">MinerU</div><div class="chip">PaddleOCR-VL</div><div class="chip l">带坐标的段落 · 公式 · 表格</div></div></div><div class="layer r" data-s="1"><b>检索层</b><div class="chips"><div class="chip">BM25</div><div class="chip">向量检索</div><div class="chip">RRF 融合</div><div class="chip">重排精排</div><div class="chip l">中文问题 → 英文检索词</div></div></div><div class="layer r" data-s="2"><b>生成与核验</b><div class="chips"><div class="chip">白名单工具</div><div class="chip">原子主张</div><div class="chip">逐字引文校验</div><div class="chip">数值 · 版本校验</div><div class="chip l">独立模型复核</div></div></div></div>',
'models': '<div class="w" style="justify-content:center"><div class="eye r" data-s="0">本地模型部署</div><div class="row r" data-s="0"><div class="c"><b>Nemotron-3.5-Embed-8B</b><span>向量检索 · 4096 维</span></div><div class="c"><b>Nemotron-3.5-Rerank-8B</b><span>交叉编码重排</span></div></div><div class="chips r" data-s="1"><div class="chip l">BF16 推理</div><div class="chip">多卡分配</div><div class="chip">显存预算保护</div><div class="chip">版本锁定</div><div class="chip">哈希校验</div></div><div class="row r" data-s="2"><div class="c"><div class="n">23,185</div><span>4096 维向量</span></div><div class="c"><div class="n">39</div><span>份文献</span></div><div class="c"><div class="n">1,986</div><span>页全量解析</span></div></div></div>',
'metrics': '<div class="w" style="gap:24px;justify-content:center"><div class="eye r" data-s="0">检索评测 · 75 道有答案题</div><div class="r" data-s="0"><div style="font-size:33px;font-weight:700;margin-bottom:4px">首位命中 Hit@1</div><div class="bar"><div>BM25</div><div class="t"><i style="--v:20%"></i></div><em>20.0%</em></div><div class="bar"><div>完整链路</div><div class="t"><i class="h" style="--v:72%"></i></div><em>72.0%</em></div></div><div class="r" data-s="1"><div style="font-size:33px;font-weight:700;margin-bottom:4px">前二十命中 Hit@20</div><div class="bar"><div>BM25</div><div class="t"><i style="--v:70.7%"></i></div><em>70.7%</em></div><div class="bar"><div>完整链路</div><div class="t"><i class="h" style="--v:100%"></i></div><em>100%</em></div></div><div class="r" data-s="2"><div style="font-size:33px;font-weight:700;margin-bottom:4px">嵌入模型对比 Hit@5 · 核心 45 题</div><div class="bar"><div>Qwen3-Embedding-8B</div><div class="t"><i style="--v:88.9%"></i></div><em>88.9%</em></div><div class="bar"><div>Nemotron-Embed-8B</div><div class="t"><i class="h" style="--v:95.6%"></i></div><em>95.6%</em></div></div></div>',
'engineering': '<div class="w" style="justify-content:center"><div class="eye r" data-s="0">工程质量</div><div class="row r" data-s="0"><div class="c"><div class="n">TESTS</div><span>项自动化测试通过</span></div><div class="c"><div class="n">122</div><span>项原文定位核验</span></div><div class="c"><div class="n">11</div><span>个白名单工具</span></div></div><div class="chips r" data-s="0"><div class="chip">任务持久化</div><div class="chip">可取消</div><div class="chip">断点恢复</div></div><div class="chips r" data-s="1"><div class="chip l">事务化配额账本</div><div class="chip">SSRF 防护</div><div class="chip">上传内容不可信隔离</div></div><div class="row r" data-s="2"><div class="c"><b>2 核 2G 云主机</b><span>轻量部署 · HTTPS 公网服务</span></div><div class="c"><b>本地模型 ⇄ 云端向量</b><span>自动切换</span></div></div></div>',
'close': '<div class="w" style="justify-content:center;align-items:center;text-align:center;gap:34px"><div class="mark r" data-s="0">[·]</div><h1 class="r" data-s="0" style="font-size:104px">研证 ResearchTrace</h1><div class="r" data-s="0" style="font-size:48px;color:#d9dad5">版本清楚 · 出处可点 · 每个结论都能回到原文</div><div class="r" data-s="1" style="font-size:34px;color:#c9f23a">researchtrace.sluna.xyz</div></div>'}
if TESTS: SLIDE['engineering'] = SLIDE['engineering'].replace('TESTS', TESTS)

frames = []; marks = {}; log = []
with sync_playwright() as p:
    b = p.chromium.launch(proxy={'server': 'socks5://127.0.0.1:18995'})
    c0 = b.new_context(viewport={'width': 1920, 'height': 1080}); g = c0.new_page(); g.set_default_timeout(45000)
    g.goto(B + '/'); g.fill('#access-code', CODE); g.keyboard.press('Enter'); g.wait_for_selector('.main-sidebar')
    st = c0.storage_state(); before = {d['id'] for d in g.evaluate("fetch('/api/v1/documents').then(r=>r.json())")}; c0.close()
    # The recording context starts logged out so the login is filmed; later scenes reuse its session.
    ctx = b.new_context(viewport={'width': 1920, 'height': 1080}); ctx.add_init_script(script=CURSOR)
    pg = ctx.new_page(); pg.set_default_timeout(45000)

    class Cast:
        def __init__(s, ctx_, page_):
            s.cdp = ctx_.new_cdp_session(page_); s.cdp.on('Page.screencastFrame', s.on)
        def on(s, e):
            fn = f'{OUT}/f{len(frames):06d}.jpg'; open(fn, 'wb').write(base64.b64decode(e['data']))
            frames.append((float(e['metadata'].get('timestamp') or time.time()), os.path.basename(fn)))
            try: s.cdp.send('Page.screencastFrameAck', {'sessionId': e['sessionId']})
            except Exception: pass
        def start(s): s.cdp.send('Page.startScreencast', {'format': 'jpeg', 'quality': 90, 'maxWidth': 1920, 'maxHeight': 1080, 'everyNthFrame': 1})
        def stop(s): s.cdp.send('Page.stopScreencast')
    cast = Cast(ctx, pg); cast.start()

    class S:
        def __init__(s, i): s.d = SC[i]; s.i = i; s.dur = s.d['end'] - s.d['start']; s.off = 0.0; s.cuts = []; s.hold_at = None
        def go(s):
            pg.wait_for_timeout(400); s.t0 = time.time(); marks[s.i] = {'ready': s.t0, 'dur': s.dur, 'start': s.d['start'], 'cuts': s.cuts}
        def hold(s): s.hold_at = time.time()
        def resume(s):
            now = time.time(); s.cuts.append((s.hold_at, now)); s.off += now - s.hold_at; s.hold_at = None
        def at(s, n, off=0):
            t = s.t0 + s.off + (s.d['lines'][n]['start'] - s.d['start']) + off; d = t - time.time()
            if d > 0: pg.wait_for_timeout(int(d * 1000))
        def done(s):
            d = s.t0 + s.off + s.dur + .15 - time.time()
            if d > 0: pg.wait_for_timeout(int(d * 1000))
    pos = [960, 600]
    def glide(x, y, ms=320):
        n = max(6, int(ms / 28)); x0, y0 = pos
        for i in range(1, n + 1):
            k = i / n; k = k * k * (3 - 2 * k); pg.mouse.move(x0 + (x - x0) * k, y0 + (y - y0) * k); pg.wait_for_timeout(16)
        pos[:] = [x, y]
    def box(l): l.scroll_into_view_if_needed(); return l.bounding_box()
    def hover(l, ms=320):
        b_ = box(l); glide(b_['x'] + b_['width'] / 2, b_['y'] + b_['height'] / 2, ms)
    def click(l, ms=320):
        hover(l, ms); pg.wait_for_timeout(110); pg.mouse.down(); pg.wait_for_timeout(50); pg.mouse.up(); pg.wait_for_timeout(60)
    def wheel(dy, ms=900):
        n = max(4, int(ms / 40))
        for _ in range(n): pg.mouse.wheel(0, dy / n); pg.wait_for_timeout(28)
    def smooth(l, block='center'): l.evaluate("(e,b)=>e.scrollIntoView({behavior:'smooth',block:b})", block)
    def outline(it):
        if not it.is_visible(): pg.get_by_label('折叠或展开目录').click(); pg.wait_for_timeout(350)
    def docs(): return pg.evaluate("fetch('/api/v1/documents').then(r=>r.json())")
    def ensure_login():
        if not ctx.cookies(B): ctx.add_cookies(st['cookies'])

    def slide(i):
        s = S(i); pg.goto('about:blank'); pg.set_content(f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>{SLIDE[i]}</body></html>'); pg.wait_for_timeout(250); s.go()
        rev = lambda n: pg.evaluate("n=>document.querySelectorAll('[data-s=\"'+n+'\"]').forEach(e=>e.classList.add('on'))", n)
        rev(0); steps = max(int(e.get_attribute('data-s')) for e in pg.query_selector_all('[data-s]'))
        for n in range(1, steps + 1):
            if n < len(s.d['lines']): s.at(n, .1)
            rev(n)
        s.done()

    def library():
        s = S('library'); ctx.clear_cookies(); pg.goto(B + '/'); pg.wait_for_selector('#access-code'); pg.wait_for_timeout(1200); s.go()
        click(pg.locator('#access-code'), 500); pg.keyboard.type(CODE, delay=70); pg.wait_for_timeout(250); pg.keyboard.press('Enter'); pg.wait_for_selector('.main-sidebar')
        pg.wait_for_selector('.line-item'); hover(pg.locator('.line-item').first, 450); s.at(1, -.3)
        click(pg.get_by_role('link', name='文献库', exact=True)); pg.wait_for_selector('.document-row'); pg.wait_for_timeout(900); glide(900, 620); wheel(420, 1500); pg.wait_for_timeout(1500); wheel(-420, 1100); s.done()

    def version():
        s = S('version'); ensure_login(); pg.goto(B + '/library'); pg.wait_for_selector('.document-row'); pg.wait_for_timeout(500)
        hover(pg.get_by_role('button', name='导入 PDF').first, 400)
        # Upload and identity check take ~15 s; filming starts once the version dialog is open.
        pg.set_input_files('input[type=file]', UPLOAD); pg.wait_for_selector('.vc-dialog[open]', timeout=150000); pg.wait_for_timeout(700); s.go()
        hover(pg.locator('.vc-dialog[open]').get_by_text('paper-upload.pdf').first if pg.locator('.vc-dialog[open]').get_by_text('paper-upload.pdf').count() else pg.locator('.vc-label').first, 500)
        s.at(1, -.2); hover(pg.locator('.vc-basis'), 450); s.at(2, .1); hover(pg.locator('.vc-recommend'), 450); s.done()

    def revision():
        s = S('revision'); s.go(); click(pg.get_by_role('button', name='AI 总结主要修订')); pg.wait_for_selector('.vc-summary:not(.pending)', timeout=40000); pg.wait_for_timeout(300)
        smooth(pg.locator('.vc-summary')); glide(960, 620); pg.wait_for_timeout(900); wheel(230, 1500); s.at(1, .1)
        if not pg.locator('.vc-counts').count(): pg.get_by_role('button', name='逐段比较').click()
        pg.wait_for_selector('.vc-counts', timeout=30000); smooth(pg.locator('.vc-counts'), 'start'); pg.wait_for_timeout(800); hover(pg.locator('.vc-counts')); s.at(2, .1)
        l = pg.get_by_role('button', name='保留较新的 v7（推荐）'); smooth(l); pg.wait_for_timeout(700); click(l); pg.wait_for_selector('.vc-dialog[open]', state='detached', timeout=20000); s.done()

    def reader():
        s = S('reader'); ensure_login(); pg.goto(f'{B}/read/{V7}'); pg.wait_for_selector('.pdf-page canvas', timeout=120000); pg.get_by_role('button', name='中英对照', exact=True).click(); pg.wait_for_selector('.tp-block'); pg.wait_for_timeout(2200); s.go()
        glide(560, 560, 500); wheel(500, 1800); s.at(1, 0); glide(1350, 560, 400); wheel(500, 1600)
        it = pg.locator('.outline-item', has_text='Scaled Dot-Product').first; s.at(2, -.1); outline(it); click(it); pg.wait_for_timeout(1500)
        h = pg.get_by_role('separator', name='调整原文与译文的宽度'); bb = h.bounding_box(); glide(bb['x'] + 2, bb['y'] + 260, 260); pg.mouse.down(); glide(bb['x'] + 190, bb['y'] + 260, 800); pg.mouse.up(); pg.wait_for_timeout(350)
        bb = h.bounding_box(); glide(bb['x'] + 2, bb['y'] + 260, 200); pg.mouse.down(); glide(bb['x'] - 90, bb['y'] + 260, 600); pg.mouse.up(); s.done()

    def selection():
        s = S('selection'); ensure_login()
        if '/read/' not in pg.url: pg.goto(f'{B}/read/{V7}'); pg.wait_for_selector('.pdf-page canvas', timeout=120000)
        pg.get_by_role('button', name='原文', exact=True).click(); pg.wait_for_timeout(1800)
        sp = None
        for _ in range(20):
            cands = pg.locator('.pdf-page .textLayer span').all()
            for el in cands[:400]:
                bb = el.bounding_box()
                if bb and 200 < bb['y'] < 820 and bb['width'] > 220 and 300 < bb['x'] < 1500: sp = el; break
            if sp: break
            pg.wait_for_timeout(500)
        s.go(); bb = sp.bounding_box(); glide(bb['x'] + 2, bb['y'] + bb['height'] / 2, 280); pg.mouse.down(); glide(bb['x'] + min(bb['width'], 380), bb['y'] + bb['height'] / 2, 520); pg.mouse.up(); pg.wait_for_timeout(250)
        click(pg.get_by_role('button', name='翻译选段'), 240); pg.wait_for_selector('.sp-result', timeout=20000); s.done(); pg.keyboard.press('Escape')

    def scan():
        s = S('scan'); ensure_login(); pg.goto(f'{B}/read/{SCAN}'); pg.wait_for_selector('.pdf-page canvas', timeout=120000); pg.get_by_role('button', name='中英对照', exact=True).click(); pg.wait_for_selector('.tp-block')
        i = pg.get_by_label('页码'); i.fill('4'); i.press('Enter'); pg.wait_for_timeout(3500); s.go(); glide(620, 600, 500); s.at(1, .1); wheel(240, 1300); s.at(2, .1); glide(1380, 560, 500); wheel(300, 1500); s.done()

    def book():
        s = S('book'); ensure_login(); d = [x for x in docs() if x['page_count'] == 541][0]; pg.goto(f"{B}/read/{d['id']}"); pg.wait_for_selector('.pdf-page canvas', timeout=240000); pg.wait_for_timeout(2000)
        it = pg.locator('.outline-item').filter(has_text='Convolutional networks').first; outline(it); it.click(); pg.wait_for_timeout(5000)
        i = pg.get_by_label('页码'); i.fill('300'); i.press('Enter'); pg.wait_for_timeout(5000); i.fill('1'); i.press('Enter'); pg.wait_for_timeout(2500); smooth(it); pg.wait_for_timeout(600)
        s.go(); glide(960, 560, 500); wheel(300, 1500); s.at(1, 0); click(it); pg.wait_for_timeout(3000); click(i); i.fill('300'); i.press('Enter'); s.done()

    def ask():
        s = S('ask'); ensure_login(); pg.goto(B + '/chat'); pg.wait_for_selector('.thread-list'); pg.get_by_role('button', name='新对话').click(); pg.wait_for_timeout(500)
        pg.get_by_role('button', name='选择论文').click(); pg.locator('.picker-list label').filter(has_text='v7').filter(has_text='Attention').first.click(); pg.wait_for_timeout(300)
        pg.locator('.side-drawer').get_by_role('button', name='完成', exact=False).click(); pg.wait_for_timeout(600); s.go()
        click(pg.get_by_label('输入问题'), 500); pg.keyboard.type(QUESTION, delay=55); pg.wait_for_timeout(300); s.at(1, -1.2); pg.keyboard.press('Enter')
        pg.wait_for_selector('.turn-question', timeout=20000); glide(1100, 520, 600); s.done()
        t = time.time(); pg.wait_for_selector('.turn-answer .answer-body', timeout=600000)
        for _ in range(120):
            if not pg.locator('.run-progress').count(): break
            pg.wait_for_timeout(1000)
        marks['ask']['wait_seconds'] = round(time.time() - t, 1); pg.wait_for_timeout(1500)

    def answer():
        s = S('answer'); a = pg.locator('.turn-answer').last; a.locator('.answer-body').wait_for(); s.go()
        hover(a.locator('.answer-claim').first, 500); pg.wait_for_timeout(700); hover(a.locator('.answer-claim').last, 600); s.at(1, -.3)
        click(a.locator('.cite-mark').first, 380); pg.wait_for_timeout(1500); click(pg.get_by_role('button', name='在原文中定位').first, 300)
        s.hold(); pg.wait_for_selector('.evidence-highlight', timeout=60000); pg.wait_for_timeout(500); smooth(pg.locator('.evidence-highlight').first); pg.wait_for_timeout(900); s.resume()
        hover(pg.locator('.evidence-highlight').first, 500); s.at(2, -1.4); pg.go_back()
        s.hold(); pg.wait_for_selector('.turn-answer .answer-body', timeout=60000); a = pg.locator('.turn-answer').last; t_ = a.locator('.tool-button', has_text='已核对'); t_.wait_for(); smooth(t_); pg.wait_for_timeout(800); s.resume()
        click(t_, 380); pg.wait_for_timeout(700); glide(1150, 640, 500); s.done()

    def cross():
        s = S('cross'); ensure_login(); pg.goto(B + '/chat'); pg.wait_for_selector('.thread-item'); pg.locator('.thread-item', has_text='Post-LN').first.click(); pg.wait_for_selector('.turn-answer .answer-body'); pg.wait_for_timeout(1000); s.go()
        hover(pg.locator('.answer-claim').first, 500); pg.wait_for_timeout(600); hover(pg.locator('.cite-mark').nth(1), 450); pg.wait_for_timeout(500); hover(pg.locator('.answer-claim').nth(3), 500); s.at(1, .1)
        hover(pg.locator('.answer-claim.insufficient').first, 600); s.done()

    def agent():
        s = S('agent'); t_ = pg.locator('.tool-button[title="公开执行记录与检索范围"]').last; s.go(); click(t_, 450); pg.wait_for_timeout(900); glide(1120, 640, 400); wheel(420, 1800); s.at(1, .1); wheel(620, 2800); s.done()

    def discover():
        s = S('discover'); ensure_login(); pg.goto(B + '/discover'); pg.get_by_label('学术检索').fill('attention is all you need'); pg.get_by_role('button', name='检索', exact=True).click(); pg.wait_for_selector('.paper-result', timeout=60000); pg.wait_for_timeout(700); s.go()
        hover(pg.locator('.paper-result').first, 500); wheel(380, 1700); s.at(1, .1); wheel(520, 2000); s.done()

    def graph():
        s = S('graph'); ensure_login(); pg.goto(B + '/insights'); pg.wait_for_selector('.rt-graph-canvas canvas'); q = pg.get_by_label('核心节点', exact=True)
        q.select_option(q.locator('option', has_text='Attention Is All You Need').first.get_attribute('value')); pg.wait_for_timeout(2800); s.go()
        glide(980, 640, 500); s.at(1, -.3); click(pg.locator('.rt-graph-citation-list button').first, 380); pg.wait_for_timeout(1200); hover(pg.locator('.rt-graph-canvas'), 500); s.at(2, .1)
        l = pg.locator('.rt-graph-node-list summary').first
        if l.count(): click(l, 400)
        s.done()

    def writing():
        s = S('writing'); ensure_login(); pg.goto(B + '/studio'); pg.get_by_role('button', name='产物', exact=True).click(); pg.locator('.artifact-row', has_text='研究 idea').first.click(); pg.wait_for_selector('.artifact-preview'); pg.wait_for_timeout(700); s.go()
        hover(pg.locator('.artifact-row', has_text='研究 idea').first, 450); glide(1300, 560, 450); smooth(pg.locator('.artifact-preview').get_by_text('Related Work', exact=True).first, 'start'); s.at(1, .1)
        hover(pg.locator('.artifact-preview').get_by_text('待完成实验与验证', exact=True).first, 500); s.done()

    def chart():
        s = S('chart'); ensure_login(); pg.goto(B + '/studio'); pg.wait_for_selector('.csv-upload'); pg.set_input_files('input[aria-label="上传 CSV"]', CSV); pg.wait_for_timeout(800)
        pg.fill('.chart-controls input[placeholder="可选"] >> nth=0', '检索链路逐级提升'); pg.wait_for_timeout(300); s.go()
        hover(pg.locator('.csv-upload'), 450); click(pg.get_by_role('button', name='生成图表'), 500); pg.wait_for_selector('.generated-chart', timeout=40000); pg.wait_for_timeout(900)
        smooth(pg.locator('.generated-chart')); hover(pg.locator('.generated-chart'), 500); s.done()

    seq = [('cover', lambda: slide('cover')), ('overview', lambda: slide('overview')), ('library', library), ('version', version), ('revision', revision),
           ('reader', reader), ('selection', selection), ('scan', scan), ('book', book), ('ask', ask), ('answer', answer), ('cross', cross), ('agent', agent),
           ('discover', discover), ('graph', graph), ('writing', writing), ('chart', chart)] + [(k, (lambda k=k: slide(k))) for k in ['architecture', 'models', 'metrics', 'engineering', 'close']]
    for i, f in seq:
        if only and i not in only: continue
        t = time.time()
        try: f(); log.append((i, 'ok', round(time.time() - t, 1)))
        except Exception as e:
            log.append((i, 'FAIL', str(e).split('\n')[0][:160])); marks.setdefault(i, {'ready': time.time(), 'dur': 0, 'start': SC[i]['start']})
            try: pg.screenshot(path=f'{F}/fail-{i}.png')
            except Exception: pass
        print(log[-1], flush=True)
    cast.stop()
    g = ctx.new_page(); g.set_default_timeout(30000); ensure_login(); D = lambda: g.evaluate("fetch('/api/v1/documents').then(r=>r.json())"); g.goto(B + '/library'); g.wait_for_selector('.document-row')
    new = [d for d in D() if d['id'] not in before]
    for _ in range(60):
        if not new or all(d['status'] in ('ready', 'failed', 'partial') for d in new): break
        g.wait_for_timeout(2500); new = [d for d in D() if d['id'] not in before]
    if new:
        g.reload(); g.wait_for_selector('.document-row'); r = g.locator('.document-row').filter(has_text='Attention Is All You Need').filter(has=g.locator('.badge', has_text='v1')).first
        r.get_by_role('button', name='管理文献', exact=False).click(); g.get_by_role('button', name='删除此版本').click(); g.get_by_role('button', name='确认删除').click(); g.wait_for_timeout(1500)
    print('library restored', {d['id'] for d in D()} == before, flush=True); b.close()

failed = {l[0] for l in log if l[1] == 'FAIL'}; order = sorted(frames)
for i, m in marks.items():
    if i in failed: continue
    d = f'{F}/scenes/{i}'; shutil.rmtree(d, ignore_errors=True); os.makedirs(d); r0 = m['ready']; idx = []; prev = None
    for ts, fn in order:
        if ts <= r0: prev = (ts, fn)
    cuts = m.get('cuts') or []; total_cut = sum(b_ - a_ for a_, b_ in cuts)
    def shift(ts):
        if any(a_ <= ts < b_ for a_, b_ in cuts): return None
        return ts - sum(b_ - a_ for a_, b_ in cuts if b_ <= ts)
    use = ([(r0, prev[1])] if prev else [])
    for ts, fn in order:
        if r0 < ts <= r0 + m['dur'] + total_cut + .3:
            t2 = shift(ts)
            if t2 is not None: use.append((t2, fn))
    # The frame on screen when filming resumes after a cut.
    for a_, b_ in cuts:
        last = [fn for ts, fn in order if ts <= b_]
        if last: use.append((shift(b_ + 1e-6) - 1e-4, last[-1]))
    use.sort()
    for n, (ts, fn) in enumerate(use):
        shutil.copy(f'{OUT}/{fn}', f'{d}/{n:05d}.jpg'); idx.append(round(ts - r0, 3))
    json.dump({'times': idx, 'dur': m['dur'], 'start': m['start'], 'wait_seconds': m.get('wait_seconds')}, open(f'{d}/index.json', 'w'))
print('frames', len(frames), 'fails', [l for l in log if l[1] == 'FAIL'])
