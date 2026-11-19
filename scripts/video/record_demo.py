"""Record the ResearchTrace walkthrough from the running app, then assemble it.

Pipeline (no model or provider calls; the app runs with RT_PROVIDER_MODE=disabled):
1. narration audio per line already synthesized (see synthesize step in README)
2. every scene is played in Chromium at 1920x1080 while Chrome's screencast
   streams frames with timestamps; each narration line starts an action and
   its start time is recorded, so audio is placed exactly where it was spoken
3. ffmpeg turns frames into video, mixes narration and burns subtitles

App scenes use real local parses of the bundled PDFs. Saved answers come from
scripts/replay_saved_answers.py; two stills are real 2026-11-18 public captures.

    python scripts/video/record_demo.py --config <run.json> [--only chat]
"""
import argparse
import base64
import json
import math
import subprocess
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GAP = 0.45      # pause after each line
LEAD = 0.7      # silence before the first line of a scene
TAIL = 0.9      # hold after the last line

CURSOR_JS = r"""
(() => {
  const install = () => {
    if (document.getElementById('__rt_cursor')) return;
    const c = document.createElement('div');
    c.id = '__rt_cursor';
    c.innerHTML = '<svg width="28" height="28" viewBox="0 0 28 28"><path d="M4 2 L4 22 L9.5 17 L13 25 L16.5 23.5 L13 15.8 L20.5 15.8 Z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg><i></i>';
    Object.assign(c.style, {position: 'fixed', left: '0', top: '0', zIndex: 2147483647, pointerEvents: 'none',
      transform: 'translate(-100px,-100px)', filter: 'drop-shadow(0 2px 3px rgba(0,0,0,.35))'});
    const ring = c.querySelector('i');
    Object.assign(ring.style, {position: 'absolute', left: '-14px', top: '-14px', width: '32px', height: '32px',
      borderRadius: '50%', border: '3px solid rgba(201,242,58,.95)', opacity: '0', transform: 'scale(.4)',
      transition: 'opacity .35s ease, transform .35s ease'});
    document.documentElement.appendChild(c);
    document.addEventListener('mousemove', e => { c.style.transform = `translate(${e.clientX - 4}px,${e.clientY - 2}px)`; }, true);
    document.addEventListener('mousedown', () => { ring.style.transition = 'none'; ring.style.opacity = '1'; ring.style.transform = 'scale(.4)';
      requestAnimationFrame(() => { ring.style.transition = 'opacity .45s ease, transform .45s ease'; ring.style.opacity = '0'; ring.style.transform = 'scale(1.5)'; }); }, true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install); else install();
})();
"""


