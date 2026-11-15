"""Synthetic fixtures are labeled unit tests; no model availability claim."""
import io
import json

import pytest
from reportlab.pdfgen import canvas

from services.api import documents, retrieval, store


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(documents, "DATA", tmp_path)
    store.migrate()
    monkeypatch.setattr(retrieval, "index_dense", lambda *args: {"status": "unavailable", "reason": "UNIT_TEST_NO_LIVE_API"})
    return tmp_path


def make_pdf(version="7", content="The optimizer uses beta1 0.9 and eight GPUs.", title="An Example of Evidence", arxiv_id="1234.56789"):
    out = io.BytesIO()
    pdf = canvas.Canvas(out)
    pdf.setTitle(title)
    pdf.setAuthor("Ada Researcher")
    pdf.setFont("Helvetica", 20)
    pdf.drawString(50, 780, title)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, 750, "arXiv:" + arxiv_id + "v" + version)
    pdf.drawString(50, 710, "1 Introduction")
    pdf.drawString(50, 680, content)
    pdf.drawString(290, 25, "1")
    pdf.showPage()
    pdf.setFont("Helvetica", 12)
    pdf.drawString(50, 780, "References")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, 740, "[1] Someone. A real fixture citation. arXiv:1111.22222. 2020.")
    pdf.drawString(290, 25, "2")
    pdf.save()
    return out.getvalue()


def parse_uploaded(workspace="alpha", content=None, filename="random.pdf"):
    uploaded = documents.upload_document(workspace, filename, content or make_pdf())
    run = store.one("SELECT * FROM runs WHERE id=?", (uploaded["run_id"],))
    return uploaded, documents.parse_document(run)


def test_new_upload_parse_fts_and_source_locations(isolated):
    uploaded, result = parse_uploaded()
    assert result["parsed_pages"] == 2
    assert result["failed_pages"] == []
    version = store.one("SELECT * FROM versions WHERE id=?", (uploaded["document"]["id"],))
    assert version["label"] == "v7"
    assert version["title"] == "An Example of Evidence"
    candidates = retrieval.retrieve("alpha", [version["id"]], "beta1 GPUs")
    assert candidates["mode"] == "keyword"
    assert any("eight GPUs" in b["text"] for b in candidates["blocks"])
    assert any("eight GPUs" in b["text"] for b in retrieval.retrieve("alpha", [version["id"]], "用了多少GPU和beta1")["blocks"])
    for b in candidates["blocks"]:
        assert b["version_id"] == version["id"]
        assert b["page_index"] == 0
        assert all(0 <= x <= 1 for x in b["bbox"])
    refs = store.rows("SELECT * FROM refs WHERE version_id=?", (version["id"],))
    assert len(refs) == 1
    assert refs[0]["target_identity"] == "arxiv:1111.22222"


def test_duplicate_and_content_derived_version_order(isolated):
    newer = make_pdf("7")
    first, _ = parse_uploaded(content=newer, filename="a17b.pdf")
    duplicate = documents.upload_document("alpha", "another-name.pdf", newer)
    assert duplicate["duplicate"] is True
    assert duplicate["document"]["id"] == first["document"]["id"]
    second, _ = parse_uploaded(content=make_pdf("1", "Earlier optimizer uses four GPUs."), filename="9b7c.pdf")
    a = store.one("SELECT * FROM versions WHERE id=?", (first["document"]["id"],))
    b = store.one("SELECT * FROM versions WHERE id=?", (second["document"]["id"],))
    assert a["work_id"] == b["work_id"]
    assert b["label"] == "v1"
    assert "较新版本" in json.loads(b["metadata"])["version_notice"]
    diff = documents.compare_versions("alpha", a["id"], b["id"])
    assert diff["counts"]["modified"] > 0
    assert any(c["before"] and "eight GPUs" in c["before"]["text"] for c in diff["changes"])
    assert any("eight GPUs" in x["text"] for x in retrieval.retrieve("alpha", [a["id"]], "GPUs")["blocks"])
    assert all("four GPUs" not in x["text"] for x in retrieval.retrieve("alpha", [a["id"]], "GPUs")["blocks"])


