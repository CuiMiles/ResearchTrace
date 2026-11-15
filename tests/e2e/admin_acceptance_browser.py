"""Verify the Admin Acceptance & Screenshot Dashboard on live http://127.0.0.1:18980."""
import json
import os
from pathlib import Path
import sys
from dotenv import dotenv_values
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/web/scripts'))
from browser_runtime import launch_chromium

BASE = os.getenv('RT_BROWSER_URL', 'http://127.0.0.1:18980').rstrip('/')
OUT = ROOT / 'evidence/ubuntu24/browser'
OUT.mkdir(parents=True, exist_ok=True)
ENV = dotenv_values(ROOT / '.env')

report = {'base_url': BASE, 'provider_requests': 0, 'checks': [], 'errors': [], 'status': 'NOT RUN'}

with sync_playwright() as p:
    browser = launch_chromium(p)
    try:
        # 1. Admin login -> Acceptance Dashboard -> Screenshots & Evidence viewer
        ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
        page = ctx.new_page()
        page.set_default_timeout(15000)
        page.on('pageerror', lambda e: report['errors'].append(f'admin_pageerror: {e}'))
        try:
            page.goto(BASE, wait_until='networkidle')
            page.get_by_label('访问码').fill(ENV['RT_ADMIN_CODE'])
            page.get_by_role('button', name='进入工作台').click()
            page.get_by_role('button', name='验收与截图').wait_for()
            page.on('console', lambda m: report['errors'].append(f'admin_console_error: {m.text}') if m.type == 'error' else None)
            page.get_by_role('button', name='验收与截图').click()
            page.get_by_role('heading', name='测试验收与截图看板').wait_for()
            page.locator('.acceptance-module-card').first.wait_for()

            # Wait for all screenshot thumbnails to finish loading and verify naturalWidth > 0
            page.wait_for_function(
                """() => {
                    const imgs = Array.from(document.querySelectorAll('.screenshot-thumb img'));
                    return imgs.length >= 10 && imgs.every(img => img.complete && img.naturalWidth > 0);
                }"""
            )
            loaded_imgs = page.locator('.screenshot-thumb img').count()
            assert not page.evaluate('document.documentElement.scrollWidth > window.innerWidth'), 'Horizontal overflow at 1440'
            page.screenshot(path=str(OUT / 'admin-acceptance-1440.png'), full_page=False)

            # Open JSON evidence preview modal
            page.locator('.evidence-links-row button.small-button').first.click()
            page.locator('.doc-viewer .log-viewer').wait_for()
            page.get_by_role('button', name='关闭结果文件').click()

            # Open screenshot lightbox
            page.locator('.screenshot-thumb').first.click()
            page.locator('.lightbox-dialog img').wait_for()
            page.screenshot(path=str(OUT / 'admin-acceptance-lightbox.png'), full_page=False)
            page.get_by_role('button', name='关闭截图预览').click()

            # Check filter and 1280 viewport
            page.get_by_role('button', name='BLOCKED (18)').click()
            page.locator('.acceptance-table tbody tr').first.wait_for()
            page.get_by_role('button', name='全部 (64)').click()
            page.set_viewport_size({'width': 1280, 'height': 800})
            assert not page.evaluate('document.documentElement.scrollWidth > window.innerWidth'), 'Horizontal overflow at 1280'

            # Verify Resources page links to acceptance dashboard
            page.get_by_role('button', name='资源与配额').click()
            page.get_by_role('button', name='验收与截图看板').wait_for()

            report['checks'].append({
                'case': 'admin_acceptance_dashboard',
                'loaded_screenshots': loaded_imgs,
                'status': 'PASS',
            })
        finally:
            ctx.close()

        # 2. Reviewer login -> confirm admin acceptance nav is hidden
        ctx2 = browser.new_context(viewport={'width': 1440, 'height': 900})
        page2 = ctx2.new_page()
        page2.set_default_timeout(15000)
        page2.on('pageerror', lambda e: report['errors'].append(f'reviewer_pageerror: {e}'))
        try:
            page2.goto(BASE, wait_until='networkidle')
            page2.get_by_label('访问码').fill(ENV['RT_ACCESS_CODE'])
            page2.get_by_role('button', name='进入工作台').click()
            page2.get_by_role('button', name='资源与配额').wait_for()
            assert page2.get_by_role('button', name='验收与截图').count() == 0
            report['checks'].append({'case': 'reviewer_hidden_admin_nav', 'status': 'PASS'})
        finally:
            ctx2.close()
    finally:
        browser.close()

report['status'] = 'PASS' if not report['errors'] and all(c['status'] == 'PASS' for c in report['checks']) else 'FAIL'
(ROOT / 'evidence/ubuntu24/admin-acceptance-browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(0 if report['status'] == 'PASS' else 1)