def wav_seconds(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


class Screencast:
    def __init__(self, page, folder):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.frames = []
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on('Page.screencastFrame', self._frame)

    def _frame(self, params):
        path = self.folder / f'{len(self.frames):06d}.jpg'
        path.write_bytes(base64.b64decode(params['data']))
        self.frames.append((params['metadata']['timestamp'], path))
        try:
            self.cdp.send('Page.screencastFrameAck', {'sessionId': params['sessionId']})
        except Exception:
            pass

    def start(self):
        self.cdp.send('Page.startScreencast', {'format': 'jpeg', 'quality': 92, 'maxWidth': 1920,
                                               'maxHeight': 1080, 'everyNthFrame': 1})

    def stop(self):
        self.cdp.send('Page.stopScreencast')


class Pointer:
    def __init__(self, page):
        self.page, self.x, self.y = page, 1500.0, 900.0

    def glide(self, x, y, ms=650):
        steps = max(8, int(ms / 16))
        x0, y0 = self.x, self.y
        for i in range(1, steps + 1):
            t = i / steps
            e = 0.5 - math.cos(math.pi * t) / 2
            self.page.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
            self.page.wait_for_timeout(ms / steps)
        self.x, self.y = x, y

    def to(self, locator, ms=650, dx=0.5, dy=0.5):
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        self.glide(box['x'] + box['width'] * dx, box['y'] + box['height'] * dy, ms)
        return box

    def click(self, locator, ms=650, pause=250, **k):
        self.to(locator, ms, **k)
        self.page.wait_for_timeout(pause)
        self.page.mouse.down()
        self.page.mouse.up()


def smooth_scroll(page, selector, delta, ms=1200):
    page.evaluate("""([sel, delta, ms]) => { const el = sel ? document.querySelector(sel) : document.scrollingElement;
      el.scrollBy({top: delta, behavior: 'smooth'}); }""", [selector, delta, ms])
    page.wait_for_timeout(ms)


def wheel(page, pointer, dy, steps=10, pause=60):
    for _ in range(steps):
        page.mouse.wheel(0, dy / steps)
        page.wait_for_timeout(pause)


# ── scene actions ──────────────────────────────────────────────────────────

def build_actions(cfg):
    base = cfg['base']
    ids = cfg['ids']

    def a(name):
        def wrap(fn):
            ACTIONS[name] = fn
            return fn
        return wrap
    ACTIONS = {}

    @a('login_page')
    def _(page, ptr):
        ptr.glide(1300, 560, 900)
        ptr.to(page.get_by_placeholder('访问码'), 700)

    @a('guest_click')
    def _(page, ptr):
        ptr.click(page.get_by_role('button', name='以游客身份体验'), 800)
        page.get_by_role('dialog').wait_for(timeout=60000)

    @a('guest_dialog_point')
    def _(page, ptr):
        rows = page.locator('.guest-facts > div')
        ptr.to(rows.nth(0), 700, dx=0.35)
        page.wait_for_timeout(1800)
        ptr.to(rows.nth(1), 600, dx=0.35)

    @a('guest_dialog_quota')
    def _(page, ptr):
        rows = page.locator('.guest-facts > div')
        ptr.to(rows.nth(2), 600, dx=0.35)
        page.wait_for_timeout(2200)
        ptr.to(rows.nth(3), 600, dx=0.35)

    @a('guest_chip')
    def _(page, ptr):
        ptr.click(page.get_by_role('dialog').get_by_role('button', name='开始体验'), 700)
        page.locator('.guest-chip').wait_for()
        page.wait_for_timeout(700)
        ptr.to(page.locator('.guest-chip'), 800)

    @a('library_open')
    def _(page, ptr):
        page.goto(base + '/library')
        page.locator('.document-row').first.wait_for()
        ptr.glide(900, 520, 900)

    @a('library_scroll')
    def _(page, ptr):
        old = page.locator('.document-row', has_text='旧版本').first
        old.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        ptr.to(old.get_by_text('旧版本'), 900)
        page.wait_for_timeout(1500)
        ptr.to(page.locator('.document-row', has_text='Attention Is All You Need').last, 700, dx=0.2)

    @a('compare_versions')
    def _(page, ptr):
        ptr.click(page.get_by_role('link', name='比较'), 700)
        page.locator('.compare-selector label').first.wait_for()
        labels = page.locator('.compare-selector label', has_text='Attention Is All You Need')
        v1 = labels.filter(has_text='v1').first
        v7 = labels.filter(has_text='v7').first
        ptr.click(v1, 600, dx=0.1)
        ptr.click(v7, 600, dx=0.1)
        ptr.click(page.get_by_role('button', name='版本差异'), 600)
        page.locator('.diff-change').first.wait_for(timeout=60000)
        page.wait_for_timeout(600)
        page.locator('.diff-change').first.scroll_into_view_if_needed()
        ptr.to(page.locator('.diff-change').nth(1), 800)

    @a('reader_open')
    def _(page, ptr):
        page.goto(f"{base}/read/{ids['v7']}")
        page.locator('.textLayer span').first.wait_for(timeout=60000)
        page.wait_for_timeout(1200)
        ptr.glide(1000, 600, 700)
        wheel(page, ptr, 900, 14, 70)
        page.wait_for_timeout(600)
        wheel(page, ptr, 900, 14, 70)

    @a('reader_outline')
    def _(page, ptr):
        item = page.locator('.outline-item', has_text='Scaled Dot-Product Attention').first
        ptr.click(item, 800, dx=0.3)
        page.wait_for_timeout(1500)

    @a('reader_select')
    def _(page, ptr):
        span = page.locator('.pdf-page[data-page-index="3"] .textLayer span', has_text='We suspect that').first
        span.scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        box = span.bounding_box()
        y = box['y'] + box['height'] / 2
        ptr.glide(box['x'] + 2, y, 700)
        page.mouse.down()
        steps = 40
        for i in range(1, steps + 1):
            page.mouse.move(box['x'] + 2 + (box['width'] - 4) * i / steps, y)
            page.wait_for_timeout(22)
        ptr.x, ptr.y = box['x'] + box['width'] - 2, y
        page.mouse.up()
        page.get_by_role('region', name='选段操作').wait_for()
        page.wait_for_timeout(900)
        ptr.to(page.get_by_role('button', name='翻译选段'), 700)
        page.wait_for_timeout(900)
        ptr.to(page.get_by_role('button', name='解释选段'), 500)
        page.wait_for_timeout(600)
        ptr.to(page.get_by_role('button', name='就此提问'), 500)

    @a('reader_refs')
    def _(page, ptr):
        page.keyboard.press('Escape')
        ptr.click(page.get_by_role('tab', name='参考文献'), 700)
        page.wait_for_timeout(1200)
        entry = page.locator('.reference-row').nth(2)
        if entry.count():
            ptr.click(entry, 700, dx=0.3)
            page.wait_for_timeout(1500)

    @a('book_open')
    def _(page, ptr):
        page.goto(f"{base}/read/{ids['book']}")
        page.locator('.textLayer span').first.wait_for(timeout=60000)
        page.wait_for_timeout(800)
        ptr.glide(1000, 640, 700)
        wheel(page, ptr, 1600, 16, 60)

    @a('book_jump')
    def _(page, ptr):
        items = page.locator('.outline-item')
        target = items.filter(has_text='Transformers').first if items.filter(has_text='Transformers').count() else items.nth(min(12, items.count() - 1))
        ptr.click(target, 800, dx=0.3)
        page.wait_for_timeout(2200)
        box = page.get_by_label('页码')
        ptr.click(box, 700)
        box.fill('300')
        box.press('Enter')
        page.wait_for_timeout(400)
        page.locator('.pdf-loading').wait_for(state='hidden', timeout=60000)
        page.wait_for_timeout(1200)

    @a('chat_open')
    def _(page, ptr):
        page.goto(f"{base}/chat/{cfg['thread']}")
        page.locator('.turn-answer .answer-body').first.wait_for(timeout=60000)
        page.wait_for_timeout(600)
        page.evaluate("document.querySelector('.chat-scroll').scrollTo({top: 0})")
        ptr.glide(1100, 300, 900)

    @a('chat_point')
    def _(page, ptr):
        first = page.locator('.turn-answer').first
        claims = first.locator('.answer-claim')
        for i in range(min(3, claims.count())):
            ptr.to(claims.nth(i), 700, dx=0.15)
            page.wait_for_timeout(500)
        ptr.to(first.locator('.cite-mark').first, 700)

    @a('chat_cite')
    def _(page, ptr):
        first = page.locator('.turn-answer').first
        ptr.click(first.locator('.cite-mark').first, 500)
        first.locator('.evidence-peek').wait_for()
        page.wait_for_timeout(800)
        ptr.to(first.locator('.evidence-peek blockquote'), 800, dx=0.3)

    @a('chat_locate')
    def _(page, ptr):
        ptr.click(page.locator('.evidence-peek').get_by_role('button', name='在原文中定位'), 700)
        page.get_by_test_id('evidence-highlight').wait_for(timeout=60000)
        page.wait_for_timeout(900)
        ptr.to(page.get_by_test_id('evidence-highlight'), 900)

    @a('chat_checks')
    def _(page, ptr):
        page.go_back()
        page.locator('.turn-answer .answer-body').first.wait_for(timeout=60000)
        page.wait_for_timeout(700)
        page.evaluate("document.querySelector('.chat-scroll').scrollTo({top: 0})")
        page.wait_for_timeout(500)
        first = page.locator('.turn-answer').first
        button = first.locator('.tool-button').first
        ptr.click(button, 800)
        first.locator('.check-row').first.wait_for()
        page.wait_for_timeout(600)
        smooth_scroll(page, '.chat-scroll', 360, 1100)
        ptr.to(first.locator('.check-row').nth(0), 700, dx=0.4)
        page.wait_for_timeout(1500)
        ptr.to(first.locator('.check-row').nth(4), 700, dx=0.4)

    @a('chat_sources')
    def _(page, ptr):
        first = page.locator('.turn-answer').first
        first.locator('.tool-button').first.click()
        page.wait_for_timeout(300)
        page.evaluate("document.querySelector('.chat-scroll').scrollTo({top: 0, behavior: 'smooth'})")
        page.wait_for_timeout(900)
        ptr.to(first.locator('.claim-tag').first, 800)
        page.wait_for_timeout(1300)
        tools = first.locator('.answer-tools .tool-button')
        for i in range(tools.count()):
            ptr.to(tools.nth(i), 450)
            page.wait_for_timeout(250)

    @a('chat_scroll')
    def _(page, ptr):
        ptr.glide(1100, 640, 600)
        smooth_scroll(page, '.chat-scroll', 900, 1600)
        second = page.locator('.turn-answer').nth(1)
        ptr.to(second.locator('.answer-claim').first, 800, dx=0.2)
        page.wait_for_timeout(1200)
        ptr.to(page.locator('.turn-answer').nth(2).locator('.answer-claim').first, 800, dx=0.2)

    @a('graph_open')
    def _(page, ptr):
        page.goto(base + '/insights')
        page.locator('.rt-graph-stage canvas, .rt-graph-stage svg').first.wait_for(timeout=60000)
        page.wait_for_timeout(800)
        ptr.glide(830, 640, 900)

    @a('graph_core')
    def _(page, ptr):
        select = page.get_by_label('核心节点')
        ptr.to(select, 700)
        value = page.evaluate("""() => { const s = document.querySelector('select[aria-label="核心节点"]');
          const o = [...s.options].find(o => o.text.startsWith('Attention Is All You Need')); return o && o.value; }""")
        select.select_option(value)
        page.wait_for_timeout(1500)
        ptr.glide(840, 560, 800)

    @a('graph_all')
    def _(page, ptr):
        ptr.click(page.get_by_role('group', name='图谱范围').get_by_role('button', name='全部'), 700)
        page.wait_for_timeout(1600)
        ptr.to(page.locator('.rt-graph-inspector'), 800, dy=0.3)

    @a('graph_future')
    def _(page, ptr):
        ptr.click(page.get_by_text('Future Work', exact=True).first, 700)
        page.wait_for_timeout(1500)
        ptr.glide(900, 520, 800)

    @a('studio_open')
    def _(page, ptr):
        page.goto(base + '/studio')
        page.wait_for_timeout(800)
        tab = page.locator('.tab-row button', has_text='论文框架').first
        ptr.click(tab, 700)
        page.wait_for_timeout(1500)
        ptr.glide(800, 420, 800)

    @a('studio_chart')
    def _(page, ptr):
        tab = page.locator('.tab-row button').filter(has_text='图表').first
        ptr.click(tab, 600)
        page.get_by_label('上传 CSV').set_input_files(str(ROOT / 'scripts/video/retrieval_eval.csv'))
        page.wait_for_timeout(700)
        kind = page.locator('label', has_text='类型').locator('select')
        ptr.to(kind, 600)
        kind.select_option('bar')
        page.wait_for_timeout(400)
        ptr.click(page.get_by_role('button', name='生成图表'), 700)
        page.locator('.generated-chart').wait_for(timeout=120000)
        page.wait_for_timeout(800)
        ptr.to(page.locator('.chart-caption'), 900, dx=0.3)

    @a('studio_diagram')
    def _(page, ptr):
        tab = page.locator('.tab-row button', has_text='结构图').first
        ptr.click(tab, 600)
        page.wait_for_timeout(600)
        ptr.click(page.get_by_text('手动编辑 Mermaid', exact=True), 700)
        page.locator('.diagram-preview svg').first.wait_for(timeout=90000)
        source = page.get_by_label('Mermaid 源码')
        ptr.click(source, 700)
        source.fill('flowchart LR\n  A[PDF 解析] --> B[混合检索]\n  B --> C[智能体回答]\n  C --> D[证据校验]\n  D --> E[带出处的结论]')
        page.wait_for_timeout(500)
        ptr.click(page.get_by_role('button', name='更新预览'), 600)
        page.get_by_text('带出处的结论', exact=True).last.wait_for(timeout=30000)
        ptr.to(page.locator('.diagram-preview'), 800)

    return ACTIONS


# ── recording ──────────────────────────────────────────────────────────────

def record(cfg, only=None):
    from playwright.sync_api import sync_playwright
    narration = json.loads((ROOT / cfg['narration']).read_text())
    out = Path(cfg['out'])
    audio_dir = Path(cfg['audio'])
    actions = build_actions(cfg)
    slides = (ROOT / 'scripts/video/slides.html').as_uri()
    manifest_path = out / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=cfg.get('chromium') or None)
        admin = browser.new_context(viewport={'width': 1920, 'height': 1080})
        admin.add_cookies([{'name': 'rt_session', 'value': cfg['admin_cookie'], 'url': cfg['base']}])
        admin.add_init_script(CURSOR_JS)
        admin.add_init_script("try{sessionStorage.setItem('rt-hide-config-notice','1')}catch(e){}")
        for scene in narration['scenes']:
            sid = scene['id']
            if only and sid not in only:
                continue
            durations = [wav_seconds(audio_dir / f'{sid}_{i:02d}.wav') for i in range(len(scene['lines']))]
            if scene['id'] == 'guest':
                ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
                ctx.add_init_script(CURSOR_JS)
                ctx.add_init_script("try{sessionStorage.setItem('rt-hide-config-notice','1')}catch(e){}")
            else:
                ctx = admin
            page = ctx.new_page()
            page.on('pageerror', lambda e: print('PAGEERROR', e))
            ptr = Pointer(page)
            # Set the opening view before recording starts.
            if scene['kind'] == 'slide':
                page.goto(f'{slides}?scene={sid}')
            elif scene['kind'] == 'still':
                img = (ROOT / scene['image']).as_uri()
                page.goto(f"{slides}?scene=still&img={img}&label={scene['label']}")
            elif sid == 'guest':
                page.goto(cfg['base'] + '/')
                page.get_by_role('button', name='以游客身份体验').wait_for()
            elif sid == 'library':
                page.goto(cfg['base'] + '/')
                page.wait_for_timeout(1500)
            elif sid in ('reader', 'book', 'chat', 'graph', 'studio'):
                page.goto(cfg['base'] + '/library')
                page.locator('.document-row').first.wait_for()
            page.mouse.move(ptr.x, ptr.y)
            page.wait_for_timeout(800)
            frames_dir = out / 'frames' / sid
            if frames_dir.exists():
                for f in frames_dir.glob('*.jpg'):
                    f.unlink()
            cast = Screencast(page, frames_dir)
            cast.start()
            t0 = time.time()
            page.wait_for_timeout(LEAD * 1000)
            starts = []
            for i, line in enumerate(scene['lines']):
                start = time.time()
                starts.append(start - t0)
                if scene['kind'] == 'slide':
                    page.evaluate(f'window.step({i})')
                act = line.get('act')
                if act:
                    actions[act](page, ptr)
                remaining = start + durations[i] + GAP - time.time()
                if remaining > 0:
                    page.wait_for_timeout(remaining * 1000)
            page.wait_for_timeout(TAIL * 1000)
            t_end = time.time() - t0
            cast.stop()
            page.wait_for_timeout(300)
            manifest[sid] = {'t0': t0, 'duration': t_end, 'starts': starts, 'durations': durations,
                             'frames': [[ts - t0, str(path)] for ts, path in cast.frames]}
            print(sid, f'{t_end:.1f}s', len(cast.frames), 'frames', 'starts', [round(s, 1) for s in starts], flush=True)
            page.close()
            if ctx is not admin:
                ctx.close()
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False))
        browser.close()