def test_workspace_and_deleted_version_isolation(isolated):
    uploaded, _ = parse_uploaded()
    version_id = uploaded["document"]["id"]
    with pytest.raises(ValueError):
        retrieval.retrieve("beta", [version_id], "GPU")
    with pytest.raises(ValueError):
        documents.compare_versions("beta", version_id, version_id)
    store.execute("UPDATE versions SET deleted=1 WHERE id=?", (version_id,))
    with pytest.raises(ValueError):
        retrieval.retrieve("alpha", [version_id], "GPU")


def test_same_title_different_identifiers_do_not_merge(isolated):
    first, _ = parse_uploaded(content=make_pdf(arxiv_id="1211.22222"), filename="x.pdf")
    second, _ = parse_uploaded(content=make_pdf(arxiv_id="1211.33333"), filename="y.pdf")
    a = store.one("SELECT work_id FROM versions WHERE id=?", (first["document"]["id"],))
    b = store.one("SELECT work_id FROM versions WHERE id=?", (second["document"]["id"],))
    assert a["work_id"] != b["work_id"]


def test_corrupt_unsupported_and_filename_safety(isolated):
    with pytest.raises(ValueError):
        documents.upload_document("alpha", "bad.pdf", b"%PDF-this is corrupted")
    with pytest.raises(ValueError):
        documents.upload_document("alpha", "bad.txt", b"some text")
    upload = documents.upload_document("alpha", "../../evil.pdf", make_pdf())
    assert upload["document"]["filename"] == "evil.pdf"


def test_cancel_checkpoint_and_resume_is_idempotent(isolated):
    upload = documents.upload_document("alpha", "new.pdf", make_pdf())
    run = store.one("SELECT * FROM runs WHERE id=?", (upload["run_id"],))
    store.execute("UPDATE runs SET status='cancelled' WHERE id=?", (run["id"],))
    assert documents.parse_document(run)["status"] == "cancelled"
    assert store.one("SELECT parsed_pages FROM versions WHERE id=?", (upload["document"]["id"],))["parsed_pages"] == 0
    store.execute("UPDATE runs SET status='running' WHERE id=?", (run["id"],))
    documents.parse_document(run)
    count = store.one("SELECT count(*) n FROM blocks")["n"]
    documents.parse_document(run)
    assert store.one("SELECT count(*) n FROM blocks")["n"] == count
    assert store.one("SELECT count(*) n FROM pages")["n"] == 2


def test_cited_snapshot_cannot_be_silently_reparsed(isolated):
    uploaded, _ = parse_uploaded()
    vid = uploaded["document"]["id"]
    run = store.one("SELECT * FROM runs WHERE id=?", (uploaded["run_id"],))
    block = store.one("SELECT * FROM blocks WHERE version_id=? AND text LIKE '%eight GPUs%'", (vid,))
    store.execute("INSERT INTO claims VALUES(?,?,?,?,?,?)", ("claim", "alpha", run["id"], "source_fact", "fixture claim", "{}"))
    store.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?)", ("evidence", "alpha", "claim", vid, block["id"], block["page_index"], block["text"], "located_semantics_pending"))
    documents.parse_document(run)  # Normal resume skips ready pages without mutation.
    assert store.one("SELECT text,bbox FROM blocks WHERE id=?", (block["id"],)) == {"text": block["text"], "bbox": block["bbox"]}
    store.execute("UPDATE versions SET parsed_pages=0 WHERE id=?", (vid,))
    with pytest.raises(ValueError, match="历史引用"):
        documents.parse_document(run)
    assert store.one("SELECT text,bbox FROM blocks WHERE id=?", (block["id"],)) == {"text": block["text"], "bbox": block["bbox"]}


def test_reupload_deleted_bytes_restores_original_snapshot(isolated):
    content = make_pdf()
    uploaded, _ = parse_uploaded(content=content)
    vid = uploaded["document"]["id"]
    before = store.rows("SELECT id,text,bbox FROM blocks WHERE version_id=? ORDER BY id", (vid,))
    store.execute("UPDATE versions SET deleted=1 WHERE id=?", (vid,))
    store.execute("DELETE FROM block_fts WHERE id IN (SELECT id FROM blocks WHERE version_id=?)", (vid,))
    restored = documents.upload_document("alpha", "renamed.pdf", content)
    assert restored["document"]["id"] == vid
    documents.parse_document(store.one("SELECT * FROM runs WHERE id=?", (restored["run_id"],)))
    assert store.rows("SELECT id,text,bbox FROM blocks WHERE version_id=? ORDER BY id", (vid,)) == before
    assert retrieval.retrieve("alpha", [vid], "GPU")["blocks"]


