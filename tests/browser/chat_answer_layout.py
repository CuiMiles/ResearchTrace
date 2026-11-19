"""Chat answer layout regression with a mocked API (layout only, no model calls).

Runs the real Vite app with every /api/v1 request answered by Playwright from an
explicitly labelled fixture: one finished answer (claims and quotes copied from
the Transformer v7 PDF, page 4) and one run still working. It checks that the
answer prose leads, that the execution record, sources and verification start
folded, and that each can be opened from the tool row. Nothing here is a live
answer and no provider is contacted.

    .venv/bin/python tests/browser/chat_answer_layout.py
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps/web"
PORT = int(os.environ.get("RT_CHAT_TEST_PORT", "19067"))
OUTPUT = Path(os.environ.get("RT_CHAT_TEST_OUTPUT", "/tmp/rt-chat-answer-layout"))
NOW = time.time()
VID = "fixture-v7"

QUOTES = {
    "q1": "We suspect that for large values of dk, the dot products grow large in magnitude, pushing the softmax function into regions where it has extremely small gradients",
    "q2": "While for small values of dk the two mechanisms perform similarly, additive attention outperforms dot product attention without scaling for larger values of dk",
    "q3": "To illustrate why the dot products get large, assume that the components of q and k are independent random variables with mean 0 and variance 1. Then their dot product, q · k = ∑ qiki, has mean 0 and variance dk.",
    "q4": "To counteract this effect, we scale the dot products by 1/√dk.",
    "q5": "We compute the dot products of the query with all keys, divide each by √dk, and apply a softmax function to obtain the weights on the values.",
}


def evidence(key: str, block: str):
    return {"block_id": block, "version_id": VID, "page_index": 3, "bbox": [0.18, 0.4, 0.82, 0.46],
            "quote": QUOTES[key], "status": "located"}


def claim(cid, text, kind, keys, status="supported"):
    return {"id": cid, "text": text, "type": kind, "evidence": [evidence(k, "b-" + k) for k in keys],
            "review": {"status": status, "method": "gemini_decision_1", "reason": "fixture"}}


CLAIMS = [
    claim("c1", "作者推测，当 d_k 较大时，点积的量级会增大，从而将 softmax 函数推向梯度极小的区域。", "source_fact", ["q1"]),
    claim("c2", "当 d_k 较小时，加性注意力与点积注意力表现相近；但当 d_k 较大时，不进行缩放的点积注意力表现不如加性注意力。", "source_fact", ["q2"]),
    claim("c3", "为说明点积为何会变大，假设 q 和 k 的各分量是均值为 0、方差为 1 的独立随机变量，则其点积的均值为 0、方差为 d_k。", "source_fact", ["q3"]),
    claim("c4", "为抵消上述效应，缩放点积注意力将查询与键的点积除以 √d_k 后再应用 softmax 函数。", "source_fact", ["q4", "q5"]),
    claim("c5", "据此可推断，将方差为 d_k 的点积除以 √d_k 可使缩放后点积的方差维持为 1，从而抑制 softmax 梯度消失问题。", "inference", ["q3", "q4"], "not_checked"),
]
STEPS = [
    {"id": 1, "event": "queued", "data": {}, "created": NOW - 162},
    {"id": 2, "event": "started", "data": {}, "created": NOW - 161},
    {"id": 3, "event": "query_rewritten", "data": {"queries": ["why scale dot product attention by sqrt dk"]}, "created": NOW - 159},
    {"id": 4, "event": "retrieved", "data": {"evidence_blocks": 8, "sparse_candidates": 40, "dense_candidates": 40, "mode": "hybrid"}, "created": NOW - 150},
    {"id": 5, "event": "model_request", "data": {"model": "FIXTURE_MODEL_A"}, "created": NOW - 149},
    {"id": 6, "event": "validating", "data": {}, "created": NOW - 60},
    {"id": 7, "event": "decision_review", "data": {"claims": 5}, "created": NOW - 40},
    {"id": 8, "event": "completed", "data": {}, "created": NOW},
]
DONE = {
    "id": "run-done", "kind": "qa", "status": "partial", "error": None, "created": NOW - 162, "updated": NOW,
    "payload": {"question": "为什么缩放点积注意力要除以 √d_k？不除会出现什么问题？", "version_ids": [VID], "thread_id": "th-fixture"},
    "result": {"claims": CLAIMS, "answer_segments": [{"text": c["text"], "claim_ids": [c["id"]]} for c in CLAIMS],
               "model": "FIXTURE_MODEL_A", "artifact_id": "fixture-artifact",
               "publication_notice": "FIXTURE：布局检查用的固定数据，不是实时回答。",
               "retrieval": {"mode": "hybrid", "blocks": [{}] * 8, "rewritten_queries": ["why scale dot product attention by sqrt dk"]}},
    "steps": STEPS,
}
RUNNING = {
    "id": "run-live", "kind": "qa", "status": "running", "error": None, "created": NOW - 9, "updated": NOW,
    "payload": {"question": "其中多头注意力的头数是多少？", "version_ids": [VID], "thread_id": "th-fixture"},
    "result": None,
    "steps": [{"id": 21, "event": "started", "data": {}, "created": NOW - 9},
              {"id": 22, "event": "retrieved", "data": {"evidence_blocks": 6, "sparse_candidates": 30, "mode": "hybrid"}, "created": NOW - 5}],
}
VERSION = {"id": VID, "work_id": "w", "title": "Attention Is All You Need (FIXTURE)", "filename": "1706.03762v7.pdf",
           "sha256": "fixture", "status": "ready", "page_count": 15, "parsed_pages": 15, "dense_pages": 15,
           "label": "v7", "metadata": {}, "created": NOW}


def respond(route):
    url = route.request.url
    path = url.split("/api/v1", 1)[1].split("?", 1)[0]
    body: object
    if path == "/auth/session":
        body = {"workspace": "fixture", "role": "reviewer"}
    elif path == "/capabilities":
        body = {"model_configured": True, "core_model": "FIXTURE", "batch_model": "FIXTURE", "paid_fallback": False}
    elif path == "/documents":
        body = [VERSION]
    elif path in ("/runs", "/batches"):
        body = []
    elif path == "/chat/threads":
        body = [{"thread_id": "th-fixture", "title": DONE["payload"]["question"], "version_ids": [VID], "turns": 2, "updated": NOW}]
    elif path == "/chat/threads/th-fixture":
        body = {"runs": [DONE, RUNNING]}
    elif path.endswith("/events"):
        return route.fulfill(status=200, headers={"Content-Type": "text/event-stream"}, body="retry: 60000\n\n")
    elif path == "/runs/run-done":
        body = DONE
    elif path == "/runs/run-live":
        body = RUNNING
    else:
        body = {}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", PORT))
    vite = subprocess.Popen(["npx", "vite", "--host", "127.0.0.1", "--port", str(PORT), "--strictPort"], cwd=WEB,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    checks, errors = [], []

    def check(name, ok, detail=""):
        checks.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    try:
        for _ in range(120):
            try:
                socket.create_connection(("127.0.0.1", PORT), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.5)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get("RT_BROWSER_EXECUTABLE") or None)
            for width, height in ((1440, 900), (390, 844)):
                page = browser.new_page(viewport={"width": width, "height": height})
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                page.route("**/api/v1/**", respond)
                page.goto(f"http://127.0.0.1:{PORT}/chat/th-fixture")
                answer = page.locator(".turn-answer").first
                answer.locator(".answer-body").wait_for(timeout=30000)
                tag = f"{width}"
                check(f"{tag} answer prose shown", answer.locator(".answer-claim").count() == 5)
                check(f"{tag} timeline folded", page.locator(".agent-timeline").count() == 0)
                check(f"{tag} sources folded", answer.locator(".answer-panel").count() == 0)
                marks = answer.locator(".cite-mark")
                numbers = [marks.nth(i).inner_text() for i in range(marks.count())]
                check(f"{tag} citations numbered by passage", numbers == ["1", "2", "3", "4", "5", "3", "4"], str(numbers))
                live = page.locator(".run-progress")
                check(f"{tag} live run is one line", live.count() == 1 and live.locator(".timeline-row").count() == 0,
                      live.inner_text() if live.count() else "")
                page.screenshot(path=OUTPUT / f"chat-{tag}-folded.png", full_page=False)
                marks.first.click()
                peek = answer.locator(".evidence-peek")
                check(f"{tag} citation opens quote", peek.count() == 1 and QUOTES["q1"][:40] in peek.inner_text())
                check(f"{tag} quote has locate", peek.get_by_role("button", name="在原文中定位").count() == 1)
                marks.first.click()
                answer.get_by_role("button", name="来源 5", exact=True).click()
                check(f"{tag} sources panel", answer.locator(".source-item").count() == 5)
                answer.get_by_role("button", name="来源 5", exact=True).click()
                answer.get_by_role("button", name="4/5 已核对", exact=True).click()
                check(f"{tag} checks panel", answer.locator(".check-row").count() == 5)
                answer.get_by_role("button", name="4/5 已核对", exact=True).click()
                answer.locator(".tool-button", has_text="过程").click()
                check(f"{tag} process panel", answer.locator(".timeline-row").count() == len(STEPS))
                page.screenshot(path=OUTPUT / f"chat-{tag}-process.png", full_page=False)
                overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                check(f"{tag} no horizontal overflow", not overflow)
                page.close()
            browser.close()
    finally:
        vite.terminate()
        vite.wait(timeout=20)
    check("no page or console errors", not errors, "; ".join(errors)[:500])
    report = {"fixture": "mocked API, layout only, no model calls", "checks": checks}
    (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    failed = [c for c in checks if c["status"] != "PASS"]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