# ── assembly ───────────────────────────────────────────────────────────────

def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def ass_time(t):
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f'{h}:{m:02d}:{s:05.2f}'


def wrap(text, width=30):
    lines, cur = [], ''
    for ch in text:
        cur += ch
        if len(cur) >= width and ch in '，。；、：！？,;' or len(cur) >= width + 8:
            lines.append(cur)
            cur = ''
    if cur:
        lines.append(cur)
    if len(lines) > 1 and len(lines[-1]) < 6:
        tail = lines.pop()
        lines[-1] += tail
    return r'\N'.join(lines)


def assemble(cfg):
    import numpy as np
    import soundfile as sf
    narration = json.loads((ROOT / cfg['narration']).read_text())
    out = Path(cfg['out'])
    audio_dir = Path(cfg['audio'])
    manifest = json.loads((out / 'manifest.json').read_text())
    segments = []
    events = []
    offset = 0.0
    rate = 44100
    for scene in narration['scenes']:
        sid = scene['id']
        m = manifest[sid]
        dur = m['duration']
        frames = [(t, p) for t, p in m['frames'] if t <= dur]
        if not frames:
            raise SystemExit(f'no frames for {sid}')
        listing = out / f'{sid}.ffconcat'
        rows = ['ffconcat version 1.0']
        times = [max(0.0, t) for t, _ in frames]
        times[0] = 0.0
        for i, (_, path) in enumerate(frames):
            end = times[i + 1] if i + 1 < len(frames) else dur
            rows.append(f"file '{path}'")
            rows.append(f'duration {max(0.001, end - times[i]):.4f}')
        rows.append(f"file '{frames[-1][1]}'")
        listing.write_text('\n'.join(rows) + '\n')
        # Narration track for the scene.
        track = np.zeros(int(math.ceil(dur * rate)) + rate, dtype=np.float32)
        for i, start in enumerate(m['starts']):
            data, sr = sf.read(audio_dir / f'{sid}_{i:02d}.wav', dtype='float32')
            assert sr == rate
            s = int(start * rate)
            track[s:s + len(data)] += data[:max(0, len(track) - s)]
            line = scene['lines'][i]
            events.append((offset + start, offset + start + m['durations'][i] + 0.25, line['sub']))
        track = track[:int(dur * rate)]
        peak = float(np.abs(track).max() or 1.0)
        track = track * min(1.0, 0.89 / peak)
        sf.write(out / f'{sid}.wav', track, rate)
        video = out / f'{sid}.mp4'
        fade = f"fade=t=in:st=0:d=0.35,fade=t=out:st={max(0, dur - 0.4):.3f}:d=0.4"
        run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(listing), '-i', str(out / f'{sid}.wav'),
             '-vf', f'scale=1920:1080:flags=lanczos,format=yuv420p,fps=30,{fade}',
             '-af', f"afade=t=in:st=0:d=0.2,afade=t=out:st={max(0, dur - 0.3):.3f}:d=0.3",
             '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
             '-t', f'{dur:.3f}', str(video)])
        segments.append(video)
        offset += dur
        print(sid, f'{dur:.1f}s', flush=True)
    joined = out / 'joined.mp4'
    (out / 'segments.txt').write_text(''.join(f"file '{s}'\n" for s in segments))
    run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(out / 'segments.txt'), '-c', 'copy', str(joined)])
    # Subtitles: ASS for burn-in, VTT alongside.
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,WenQuanYi Zen Hei,44,&H00FFFFFF,&H00FFFFFF,&H50141414,&H64000000,0,0,0,0,100,100,1,0,3,14,0,2,220,220,54,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    body = ''.join(f'Dialogue: 0,{ass_time(a)},{ass_time(b)},Sub,,0,0,0,,{wrap(t)}\n' for a, b, t in events)
    (out / 'subtitles.ass').write_text(header + body, encoding='utf-8')
    def vtt_time(t):
        return f'{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:06.3f}'
    (out / 'subtitles.vtt').write_text('WEBVTT\n\n' + '\n'.join(f'{vtt_time(a)} --> {vtt_time(b)}\n{t}\n' for a, b, t in events),
                                       encoding='utf-8')
    final = Path(cfg['final'])
    run(['ffmpeg', '-y', '-i', str(joined), '-vf', f"ass={out / 'subtitles.ass'}", '-c:v', 'libx264', '-preset', 'slow',
         '-crf', '18', '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
         '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', str(final)])
    print('final', final, f'{offset:.1f}s')
    (out / 'timeline.json').write_text(json.dumps({'duration': offset, 'subtitles': events}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--only', nargs='*')
    parser.add_argument('--assemble', action='store_true')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    if args.assemble:
        assemble(config)
    else:
        record(config, args.only)