def test_two_column_order_is_column_first():
    words = []
    for i in range(45):
        y = 160 + i * 12
        words.append({"text": "left" + str(i), "x0": 40, "x1": 170, "top": y, "bottom": y + 10, "size": 10})
        words.append({"text": "right" + str(i), "x0": 340, "x1": 470, "top": y, "bottom": y + 10, "size": 10})
    blocks = documents._make_blocks(words, 600, 800, "v", 0, "fixture", "native")
    joined = " ".join(b["text"] for b in blocks)
    assert joined.index("left44") < joined.index("right0")


def test_subscript_stays_with_actual_symbol_and_value():
    words = [
        {"text": "β", "x0": 100, "x1": 106, "top": 100, "bottom": 110, "size": 10},
        {"text": "1", "x0": 106, "x1": 110, "top": 106, "bottom": 113, "size": 7},
        {"text": "=", "x0": 112, "x1": 118, "top": 100, "bottom": 110, "size": 10},
        {"text": "0.9", "x0": 120, "x1": 135, "top": 100, "bottom": 110, "size": 10},
    ]
    blocks = documents._make_blocks(words, 600, 800, "v", 0, "fixture", "native")
    assert len(blocks) == 1
    assert blocks[0]["text"] == "β 1 = 0.9"


def test_dense_provider_vectors_are_used_and_model_spaces_isolated(isolated, monkeypatch):
    uploaded, _ = parse_uploaded()
    version_id = uploaded["document"]["id"]
    block = store.one("SELECT * FROM blocks WHERE text LIKE '%eight GPUs%'")
    import numpy as np
    store.execute("INSERT INTO embeddings VALUES(?,?,?,?,?,?)", (block["id"], "alpha", version_id, "gemini-embedding-001", 2, np.asarray([1., 0.], dtype=np.float32).tobytes()))
    # Explicit mock is isolated to unit coverage; this does not certify a live provider.
    import sys
    import types
    monkeypatch.setitem(sys.modules, "services.api.models", types.SimpleNamespace(embed=lambda *args, **kwargs: {"model": "gemini-embedding-001", "dimension": 2, "vectors": [[1., 0.]]}))
    result = retrieval.retrieve("alpha", [version_id], "something semantically equivalent")
    assert result["mode"] == "hybrid"
    assert result["dense"][0]["block_id"] == block["id"]
    monkeypatch.setenv("RT_DISABLE_DENSE", "true")
    assert retrieval.retrieve("alpha", [version_id], "something semantically equivalent")["dense"] == []


def test_real_cpu_ocr_scan_is_searchable(isolated):
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.utils import ImageReader
    if not documents._tesseract_binary():
        pytest.skip("Tesseract unavailable: no claim of OCR success")
    image = Image.new("RGB", (1200, 1600), "white")
    draw = ImageDraw.Draw(image)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font = ImageFont.truetype(font_path, 38)
    draw.text((100, 220), "Scanned experiment: unique marker 7189.", fill="black", font=font)
    draw.text((100, 300), "The measured temperature was 42 degrees.", fill="black", font=font)
    out = io.BytesIO()
    pdf = canvas.Canvas(out, pagesize=(600, 800))
    pdf.drawImage(ImageReader(image), 0, 0, width=600, height=800)
    pdf.save()
    upload, result = parse_uploaded(content=out.getvalue(), filename="unseen_scan.pdf")
    assert result["failed_pages"] == []
    found = retrieval.retrieve("alpha", [upload["document"]["id"]], "7189 temperature")
    assert found["blocks"]
    assert any(b["source"] == "tesseract" and "7189" in b["text"] for b in found["blocks"])


