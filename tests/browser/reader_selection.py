"""Isolated reader + real PDF.js/browser/translation handler regression.

Run from repo root with the project Python and RT_BROWSER_EXECUTABLE configured.
Uses genuine core PDFs, a temporary Vite entry and explicitly fake QA/translation
providers. No main app, keys, live API, GPU, main port or service restarts.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pypdfium2 as pdfium
from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from services.api import models, store, text_translation

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps/web"
PORT = int(os.environ.get("RT_READER_TEST_PORT", "19065"))
OUTPUT = Path(
    os.environ.get("RT_READER_TEST_OUTPUT", "/tmp/rt-reader-selection-browser")
)
FILES = {
    "v1": "1706.03762v1.pdf",
    "v7": "1706.03762v7.pdf",
    "scan": "1706.03762v1_img.pdf",
    "book": "UnderstandingDeepLearning_02_09_26_C.pdf",
}
HARNESS = """import React,{useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Reader} from './src/Reader';
import {ModelConfig} from './src/ModelConfig';
import './src/styles/tokens.css'; import './src/styles/app.css';
const versions=VERSIONS;
function Fixture(){const[id,setId]=useState('v1');const[run,setRun]=useState<string|null>(null);const[shown,setShown]=useState(true);return <ModelConfig.Provider value={{model_configured:true,core_model:'FIXTURE_NO_API',batch_model:'FIXTURE_NO_API',paid_fallback:false}}><div style={{height:40,display:'flex',gap:8}}>{versions.map(v=><button key={v.id} onClick={()=>setId(v.id)} data-fixture-version={v.id}>{v.id}</button>)}<button onClick={()=>setShown(x=>!x)} data-fixture-toggle>mount/unmount</button></div><div style={{height:'calc(100vh - 40px)'}}>{shown&&<Reader versions={versions} version={versions.find(v=>v.id===id)!} setVersion={setId} highlight={null} onEvidence={()=>{}} runId={run} setRunId={setRun} refresh={()=>{}} startUpload={()=>{}}/>}</div></ModelConfig.Provider>}
createRoot(document.getElementById('root')!).render(<React.StrictMode><Fixture/></React.StrictMode>);
"""


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    # Refuse to reuse a listening port rather than killing another developer.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", PORT))
    versions, blocks, pdfs = [], {}, {}
    for vid, filename in FILES.items():
        path = ROOT / "evals/pdfs/core" / filename
        pdfs[vid] = path.read_bytes()
        with pdfium.PdfDocument(path) as document:
            versions.append(
                {
                    "id": vid,
                    "work_id": vid,
                    "title": filename,
                    "filename": filename,
                    "sha256": "fixture-label-only",
                    "status": "ready",
                    "page_count": len(document),
                    "parsed_pages": len(document),
                    "dense_pages": 0,
                    "label": "REAL_PDF_FIXTURE",
                    "metadata": {},
                    "created": time.time(),
                }
            )
            pdf_page = document[0]
            textpage = pdf_page.get_textpage()
            source_text = textpage.get_text_range()
            textpage.close()
            pdf_page.close()
            blocks[vid] = (
                [
                    {
                        "id": f"{vid}-block",
                        "version_id": vid,
                        "parse_id": vid,
                        "page_index": 0,
                        "bbox": [],
                        "text": source_text,
                        "type": "paragraph",
                        "reading_order": 0,
                        "source": "REAL_PDF_FIXTURE",
                        "quality": "fixture_no_precise_bbox",
                        "metadata": {},
                    }
                ]
                if source_text
                else []
            )

    model_calls, qa_calls, checks, errors = [], [], [], []

    def provider(system, prompt, rid, **kwargs):
        assert kwargs == {"role": "light", "json_output": True}
        model_calls.append({"run_id": rid, "role": kwargs["role"]})
        return {
            "text": json.dumps(
                {
                    "translations": [
                        {"block_id": b["block_id"], "text": "FIXTURE 译文 " + b["text"]}
                        for b in json.loads(prompt)
                    ]
                }
            ),
            "model": "FIXTURE_NO_API",
        }

    original_generate, original_data = models.generate, store.DATA
    original_role = os.environ.get("RT_MODEL_LIGHT")
    html, tsx = WEB / "__reader_fixture__.html", WEB / "__reader_fixture__.tsx"
    vite = None
    with tempfile.TemporaryDirectory(prefix="rt-reader-data-") as tmp:
        store.DATA = Path(tmp)
        os.environ["RT_MODEL_LIGHT"] = "fixture-translator"
        models.generate = provider
        store.migrate()
        store.execute(
            "INSERT INTO workspaces VALUES(?,?,?)",
            ("reader-fixture", "fixture", time.time()),
        )
        for v in versions:
            store.execute(
                """INSERT INTO versions(id,workspace,title,filename,sha256,path,status,page_count,parsed_pages,created)
                VALUES(?,?,?,?,?,?,'ready',?,?,?)""",
                (
                    v["id"],
                    "reader-fixture",
                    v["title"],
                    v["filename"],
                    v["id"],
                    "fixture-only",
                    v["page_count"],
                    v["parsed_pages"],
                    time.time(),
                ),
            )
            store.execute(
                "INSERT INTO parses(id,version_id,workspace,engine,device,status,page_count,parsed_pages,created) VALUES(?,?,'reader-fixture','native','cpu','ready',?,?,?)",
                (v["id"], v["id"], v["page_count"], v["parsed_pages"], time.time()),
            )
            store.execute("INSERT INTO active_parses VALUES(?,?)", (v["id"], v["id"]))
        app = FastAPI()
        app.include_router(text_translation.router)
        app.dependency_overrides[text_translation.session_dependency] = lambda: {
            "workspace": "reader-fixture"
        }
        try:
            html.write_text(
                '<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0"><div id="root"></div><script type="module" src="/__reader_fixture__.tsx"></script></body></html>'
            )
            tsx.write_text(HARNESS.replace("VERSIONS", json.dumps(versions)))
            config = Path(tmp) / "vite.config.mjs"
            # Keep optimizer/config-loader writes outside a read-only dependency
            # symlink, even when another agent reuses this fixture runner.
            config.write_text(
                "export default "
                + json.dumps(
                    {"root": str(WEB), "cacheDir": str(Path(tmp) / "vite-cache")}
                )
                + ";"
            )
            with (OUTPUT / "vite.log").open("w") as log:
                vite = subprocess.Popen(
                    [
                        "node",
                        str(WEB / "node_modules/vite/bin/vite.js"),
                        "--config",
                        str(config),
                        "--configLoader",
                        "runner",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(PORT),
                        "--strictPort",
                    ],
                    cwd=WEB,
                    stdout=log,
                    stderr=log,
                )
            for _ in range(100):
                with socket.socket() as sock:
                    sock.settimeout(0.2)
                    if sock.connect_ex(("127.0.0.1", PORT)) == 0:
                        break
                if vite.poll() is not None:
                    raise RuntimeError("Vite startup failed")
                time.sleep(0.1)
            with TestClient(app) as client, sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.environ.get("RT_BROWSER_EXECUTABLE"),
                    headless=True,
                    args=["--no-sandbox"],
                )
                page = browser.new_page(
                    viewport={"width": 1440, "height": 1000}, device_scale_factor=1
                )
                page.on("pageerror", lambda e: errors.append(str(e)))
                # Capture console errors separately; don't suppress global rejection.
                console_errors = []
                page.on(
                    "console",
                    lambda msg: (
                        console_errors.append(msg.text) if msg.type == "error" else None
                    ),
                )

                def route(request):
                    url = urlparse(request.request.url)
                    path = url.path.removeprefix("/api/v1")
                    parts = path.split("/")
                    query = parse_qs(url.query)
                    if path == "/text/translations":
                        payload = request.request.post_data_json
                        response = client.post(
                            "/api/v1/text/translations", json=payload
                        )
                        if response.status_code == 200:
                            rid = response.json()["id"]
                            result = text_translation.handle(
                                store.one("SELECT * FROM runs WHERE id=?", (rid,))
                            )
                            store.execute(
                                "UPDATE runs SET status='completed',result=? WHERE id=?",
                                (json.dumps(result), rid),
                            )
                        request.fulfill(
                            status=response.status_code,
                            content_type="application/json",
                            body=response.text,
                        )
                        return
                    if path == "/qa/runs":
                        qa_calls.append(request.request.post_data_json)
                        rid = store.uid()
                        now = time.time()
                        store.execute(
                            "INSERT INTO runs(id,workspace,kind,status,payload,result,created,updated) VALUES(?,'reader-fixture','qa','completed',?,?,?,?)",
                            (
                                rid,
                                json.dumps(qa_calls[-1]),
                                json.dumps(
                                    {
                                        "answer": "FIXTURE explanation; not a live model answer"
                                    }
                                ),
                                now,
                                now,
                            ),
                        )
                        data = {"id": rid}
                    elif path.startswith("/runs/"):
                        if path.endswith("/events"):
                            request.fulfill(
                                content_type="text/event-stream",
                                body="event: completed\ndata: {}\n\n",
                            )
                            return
                        data = store.one("SELECT * FROM runs WHERE id=?", (parts[2],))
                        data.update(
                            result=json.loads(data["result"]),
                            payload=json.loads(data["payload"]),
                            steps=[],
                        )
                    elif path.startswith("/translations/"):
                        data = []
                    elif path.startswith("/documents/"):
                        vid = parts[2]
                        resource = parts[3]
                        if resource == "file":
                            request.fulfill(
                                content_type="application/pdf", body=pdfs[vid]
                            )
                            return
                        if resource == "blocks":
                            data = (
                                blocks[vid]
                                if int(query.get("offset", ["0"])[0]) == 0
                                else []
                            )
                        elif resource == "parses":
                            data = [
                                {
                                    "id": vid,
                                    "status": "ready",
                                    "engine": "native",
                                    "active": True,
                                    "parsed_pages": next(
                                        v["page_count"]
                                        for v in versions
                                        if v["id"] == vid
                                    ),
                                }
                            ]
                        elif resource in ("references", "search"):
                            data = []
                        elif resource == "pages":
                            data = {
                                "page_index": int(parts[4]),
                                "blocks": blocks[vid] if parts[4] == "0" else [],
                                "width": 612,
                                "height": 792,
                                "rotation": 0,
                            }
                        else:
                            raise AssertionError("Unexpected fixture resource " + path)
                    else:
                        raise AssertionError("Unexpected fixture API " + path)
                    request.fulfill(
                        content_type="application/json", body=json.dumps(data)
                    )

                page.route("**/api/v1/**", route)
                page.goto(f"http://127.0.0.1:{PORT}/__reader_fixture__.html")

                def ready():
                    page.locator(".textLayer span").first.wait_for(timeout=30000)
                    page.locator(".pdf-loading").wait_for(state="hidden", timeout=30000)

                def select_title():
                    ready()
                    # DOM Range selects PDF.js's real extracted span, not a fake
                    # text overlay; native mouse selection is checked below too.
                    return page.locator('.pdf-page[data-page-index="0"] .textLayer').evaluate(
                        """el=>{const span=[...el.querySelectorAll('span')].find(s=>s.textContent.includes('Attention Is All You Need')); if(!span)throw Error('real PDF title not found'); const r=document.createRange();r.selectNodeContents(span);const s=getSelection();s.removeAllRanges();s.addRange(r);return s.toString()}"""
                    )

                selected = select_title()
                page.get_by_role("region", name="选段操作").wait_for()
                assert selected == "Attention Is All You Need"
                checks.append("real PDF text selection opens floating selection card")
                # The card floats next to the selection inside the PDF viewport
                # and never covers the selected glyphs themselves.
                bar = page.get_by_role("region", name="选段操作").bounding_box()
                pdf = page.locator(".pdf-scroller").bounding_box()
                chosen = page.evaluate(
                    "(()=>{const r=getSelection().getRangeAt(0).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})()"
                )
                overlap = not (
                    bar["y"] >= chosen["y"] + chosen["height"] - 1
                    or bar["y"] + bar["height"] <= chosen["y"] + 1
                    or bar["x"] >= chosen["x"] + chosen["width"]
                    or bar["x"] + bar["width"] <= chosen["x"]
                )
                assert not overlap, (bar, chosen)
                assert pdf["x"] <= bar["x"] and bar["x"] + bar["width"] <= pdf["x"] + pdf["width"] + 1
                checks.append("selection card sits beside, not over, the selected text")
                page.get_by_role("button", name="就此提问", exact=True).click()
                question = page.locator("#question")
                assert (
                    selected in question.input_value()
                    and "selected_text" not in question.input_value()
                )
                assert question.evaluate("el=>el===document.activeElement")
                assert not qa_calls
                checks.append("question prefills/focuses composer without a model call")
                page.get_by_role("button", name="解释选段", exact=True).click()
                page.wait_for_function(
                    'document.querySelector(".qa-scroll").textContent.includes("FIXTURE explanation")'
                )
                assert len(qa_calls) == 1 and qa_calls[0]["version_ids"] == ["v1"]
                assert (
                    selected in qa_calls[0]["question"]
                    and "不可信数据" in qa_calls[0]["question"]
                )
                checks.append(
                    "explanation uses existing QA endpoint with selected-text constraints"
                )
                page.get_by_role("button", name="翻译选段", exact=True).click()
                page.get_by_text("翻译完成", exact=True).wait_for(timeout=10000)
                assert "FIXTURE 译文" in page.locator(".sp-result").inner_text()
                assert len(model_calls) == 1
                page.get_by_role("button", name="翻译选段", exact=True).click()
                page.locator('[data-cache="hit"]').wait_for(timeout=10000)
                assert page.locator('[data-cache="hit"]').inner_text() == "来自翻译缓存"
                assert len(model_calls) == 1
                checks.append(
                    "selection translation shows inline; repeat is a labelled persistent cache hit"
                )
                # Keyboard Tab/Enter and Escape work without mouse positioning.
                page.get_by_role("button", name="就此提问", exact=True).focus()
                page.keyboard.press("Enter")
                page.wait_for_function("document.activeElement?.id === 'question'", timeout=3000)
                page.get_by_role("button", name="翻译选段", exact=True).focus()
                page.keyboard.press("Escape")
                assert page.get_by_role("region", name="选段操作").count() == 0
                checks.append("keyboard Enter/Escape contextual actions")
                # Continuous reading: the wheel moves through pages, no page buttons needed.
                scroller = page.locator(".reader-pdf .pdf-scroller").bounding_box()
                page.mouse.move(
                    scroller["x"] + scroller["width"] / 2,
                    scroller["y"] + scroller["height"] / 2,
                )
                for _ in range(8):
                    page.mouse.wheel(0, 800)
                    page.wait_for_timeout(120)
                page_input = page.get_by_role("spinbutton", name="页码", exact=True)
                page.wait_for_function(
                    "Number(document.querySelector('.page-control input').value) > 2"
                )
                checks.append(
                    f"mouse wheel scrolls continuously to page {page_input.input_value()}"
                )
                page_input.fill("1")
                page.wait_for_function(
                    "document.querySelector('.reader-pdf .pdf-scroller').scrollTop < 5"
                )
                # 中英对照 keeps the real PDF layout on the left, aligned blocks on the right.
                page.get_by_role("button", name="中英对照", exact=True).click()
                page.locator('.translation-pane [data-block="v1-block"]').wait_for()
                assert page.locator(".reader-pdf .pdf-page canvas").count() >= 1
                page.locator(".reader-pdf .textLayer span").first.wait_for()
                checks.append("bilingual view keeps original PDF beside aligned paragraphs")
                page.get_by_role("button", name="原文", exact=True).click()
                ready()
                # Same page transform on canvas and text for zoom + all rotations.
                for _ in range(2):
                    page.get_by_role("button", name="放大", exact=True).click()
                for angle in (90, 180, 270, 0):
                    page.get_by_role("button", name="旋转页面", exact=True).click()
                    ready()
                    dims = page.locator('.pdf-page[data-page-index="0"] .pdf-page-surface').evaluate(
                        """el=>{const c=el.querySelector('canvas').getBoundingClientRect(),t=el.querySelector('.textLayer').getBoundingClientRect();return {canvas:[c.width,c.height,c.x,c.y],text:[t.width,t.height,t.x,t.y],angle:el.querySelector('.textLayer').dataset.mainRotation}}"""
                    )
                    assert dims["angle"] == str(angle), dims
                    assert all(
                        abs(a - b) < 2 for a, b in zip(dims["canvas"], dims["text"])
                    ), dims
                    checks.append(
                        f"canvas/text viewport alignment rotation={angle} zoom=120%"
                    )
                # Native mouse drag selects real PDF text at viewport coordinates.
                page.locator(".pdf-scroller").evaluate(
                    "el=>{el.scrollTop=0;el.scrollLeft=0}"
                )
                title = (
                    page.locator(".textLayer span")
                    .filter(has_text="Attention Is All You Need")
                    .first
                )
                title.scroll_into_view_if_needed()
                rect = title.bounding_box()
                page.mouse.move(rect["x"] + 2, rect["y"] + rect["height"] / 2)
                page.mouse.down()
                page.mouse.move(
                    rect["x"] + rect["width"] - 2,
                    rect["y"] + rect["height"] / 2,
                    steps=12,
                )
                page.mouse.up()
                page.get_by_role("region", name="选段操作").wait_for()
                assert "Attention" in page.evaluate("getSelection().toString()")
                checks.append(
                    "native mouse drag selects visible PDF glyphs after zoom/rotation"
                )
                for width in (1280, 1440, 1920, 390):
                    page.set_viewport_size({"width": width, "height": 1000})
                    ready()
                    select_title()
                    page.get_by_role("region", name="选段操作").wait_for()
                    close_panel = page.get_by_role(
                        "button", name="关闭问答", exact=True
                    )
                    if close_panel.is_visible():
                        close_panel.click()
                    toolbar = page.get_by_role("region", name="选段操作").bounding_box()
                    assert toolbar["width"] <= width and toolbar["x"] >= 0
                    assert page.get_by_role(
                        "button", name="翻译选段", exact=True
                    ).evaluate(
                        "el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}"
                    )
                    page.screenshot(path=str(OUTPUT / f"reader-{width}.png"))
                    checks.append(
                        f"selection toolbar visible within viewport width={width}"
                    )
                page.set_viewport_size({"width": 1440, "height": 1000})
                # 541-page original: last physical page is still lazily rendered.
                page.locator("[data-fixture-version=book]").click()
                ready()
                page.get_by_role("spinbutton", name="页码", exact=True).fill("541")
                ready()
                page.locator('.pdf-page[data-page-index="540"] canvas').wait_for(timeout=30000)
                rendered = page.locator(".pdf-page-surface canvas").count()
                assert 1 <= rendered <= 4, rendered
                assert page.locator(".pdf-page").count() == 541
                checks.append(
                    f"541-page real book: continuous layout, last page rendered, only {rendered} canvases live"
                )
                page.locator("[data-fixture-version=scan]").click()
                page.get_by_text("此页没有可选择的文字", exact=False).wait_for(
                    timeout=30000
                )
                assert page.locator(".textLayer span").count() == 0
                checks.append("real image-only PDF offers OCR parallel-view guidance")
                # Stress both fetch abort and in-flight worker/render cleanup in StrictMode.
                for i in range(30):
                    page.locator(
                        f"[data-fixture-version={'v1' if i % 2 == 0 else 'v7'}]"
                    ).click()
                    page.wait_for_timeout(15 if i % 3 else 70)
                ready()
                for _ in range(10):
                    page.locator("[data-fixture-toggle]").click()
                    page.wait_for_timeout(30)
                    page.locator("[data-fixture-toggle]").click()
                    page.wait_for_timeout(50)
                ready()
                page.wait_for_timeout(2000)
                assert not errors, errors
                assert not console_errors, console_errors
                checks.append(
                    "rapid document swaps + mount/unmount: zero pageerror or console error"
                )
                browser.close()
            report = {
                "status": "PASS",
                "checks": checks,
                "checks_passed": len(checks),
                "page_errors": errors,
                "fixture_model_calls": len(model_calls),
                "fixture_qa_calls": len(qa_calls),
                "real_model_calls": 0,
                "quota_rows": store.one("SELECT count(*) n FROM quota")["n"],
                "fixture_notice": "real PDF.js and original PDFs; isolated API router/handler with fake model and fake QA, not live answer quality",
            }
            (OUTPUT / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2)
            )
            print(json.dumps(report, ensure_ascii=False))
        except BaseException as error:
            (OUTPUT / "failure.json").write_text(
                json.dumps(
                    {
                        "status": "FAIL",
                        "error": str(error),
                        "checks_passed": checks,
                        "page_errors": errors,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            raise
        finally:
            if vite:
                vite.terminate()
                try:
                    vite.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    vite.kill()
                    vite.wait()
            html.unlink(missing_ok=True)
            tsx.unlink(missing_ok=True)
            models.generate = original_generate
            store.DATA = original_data
            if original_role is None:
                os.environ.pop("RT_MODEL_LIGHT", None)
            else:
                os.environ["RT_MODEL_LIGHT"] = original_role


if __name__ == "__main__":
    main()