def test_cropbox_coordinates_are_visible_page_relative(isolated):
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import RectangleObject
    out = io.BytesIO()
    pdf = canvas.Canvas(out, pagesize=(600, 800))
    pdf.setFont("Helvetica", 18)
    pdf.drawString(100, 600, "Evidence anchor 7189 remains visible.")
    pdf.save()
    reader = PdfReader(io.BytesIO(out.getvalue()))
    page = reader.pages[0]
    page.cropbox = RectangleObject((50, 100, 550, 700))
    writer = PdfWriter()
    writer.add_page(page)
    cropped = io.BytesIO()
    writer.write(cropped)
    upload, _ = parse_uploaded(content=cropped.getvalue(), filename="crop.pdf")
    block = retrieval.retrieve("alpha", [upload["document"]["id"]], "7189")["blocks"][0]
    assert abs(block["bbox"][0] - .1) < .01
    assert .13 < block["bbox"][1] < .2
    page_record = store.one("SELECT * FROM pages WHERE version_id=?", (upload["document"]["id"],))
    assert page_record["width"] == 500
    assert page_record["height"] == 600


@pytest.mark.parametrize("rotation", [90, 270])
def test_rotated_crop_source_coordinates(isolated, rotation):
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import RectangleObject
    out = io.BytesIO()
    pdf = canvas.Canvas(out, pagesize=(600, 800))
    pdf.setFont("Helvetica", 18)
    pdf.drawString(100, 600, "Evidence anchor 7189 remains visible.")
    pdf.save()
    page = PdfReader(io.BytesIO(out.getvalue())).pages[0]
    page.cropbox = RectangleObject((50, 100, 550, 700))
    page.rotate(rotation)
    writer = PdfWriter()
    writer.add_page(page)
    output = io.BytesIO()
    writer.write(output)
    upload, result = parse_uploaded(content=output.getvalue(), filename="rotated.pdf")
    assert result["failed_pages"] == []
    block = retrieval.retrieve("alpha", [upload["document"]["id"]], "7189")["blocks"][0]
    assert "Evidence anchor 7189 remains visible." in block["text"]
    box = block["bbox"]
    if rotation == 90:
        assert .80 < box[0] < .85
        assert .08 < box[1] < .12
    else:
        assert .13 < box[0] < .20
        assert .88 < box[3] < .92
    physical = store.one("SELECT * FROM pages WHERE version_id=?", (upload["document"]["id"],))
    assert physical["width"] == 600 and physical["height"] == 500
    assert physical["rotation"] == rotation


def run_document_acceptance():
    """Reproducible integration runner; no model calls, no pre-recorded answers."""
    import hashlib
    import os
    import resource
    import subprocess
    import sys
    import time
    from pathlib import Path

    assert os.environ.get("ENABLE_DENSE", "").lower() == "false", "Set ENABLE_DENSE=false: this runner has no API budget"
    store.migrate()
    workspace = "doc-validation-" + store.uid()[:8]
    output = {"kind": "real PDF parsing/FTS/OCR + synthetic longbook engineering", "api_calls": 0, "cases": []}
    uploaded_ids = []
    for filename in ("b90f732e.pdf", "c31d8f44.pdf", "de408a19.pdf", "scan_derived.pdf"):
        started = time.time()
        path = Path("evals/files") / filename
        upload = documents.upload_document(workspace, filename, path.read_bytes())
        run = store.one("SELECT * FROM runs WHERE id=?", (upload["run_id"],))
        result = documents.parse_document(run)
        version = store.one("SELECT * FROM versions WHERE id=?", (upload["document"]["id"],))
        version.pop("path")
        version["metadata"] = json.loads(version["metadata"])
        blocks = store.rows("SELECT id,page_index,text,type,bbox,source,quality FROM blocks WHERE version_id=? ORDER BY page_index,reading_order", (version["id"],))
        query = "GPUs training optimizer beta1" if filename != "scan_derived.pdf" else "attention model sequence"
        found = retrieval.retrieve(workspace, [version["id"]], query)
        record = {"file": filename, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "version": version, "parse_result": result, "elapsed_seconds": round(time.time() - started, 3), "rss_max_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, "first_page_blocks": [b for b in blocks if b["page_index"] == 0][:22], "retrieval_query": query, "retrieval": found}
        output["cases"].append(record)
        uploaded_ids.append(version["id"])
        print(filename, version["title"], version["identity"], version["label"], result["parsed_pages"], "pages", "refs", result["references"], "search blocks", len(found["blocks"]), flush=True)
    v7, v1 = [store.one("SELECT * FROM versions WHERE id=?", (v,)) for v in uploaded_ids[:2]]
    assert v7["identity"] == v1["identity"] == "arxiv:1706.03762"
    assert v7["label"] == "v7" and v1["label"] == "v1"
    assert v7["work_id"] == v1["work_id"]
    assert "较新版本" in json.loads(v1["metadata"])["version_notice"]
    diff = documents.compare_versions(workspace, v7["id"], v1["id"])
    assert diff["changes"]
    output["version_diff"] = {"counts": diff["counts"], "changes": diff["changes"][:20], "same_work": diff["same_work"]}
    target = store.DATA / "evidence.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2))

    path = Path("evals/files/long_engineering.pdf")
    upload = documents.upload_document(workspace, path.name, path.read_bytes())
    run = store.one("SELECT * FROM runs WHERE id=?", (upload["run_id"],))
    vid, rid = upload["document"]["id"], run["id"]
    env = dict(os.environ, ENABLE_DENSE="false", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    code = "import resource,json;resource.setrlimit(resource.RLIMIT_AS,(1400*1024**2,1400*1024**2));from services.api import documents,store;run=store.one('SELECT * FROM runs WHERE id=?',(" + repr(rid) + ",));print(json.dumps(documents.parse_document(run)),flush=True);print('RSS_KIB',resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,flush=True)"
    # Kill the actual parser process after a persistent checkpoint; resume the same run.
    child = subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    peak_kib = 0
    checkpoint_pages = 0
    for _ in range(1200):
        if child.poll() is not None:
            break
        checkpoint_pages = store.one("SELECT parsed_pages FROM versions WHERE id=?", (vid,))["parsed_pages"]
        try:
            status_text = Path(f"/proc/{child.pid}/status").read_text()
            match = __import__("re").search(r"VmHWM:\s+(\d+)", status_text)
            peak_kib = max(peak_kib, int(match.group(1))) if match else peak_kib
        except FileNotFoundError:
            pass
        if checkpoint_pages >= 30:
            child.kill()
            break
        time.sleep(.1)
    killed_stdout, killed_stderr = child.communicate(timeout=10)
    assert checkpoint_pages >= 30, (checkpoint_pages, killed_stdout, killed_stderr)
    before_count = store.one("SELECT count(*) n FROM blocks WHERE version_id=?", (vid,))["n"]
    resumed = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=900)
    assert resumed.returncode == 0, resumed.stderr[-2000:]
    final = store.one("SELECT * FROM versions WHERE id=?", (vid,))
    assert final["parsed_pages"] == final["page_count"] == 541
    assert final["status"] == "ready"
    latter = store.rows("SELECT page_index,text FROM pages WHERE version_id=? AND page_index IN (300,499,540)", (vid,))
    latter_queries = []
    for page in latter:
        # New queries are selected from actual back-half text, never sample-name branches.
        marker = __import__("re").search(r"RTMARK\d+", page["text"])
        query = marker.group(0) if marker else next((line[:100] for line in page["text"].split("\n") if len(line) > 40), page["text"][:100])
        matches = retrieval.retrieve(workspace, [vid], query, limit=30)
        latter_queries.append({"page_index": page["page_index"], "query": query, "returned_pages": [b["page_index"] for b in matches["blocks"]]})
        assert page["page_index"] in latter_queries[-1]["returned_pages"], latter_queries[-1]
    output["longbook"] = {"source": "self-authored derived engineering fixture, not official 541-page textbook", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "version_id": vid, "run_id": rid, "killed_returncode": child.returncode, "checkpoint_pages": checkpoint_pages, "checkpoint_block_count": before_count, "resumed_stdout": resumed.stdout, "final_pages": final["parsed_pages"], "sparse_pages": store.one("SELECT count(*) n FROM pages WHERE version_id=? AND status='ready'", (vid,))["n"], "peak_polled_kib_before_kill": peak_kib, "memory_limit_mib": 1400, "latter_queries": latter_queries}
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print("EVIDENCE", target, "longbook", output["longbook"], flush=True)


if __name__ == "__main__":
    run_document_acceptance()
