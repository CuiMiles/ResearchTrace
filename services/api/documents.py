"""Page-checkpointed PDF ingestion. All content is data, never instructions."""
import difflib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium

from .store import DATA, cancelled, db, event, execute, one, rows, uid

PARSER_VERSION = "pdfplumber-layout-v2"
MAX_BYTES = 70 * 1024 * 1024
MAX_PAGES = 1500


def _json(value):
    return json.dumps(value, ensure_ascii=False)


def _is_blank_page(page, path, page_index):
    """Verify an empty body, allowing only margin printer trim lines.

    Scanned pages, figures, faint body text and extraction failures must not be
    marked blank. Structural checks are confirmed by a bounded raster render.
    """
    if any(objects for kind, objects in page.objects.items() if kind != 'line'):
        return False
    x0, y0, x1, y1 = page.bbox
    inner = (x0 + page.width * .05, y0 + page.height * .05,
             x1 - page.width * .05, y1 - page.height * .05)
    for line in page.lines:
        if not (line['x1'] < inner[0] or line['x0'] > inner[2]
                or line['bottom'] < inner[1] or line['top'] > inner[3]):
            return False
    doc = rendered_page = bitmap = image = body = None
    try:
        doc = pdfium.PdfDocument(path)
        rendered_page = doc[page_index]
        bitmap = rendered_page.render(scale=.5)
        image = bitmap.to_pil().convert('RGB')
        width, height = image.size
        body = image.crop((int(width * .05), int(height * .05), int(width * .95), int(height * .95)))
        return all(low == high == 255 for low, high in body.getextrema())
    except Exception:
        return False
    finally:
        for item in (body, image, bitmap, rendered_page, doc):
            if item is not None:
                item.close()


def _decode(row):
    if not row:
        return row
    row = dict(row)
    for key in ("metadata", "bbox"):
        if isinstance(row.get(key), str):
            row[key] = json.loads(row[key])
    row.pop("path", None)
    row.pop("workspace", None)
    return row


def upload_document(workspace, filename, content, index_dense=True):
    if not isinstance(content, bytes) or not content.startswith(b"%PDF-"):
        raise ValueError("只支持具有有效 PDF 文件头的文件")
    return upload_document_file(workspace, filename, io.BytesIO(content), index_dense)


def upload_document_file(workspace, filename, source, index_dense=True, *,
                         batch_item_id=None, max_bytes=MAX_BYTES):
    """Spool and validate one file; register bytes, run and batch item atomically.

    The bytes API remains available to existing importers. Multipart callers pass
    the already spooled file, so even fifty PDFs never become fifty byte strings.
    Only upload registration changes here; parser snapshots remain untouched.
    """
    filename = Path(filename.replace("\\", "/")).name[:240]
    if not filename or filename in (".", ".."):
        raise ValueError("无效文件名")
    target = DATA / "pdfs" / workspace
    target.mkdir(parents=True, exist_ok=True)
    temporary = target / f"{uid()}.tmp"
    installed = None
    try:
        digest = hashlib.sha256()
        size = 0
        with temporary.open('xb') as output:
            while True:
                chunk = source.read(min(1024 * 1024, max_bytes - size + 1))
                if not chunk:
                    break
                if size == 0 and not chunk.startswith(b'%PDF-'):
                    raise ValueError("只支持具有有效 PDF 文件头的文件")
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError(f"PDF 超出 {max_bytes // (1024 * 1024)} MiB 上限")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if not size:
            raise ValueError("只支持具有有效 PDF 文件头的文件")
        try:
            doc = pdfium.PdfDocument(str(temporary))
            try:
                page_count = len(doc)
            finally:
                doc.close()
            if page_count < 1 or page_count > MAX_PAGES:
                raise ValueError(f"PDF 页数必须为 1–{MAX_PAGES}")
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError("PDF 损坏或已加密，无法读取；请提供可阅读的 PDF") from None
        digest = digest.hexdigest()
        now = time.time()
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            item = None
            if batch_item_id:
                item = conn.execute("SELECT i.*,b.status AS batch_status FROM batch_items i JOIN import_batches b ON b.id=i.batch_id AND b.workspace=i.workspace WHERE i.id=? AND i.workspace=?", (batch_item_id, workspace)).fetchone()
                if not item or item['status'] != 'uploading' or item['batch_status'] not in ('uploading', 'active'):
                    raise ValueError('批次文件已取消或不属于当前工作区')
            existing = conn.execute("SELECT * FROM versions WHERE workspace=? AND sha256=?", (workspace, digest)).fetchone()
            duplicate = bool(existing and not existing['deleted'])
            owns_run = not duplicate
            if duplicate:
                version_id = existing['id']
                prior = conn.execute("SELECT id,status FROM runs WHERE workspace=? AND kind='parse' AND json_extract(payload,'$.version_id')=? ORDER BY created DESC LIMIT 1", (workspace, version_id)).fetchone()
                run_id = prior['id'] if prior else None
                status = prior['status'] if prior else 'completed'
            else:
                pending = conn.execute("SELECT count(*) FROM runs WHERE workspace=? AND status IN ('queued','running')", (workspace,)).fetchone()[0]
                total = conn.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0]
                if not item and (pending >= 10 or total >= 30):
                    raise ValueError("解析队列已满，请等待或取消已有任务")
                version_id = existing['id'] if existing else uid()
                path = Path(existing['path']) if existing else target / f"{version_id}.pdf"
                # Identical reuploads must never overwrite the immutable original.
                if not path.exists():
                    temporary.replace(path)
                    installed = path
                    directory = os.open(target, os.O_RDONLY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                status = 'waiting_batch' if item else 'queued'
                if existing:
                    conn.execute("UPDATE versions SET deleted=0,status=?,path=? WHERE id=? AND workspace=?", (status, str(path), version_id, workspace))
                    for block in conn.execute("SELECT id,text FROM blocks WHERE version_id=? AND type NOT IN ('header','footer','figure') AND length(text)>0", (version_id,)).fetchall():
                        if not conn.execute("SELECT 1 FROM block_fts WHERE id=?", (block['id'],)).fetchone():
                            conn.execute("INSERT INTO block_fts(id,text) VALUES(?,?)", (block['id'], block['text']))
                else:
                    work_id = uid()
                    title = Path(filename).stem
                    conn.execute("INSERT INTO works(id,workspace,title,metadata) VALUES(?,?,?,?)", (work_id, workspace, title, _json({'identity_status': 'pending_parse'})))
                    conn.execute("INSERT INTO versions(id,workspace,work_id,title,filename,sha256,path,status,page_count,created) VALUES(?,?,?,?,?,?,?,?,?,?)", (version_id, workspace, work_id, title, filename, digest, str(path), status, page_count, now))
                run_id = uid()
                payload = {'version_id': version_id}
                if not index_dense:
                    payload['index_dense'] = False
                if item:
                    payload.update(batch_id=item['batch_id'], batch_item_id=batch_item_id)
                conn.execute("INSERT INTO runs(id,workspace,kind,status,payload,idempotency,created,updated) VALUES(?,?,?,?,?,?,?,?)", (run_id, workspace, 'parse', status, _json(payload), 'batch:' + batch_item_id if item else None, now, now))
                conn.execute("INSERT INTO steps(run_id,event,data,created) VALUES(?,?,?,?)", (run_id, status, _json({'tool': 'parse_document', 'version_id': version_id, 'page_count': page_count}), now))
            if item:
                conn.execute("UPDATE batch_items SET sha256=?,version_id=?,run_id=?,owns_run=?,duplicate=?,status=?,error=NULL,updated=? WHERE id=? AND workspace=?", (digest, version_id, run_id, int(owns_run), int(duplicate), status, now, batch_item_id, workspace))
                # Accepted files can proceed even if a later upload or API process
                # dies. An uploading item without committed bytes is never admitted.
                conn.execute("UPDATE import_batches SET status='active',updated=? WHERE id=? AND workspace=? AND status IN ('uploading','active')", (now, item['batch_id'], workspace))
        installed = None  # The committed database now owns the immutable file.
        return {'document': _decode(one('SELECT * FROM versions WHERE id=? AND workspace=?', (version_id, workspace))), 'run_id': run_id, 'duplicate': duplicate}
    except BaseException:
        if installed is not None:
            installed.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def _normalized(text):
    return re.sub(r"\W+", "", text, flags=re.UNICODE).casefold()


def _identity(pdf, page):
    """Use actual front matter, including the rotated arXiv margin stamp."""
    text = page.extract_text(layout=False, x_tolerance=1.1, y_tolerance=2.5) or ""
    chars_text = "".join(c.get("text", "") for c in page.chars)
    # Some writers encode margin characters in reverse object order.
    candidates = [text, chars_text, chars_text[::-1]]
    arxiv = None
    for candidate in candidates:
        arxiv = re.search(r"(?:arXiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5})(?:v(\d+))?", candidate, re.I)
        if arxiv:
            break
    doi = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, re.I)
    from .cards import layout_title, plausible_title
    title = (pdf.metadata or {}).get("Title", "")
    if not isinstance(title, str):
        title = ""
    metadata_title = re.sub(r"\s+", " ", title).strip()[:500]
    if not plausible_title(title) or re.search(r"untitled|microsoft|latex|template", title, re.I):
        metadata_title = ""
        # Line-level font clustering keeps small caps ("LoRA", "16x16") intact.
        title = layout_title(page)
    title = re.sub(r"\s+", " ", title).strip()[:500]
    author = (pdf.metadata or {}).get("Author", "")
    if not isinstance(author, str):
        author = ""
    result = {"parser": PARSER_VERSION, "title_source": "pdf_frontmatter", "author": author[:500],
              "pdf_metadata_title": metadata_title, "first_page_text_fingerprint": hashlib.sha256(_normalized(text).encode()).hexdigest(), "identity_status": "uncertain"}
    label = "版本待确认"
    identity = None
    if arxiv:
        result["arxiv_id"] = arxiv.group(1)
        result["arxiv_version"] = int(arxiv.group(2)) if arxiv.group(2) else None
        identity = "arxiv:" + arxiv.group(1)
        label = "v" + arxiv.group(2) if arxiv.group(2) else "arXiv 版本待确认"
        result["identity_status"] = "arxiv_frontmatter"
    elif doi:
        result["doi"] = doi.group(0).rstrip(".,;")
        identity = "doi:" + result["doi"].lower()
        result["identity_status"] = "doi_frontmatter"
    return title, identity, label, result


def _apply_identity(version, title, identity, label, metadata):
    title = title or version["title"]
    work_id = version["work_id"]
    if identity:
        match = one("SELECT * FROM works WHERE workspace=? AND identity=? AND id<>? LIMIT 1", (version["workspace"], identity, work_id))
        if match:
            work_id = match["id"]
            metadata["association_reason"] = "same " + identity
            versions = rows("SELECT id,label,metadata FROM versions WHERE workspace=? AND work_id=? AND deleted=0", (version["workspace"], work_id))
            new_n = metadata.get("arxiv_version")
            old_n = [json.loads(v["metadata"]).get("arxiv_version") for v in versions]
            if new_n and any(n and n > new_n for n in old_n):
                metadata["version_notice"] = "库中保留了较新版本；本次导入旧版本，不替换已有证据。"
            else:
                metadata["version_notice"] = "同一作品的另一版本；旧回答仍绑定原版本。"
    # Without identifier, exact title + author is only a visible candidate, never automatic merge.
    if not identity:
        candidates = rows("SELECT id,title,metadata FROM works WHERE workspace=? AND id<>?", (version["workspace"], work_id))
        metadata["same_work_candidates"] = [{"work_id": w["id"], "title": w["title"], "reason": "标题接近，需人工确认；尚未合并"} for w in candidates if difflib.SequenceMatcher(None, _normalized(title), _normalized(w["title"])).ratio() > .86][:5]
    with db() as conn:
        conn.execute("UPDATE versions SET title=?,identity=?,label=?,metadata=?,work_id=? WHERE id=?", (title, identity, label, _json(metadata), work_id, version["id"]))
        conn.execute("UPDATE works SET title=?,identity=COALESCE(?,identity),metadata=? WHERE id=?", (title, identity, _json(metadata), work_id))
        if version["work_id"] != work_id:
            conn.execute("DELETE FROM works WHERE id=? AND NOT EXISTS(SELECT 1 FROM versions WHERE work_id=?)", (version["work_id"], version["work_id"]))


def _box(words, width, height):
    return [max(0., min(1., min(w["x0"] for w in words) / width)), max(0., min(1., min(w["top"] for w in words) / height)), max(0., min(1., max(w["x1"] for w in words) / width)), max(0., min(1., max(w["bottom"] for w in words) / height))]


def _make_blocks(words, width, height, version_id, page_index, source, quality):
    """Infer a genuine middle gutter; fully read each column before next."""
    if not words:
        return []
    words = [w for w in words if w.get("upright", True)]
    if not words:
        return []
    middle = width / 2
    body = [w for w in words if height * .14 < w["top"] < height * .9]
    crossing = [w for w in body if w["x0"] < middle - 3 and w["x1"] > middle + 3]
    left = [w for w in body if w["x1"] < middle]
    right = [w for w in body if w["x0"] > middle]
    two_column = len(left) > 35 and len(right) > 35 and len(crossing) < max(4, len(body) * .015)
    # Header/footer and full-width titles are separate bands; avoid interleaving columns.
    if two_column:
        full = [w for w in words if w["x0"] < middle and w["x1"] > middle]
        # No full-width title means no shared header band: a fixed top band
        # would incorrectly splice the first left/right-column lines together.
        cutoff = max((w["bottom"] + 4 for w in full if w["top"] < height * .3), default=0)
        header = [w for w in words if w["top"] < cutoff]
        rest = [w for w in words if w["top"] >= cutoff]
        groups = [header, [w for w in rest if (w["x0"] + w["x1"]) / 2 <= middle], [w for w in rest if (w["x0"] + w["x1"]) / 2 > middle]]
    else:
        groups = [words]
    result = []
    body_size = Counter(round(w.get("size", 10)) for w in words).most_common(1)[0][0]
    for group in groups:
        lines = []
        for word in sorted(group, key=lambda w: (w["top"], w["x0"])):
            # Match by vertical glyph overlap so subscripts/superscripts remain
            # with their actual symbol rather than a detached artificial line.
            line = next((ln for ln in lines[-3:] if min(max(w["bottom"] for w in ln), word["bottom"]) - max(min(w["top"] for w in ln), word["top"]) > min(max(w["bottom"] for w in ln) - min(w["top"] for w in ln), word["bottom"] - word["top"]) * .2), None)
            if line is None:
                lines.append([word])
            else:
                line.append(word)
        paragraphs = []
        current = []
        previous = None
        for line in lines:
            line.sort(key=lambda w: w["x0"])
            text = " ".join(w["text"] for w in line)
            heading = len(text) < 150 and (max(w.get("size", 10) for w in line) > body_size * 1.13 or re.match(r"^(?:\d{1,2}(?:\.\d{1,2})*\s+[A-Z]|References\s*$|Abstract\s*$|Appendix\s+)", text))
            ref_start = bool(re.match(r"^\[\d+\]", text))
            if current and (heading or ref_start or previous is not None and line[0]["top"] - max(w["bottom"] for w in previous) > max(6, body_size * .7) or sum(len(w["text"]) for w in current) > 1300):
                paragraphs.append(current)
                current = []
            current.extend(line)
            if heading:
                paragraphs.append(current)
                current = []
            previous = line
        if current:
            paragraphs.append(current)
        for paragraph in paragraphs:
            # Joining words with spaces preserves source token values; keep line breaks out of quotes.
            text = " ".join(w["text"] for w in paragraph).strip()
            if not text:
                continue
            sizes = [w.get("size", 10) for w in paragraph]
            is_heading = len(text) < 150 and (max(sizes) > body_size * 1.13 or bool(re.match(r"^(?:\d{1,2}(?:\.\d{1,2})*\s+[A-Z]|References\s*$|Abstract\s*$)", text)))
            kind = "heading" if is_heading else "paragraph"
            if re.search(r"[=∑∏∫≤≥]", text) and len(text) < 500:
                kind = "equation"
            if re.match(r"^(Table|Figure|Fig\.)\s+\d", text, re.I):
                kind = "caption"
            meta = {"citation_markers": sorted(set(re.findall(r"\[(\d+(?:[,–\-]\s*\d+)*)\]", text))), "layout": "two_column" if two_column else "single_column"}
            result.append({"id": f"{version_id}:{page_index}:{len(result)}", "version_id": version_id, "page_index": page_index, "bbox": _box(paragraph, width, height), "type": kind, "reading_order": len(result), "text": text, "source": source, "quality": quality, "metadata": meta})
    return result


def _make_rotated_blocks(words, width, height, version_id, page_index, rotation):
    lines = []
    for word in sorted(words, key=lambda w: w["x0"], reverse=rotation == 90):
        line = next((item for item in lines[-3:] if abs(item[0]["x0"] - word["x0"]) < 3), None)
        if line is None:
            lines.append([word])
        else:
            line.append(word)
    result = []
    for line in lines:
        line.sort(key=lambda w: w["top"], reverse=rotation == 270)
        text = " ".join(w["text"] for w in line)
        result.append({"id": f"{version_id}:{page_index}:{len(result)}", "version_id": version_id, "page_index": page_index, "bbox": _box(line, width, height), "type": "paragraph", "reading_order": len(result), "text": text, "source": "pdfplumber", "quality": "native", "metadata": {"layout": "rotated_text", "citation_markers": sorted(set(re.findall(r"\[(\d+)\]", text)))}})
    return result


def _tesseract_binary():
    configured = os.environ.get("TESSERACT_CMD")
    bundled = Path(__file__).resolve().parents[2] / ".tools" / "ocr" / "usr" / "bin" / "tesseract"
    return configured or shutil.which("tesseract") or (str(bundled) if bundled.exists() else None)


def _ocr_words(pdf_path, page_index):
    binary = _tesseract_binary()
    if not binary:
        return [], "ocr_unavailable"
    doc = pdfium.PdfDocument(str(pdf_path))
    page = doc[page_index]
    render_scale = min(2., 2400 / max(page.get_size()))
    bitmap = page.render(scale=render_scale)
    image = bitmap.to_pil()
    import io
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    env = dict(os.environ)
    bundled = Path(binary).resolve().parents[1]
    tessdata = next(iter(sorted((bundled / "share" / "tesseract-ocr").glob("*/tessdata"))), None)
    if tessdata:
        env["TESSDATA_PREFIX"] = str(tessdata)
        env["LD_LIBRARY_PATH"] = str(bundled / "lib" / "x86_64-linux-gnu") + ":" + env.get("LD_LIBRARY_PATH", "")
    env["OMP_THREAD_LIMIT"] = "1"
    try:
        try:
            proc = subprocess.run([binary, "stdin", "stdout", "-l", os.environ.get("TESSERACT_LANG", "eng"), "--psm", "3", "tsv"], input=buffer.getvalue(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=90, check=False)
        except subprocess.TimeoutExpired:
            return [], "ocr_timeout"
        if proc.returncode:
            return [], "ocr_failed"
        output = proc.stdout.decode("utf-8", errors="replace")
        import csv
        words = []
        confidences = []
        for entry in csv.DictReader(io.StringIO(output), delimiter="\t"):
            text = (entry.get("text") or "").strip()
            conf = float(entry.get("conf", -1))
            if text and conf >= 0:
                x, y, w, h = [float(entry[k]) for k in ("left", "top", "width", "height")]
                words.append({"text": text, "x0": x / render_scale, "x1": (x + w) / render_scale, "top": y / render_scale, "bottom": (y + h) / render_scale, "size": h / render_scale, "upright": True})
                confidences.append(conf)
        quality = "ocr_review_required" if not confidences or sum(confidences) / len(confidences) < 75 else "ocr"
        return words, quality
    finally:
        image.close()
        bitmap.close()
        page.close()
        doc.close()


def _references(workspace, version_id, parse_id=None):
    """Persist actual bibliography entries with source blocks; no invented metadata."""
    from .snapshots import snapshot_blocks
    parse_id = parse_id or version_id
    blocks = snapshot_blocks(workspace, version_id, parse_id)
    in_refs = False
    entries = []
    current = None
    for block in blocks:
        if block["type"] in ("header", "footer", "figure"):
            continue
        text = block["text"]
        if re.match(r"^(?:\d+\s+)?(?:References|Bibliography|参考文献)\s*$", text.strip(), re.I):
            in_refs = True
            continue
        if not in_refs:
            continue
        if re.match(r"^(?:Appendix|\d+\s+Appendix|A\s+[A-Z])", text) and block["type"] == "heading":
            break
        marker = re.match(r"^\[(\d+)\]\s*(.*)", text, re.S)
        if marker:
            if current:
                entries.append(current)
            current = {"marker": marker.group(1), "text": text, "block_id": block["id"], "page_index": block["page_index"], "block_ids": [block["id"]]}
        elif current:
            current["text"] += " " + text
            current["block_ids"].append(block["id"])
        elif len(text) > 40:
            # Author-year bibliography: each parsed paragraph is a conservative raw entry.
            entries.append({"marker": "", "text": text, "block_id": block["id"], "page_index": block["page_index"], "block_ids": [block["id"]]})
    if current:
        entries.append(current)
    with db() as conn:
        conn.execute("DELETE FROM refs WHERE workspace=? AND version_id=? AND COALESCE(json_extract(metadata,'$.parse_id'),version_id)=?", (workspace, version_id, parse_id))
        for idx, entry in enumerate(entries):
            arxiv = re.search(r"(?:arXiv:|arxiv.org/(?:abs|pdf)/)\s*(\d{4}\.\d{4,5})", entry["text"], re.I)
            doi = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", entry["text"], re.I)
            identity = "arxiv:" + arxiv.group(1) if arxiv else "doi:" + doi.group(0).rstrip(".,;").lower() if doi else None
            conn.execute("INSERT INTO refs VALUES(?,?,?,?,?,?,?,?,?)", (f"{parse_id}:ref:{idx}", workspace, version_id, entry["block_id"], entry["page_index"], entry["marker"], entry["text"], identity, _json({"block_ids": entry["block_ids"], "match_status": "raw_bibliography", "parse_id": parse_id})))
    return len(entries)


def _suppress_repeating_margins(workspace, version_id, page_count, parse_id=None):
    candidates = []
    occurrences = {}
    from .snapshots import snapshot_blocks
    for block in snapshot_blocks(workspace, version_id, parse_id or version_id):
        if not 0 < len(block['text']) < 140:
            continue
        box = json.loads(block["bbox"])
        if box[1] > .08 and box[3] < .92:
            continue
        fingerprint = re.sub(r"\d+", "#", _normalized(block["text"]))
        occurrences.setdefault(fingerprint, set()).add(block["page_index"])
        candidates.append((block, box, fingerprint))
    removed = 0
    with db() as conn:
        for block, box, fingerprint in candidates:
            page_number = bool(re.fullmatch(r"\s*(?:\d{1,5}|[ivxlcdm]{1,7})\s*", block["text"], re.I))
            repeated = page_count >= 3 and len(occurrences[fingerprint]) >= max(3, page_count * .55)
            if page_number or repeated:
                metadata = json.loads(block["metadata"])
                metadata["excluded_from_index"] = "printed_page_label" if page_number else "repeating_margin"
                conn.execute("UPDATE blocks SET type=?,metadata=? WHERE id=?", ("header" if box[1] < .08 else "footer", _json(metadata), block["id"]))
                conn.execute("DELETE FROM block_fts WHERE id=?", (block["id"],))
                removed += 1
    return removed



def _stop_parse_if_needed(conn, workspace, version_id, parse_id, run_id, legacy):
    """Caller holds the writer transaction, so delete/cancel cannot race publication."""
    state = conn.execute('SELECT r.status,v.deleted FROM runs r JOIN versions v ON v.id=? WHERE r.id=? AND r.workspace=? AND v.workspace=?',
                         (version_id,run_id,workspace,workspace)).fetchone()
    if state and not state['deleted'] and state['status'] != 'cancelled':
        return False
    conn.execute("UPDATE parses SET status='cancelled' WHERE id=?", (parse_id,))
    conn.execute("UPDATE runs SET status='cancelled',updated=? WHERE id=?", (time.time(),run_id))
    if legacy:
        conn.execute("UPDATE versions SET status='partial' WHERE id=? AND deleted=0",(version_id,))
    return True


def parse_document(run):
    payload = json.loads(run["payload"]) if isinstance(run["payload"], str) else run["payload"]
    version_id = payload["version_id"]
    workspace = run["workspace"]
    version = one("SELECT * FROM versions WHERE id=? AND workspace=? AND deleted=0", (version_id, workspace))
    if not version:
        raise ValueError("文档不存在或已删除")
    if version["parsed_pages"] == 0 and one("SELECT id FROM evidence WHERE workspace=? AND version_id=? LIMIT 1", (workspace, version_id)):
        raise ValueError("该解析快照已有历史引用，不能覆盖重建；请创建独立解析修订快照")
    from .snapshots import selected_parse, snapshot_blocks
    parse_id = payload.get('parse_id', version_id)
    revision = selected_parse(workspace, version_id, parse_id)
    engine = payload.get('engine', 'native')
    legacy = parse_id == version_id
    if revision['status'] == 'ready' and revision['parsed_pages'] == revision['page_count']:
        if legacy:
            execute("UPDATE versions SET status='ready' WHERE id=?",(version_id,))
        return {'version_id':version_id,'parse_id':parse_id,'status':'ready','parsed_pages':revision['parsed_pages'],'reused':True}
    execute("UPDATE parses SET status='parsing',error=NULL WHERE id=?", (parse_id,))
    if legacy:
        execute("UPDATE versions SET status='parsing' WHERE id=?", (version_id,))
    event(run["id"], "parse_started", {"tool": "parse_document", "version_id": version_id, "checkpoint_pages": version["parsed_pages"]})
    with pdfplumber.open(version["path"]) as pdf:
        if len(pdf.pages) > MAX_PAGES:
            raise ValueError("PDF 页数超出限制")
        if legacy and version["parsed_pages"] == 0:
            title, identity, label, metadata = _identity(pdf, pdf.pages[0])
            _apply_identity(version, title, identity, label, metadata)
        for page_index in range(len(pdf.pages)):
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                if _stop_parse_if_needed(conn,workspace,version_id,parse_id,run['id'],legacy):
                    saved=conn.execute('SELECT parsed_pages FROM parses WHERE id=?',(parse_id,)).fetchone()[0]
                    return {"version_id":version_id,"parse_id":parse_id,"status":"cancelled","parsed_pages":saved}

            existing_page = one("SELECT status FROM pages WHERE version_id=? AND page_index=?", (version_id,page_index)) if legacy else one("SELECT status FROM parse_pages WHERE parse_id=? AND page_index=?", (parse_id,page_index))
            if existing_page:
                continue
            if legacy and one("SELECT e.id FROM evidence e JOIN blocks b ON b.id=e.block_id WHERE e.workspace=? AND e.version_id=? AND b.page_index=? LIMIT 1", (workspace, version_id, page_index)):
                raise ValueError("该页已有历史引用，禁止覆盖其块标识和位置；请使用独立解析修订快照")
            original_page = pdf.pages[page_index]
            page = original_page.crop(original_page.cropbox) if original_page.cropbox != original_page.mediabox else original_page
            width, height = float(page.width), float(page.height)
            origin_x, origin_y = page.bbox[:2]
            words = page.extract_words(extra_attrs=["size"], use_text_flow=False, x_tolerance=1.1, y_tolerance=2.5)
            rotated_text = page.rotation in (90, 270) and words and sum(not w.get("upright", True) for w in words) > len(words) * .65
            if rotated_text:
                words = page.extract_words(line_dir_rotated="rtl" if page.rotation == 90 else "ltr", char_dir_rotated="ttb" if page.rotation == 90 else "btt")
            words = [{**w, "x0": w["x0"] - origin_x, "x1": w["x1"] - origin_x, "top": w["top"] - origin_y, "bottom": w["bottom"] - origin_y} for w in words]
            native_text = " ".join(w["text"] for w in words)
            blank_page = engine == 'native' and not native_text.strip() and _is_blank_page(page,version['path'],page_index)
            quality, source = "native", "pdfplumber"
            provenance = {'engine':'native','version':PARSER_VERSION,'device':'cpu'}
            if engine in ('paddleocr','paddleocr_vl','mineru'):
                from .enhanced_parsing import external_page, paddle_words, mineru_blocks
                provenance = external_page(version['path'],page_index,engine,device=payload.get('device','cpu'),run_id=run['id'])
                if engine == 'paddleocr':
                    words, quality = paddle_words(provenance,width,height)
                    blocks = _make_blocks(words,width,height,version_id,page_index,engine,quality)
                else:
                    blocks = mineru_blocks(provenance,version_id,page_index)
                    quality = 'ocr_review_required'
                source = engine
            else:
                if len(re.sub(r"\s", "", native_text)) < 25 and not blank_page:
                    words, quality = _ocr_words(version["path"], page_index)
                    source = "tesseract" if words else "none"
                blocks = _make_rotated_blocks(words, width, height, version_id, page_index, page.rotation) if rotated_text and source == "pdfplumber" else _make_blocks(words, width, height, version_id, page_index, source, quality)
            for i,block in enumerate(blocks):
                block['id'] = f'{parse_id}:{page_index}:{i}'
                block['metadata'].update(parse_id=parse_id,parser_version=provenance.get('version'),models=provenance.get('models',[]),device=provenance.get('device','cpu'))
            # Retain image/table source regions even if reconstruction is unavailable.
            for image in (page.images if engine == 'native' else []):
                bbox = [max(0, (image["x0"] - origin_x) / width), max(0, (image["top"] - origin_y) / height), min(1, (image["x1"] - origin_x) / width), min(1, (image["bottom"] - origin_y) / height)]
                if (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) < .005:
                    continue
                blocks.append({"id": f"{parse_id}:{page_index}:{len(blocks)}", "version_id": version_id, "page_index": page_index, "bbox": bbox, "type": "figure", "reading_order": len(blocks), "text": "", "source": "pdfplumber_region", "quality": "source_region_only", "metadata": {"reconstruction": "原图区域；无可靠结构化重建"}})
            try:
                tables = page.find_tables() if engine == 'native' else []
                for table in tables[:20]:
                    cells = table.extract()
                    text = "\n".join(" | ".join(c or "" for c in row) for row in cells)
                    if len(text.strip()) > 15:
                        blocks.append({"id": f"{parse_id}:{page_index}:{len(blocks)}", "version_id": version_id, "page_index": page_index, "bbox": [(table.bbox[0] - origin_x) / width, (table.bbox[1] - origin_y) / height, (table.bbox[2] - origin_x) / width, (table.bbox[3] - origin_y) / height], "type": "table", "reading_order": len(blocks), "text": text, "source": "pdfplumber_table", "quality": "table_review_required", "metadata": {"cells": cells, "reconstruction": "需与原图核对"}})
            except (ValueError, TypeError):
                pass
            text = "\n".join(b["text"] for b in blocks if b["text"])
            status = "ready" if quality == "native" else quality
            if not text.strip():
                status = "blank" if blank_page else "ocr_unavailable" if quality == "ocr_unavailable" else "empty_or_failed"
            # Printed page number is evidence-based; physical index always remains separate.
            label = None
            bottom_words = [w for w in words if w["top"] > height * .9 and re.fullmatch(r"\d{1,5}|[ivxlcdm]{1,8}", w["text"], re.I)]
            if len(bottom_words) == 1:
                label = bottom_words[0]["text"]
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                if _stop_parse_if_needed(conn,workspace,version_id,parse_id,run['id'],legacy):
                    saved=conn.execute('SELECT parsed_pages FROM parses WHERE id=?',(parse_id,)).fetchone()[0]
                    return {"version_id":version_id,"parse_id":parse_id,"status":"cancelled","parsed_pages":saved}
                # All committed pages, including failed/empty ones, are immutable.
                old = conn.execute("SELECT b.id FROM blocks b LEFT JOIN block_parses m ON m.block_id=b.id WHERE b.version_id=? AND b.page_index=? AND COALESCE(m.parse_id,b.version_id)=?", (version_id,page_index,parse_id)).fetchall()
                if old:
                    raise ValueError('解析页已持久化；不能覆盖已有块，请创建新快照')
                if legacy:
                    conn.execute("INSERT OR REPLACE INTO pages VALUES(?,?,?,?,?,?,?,?)", (version_id, page_index, label, width, height, int(page.rotation or 0), status, text))
                else:
                    conn.execute("INSERT INTO parse_pages VALUES(?,?,?,?,?,?,?,?,?)", (parse_id,version_id,page_index,label,width,height,int(page.rotation or 0),status,text))
                for block in blocks:
                    conn.execute("INSERT INTO blocks VALUES(?,?,?,?,?,?,?,?,?,?,?)", (block["id"], workspace, version_id, page_index, _json(block["bbox"]), block["type"], block["reading_order"], block["text"], block["source"], block["quality"], _json(block["metadata"])))
                    if not legacy:
                        conn.execute("INSERT INTO block_parses VALUES(?,?)",(block["id"],parse_id))
                    if block["text"]:
                        index_text = block["text"]
                        symbols = re.sub(r"([βγδε])\s+(\d+)", r"\1\2", index_text)
                        if symbols != index_text:
                            index_text += "\n" + symbols
                        conn.execute("INSERT INTO block_fts(id,text) VALUES(?,?)", (block["id"], index_text))
                committed_pages = conn.execute("SELECT count(*) FROM pages WHERE version_id=?", (version_id,)).fetchone()[0] if legacy else conn.execute("SELECT count(*) FROM parse_pages WHERE parse_id=?",(parse_id,)).fetchone()[0]
                safe_provenance = {k:provenance[k] for k in ('engine','version','models','device') if k in provenance}
                prior=json.loads(conn.execute('SELECT provenance FROM parses WHERE id=?',(parse_id,)).fetchone()[0])
                if prior and prior != safe_provenance:
                    raise ValueError('解析器版本、模型或设备已变化；请创建新快照，已有页面保持不变')
                conn.execute("UPDATE parses SET parsed_pages=?,provenance=? WHERE id=?",(committed_pages,_json(safe_provenance),parse_id))
                if legacy:
                    conn.execute("UPDATE versions SET parsed_pages=?,page_count=? WHERE id=?", (committed_pages, len(pdf.pages), version_id))
                conn.execute("UPDATE runs SET checkpoint=?,updated=? WHERE id=?", (_json({"parsed_pages": committed_pages}), time.time(), run["id"]))
            event(run["id"], "page_indexed", {"tool": "parse_document", "page_index": page_index, "parsed_pages": committed_pages, "page_count": len(pdf.pages), "blocks": len(blocks), "quality": quality, "source": source})
            page.close()
            if page is not original_page:
                original_page.close()
    with db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if _stop_parse_if_needed(conn,workspace,version_id,parse_id,run['id'],legacy):
            saved=conn.execute('SELECT parsed_pages FROM parses WHERE id=?',(parse_id,)).fetchone()[0]
            return {"version_id":version_id,"parse_id":parse_id,"status":"cancelled","parsed_pages":saved}
    margins = _suppress_repeating_margins(workspace,version_id,version['page_count'],parse_id)
    ref_count = _references(workspace,version_id,parse_id)
    parsed_blocks = snapshot_blocks(workspace,version_id,parse_id)
    headings = [b for b in parsed_blocks if b['type']=='heading']
    outline = [{"title":h['text'],"page_index":h['page_index'],"block_id":h['id']} for h in headings]
    pages = rows('SELECT page_index,status FROM pages WHERE version_id=?',(version_id,)) if legacy else rows('SELECT page_index,status FROM parse_pages WHERE parse_id=?',(parse_id,))
    failures = [p for p in pages if p['status'] not in ('ready','ocr','ocr_review_required','blank')]
    status = 'partial' if failures else 'ready'
    with db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if _stop_parse_if_needed(conn,workspace,version_id,parse_id,run['id'],legacy):
            return {"version_id":version_id,"parse_id":parse_id,"status":"cancelled","parsed_pages":len(pages)}
        current_meta=json.loads(conn.execute('SELECT metadata FROM versions WHERE id=?',(version_id,)).fetchone()[0])
        conn.execute('UPDATE parses SET status=? WHERE id=?',(status,parse_id))
        if status=='ready':
            conn.execute('INSERT OR REPLACE INTO active_parses VALUES(?,?)',(version_id,parse_id))
            if not current_meta.get('outline_manual') or not legacy:
                current_meta['outline']=outline
            current_meta['active_parse_id']=parse_id
            conn.execute('UPDATE versions SET status=?,parsed_pages=?,dense_pages=?,metadata=? WHERE id=?',(status,len(pages),version['dense_pages'] if legacy else 0,_json(current_meta),version_id))
        elif legacy:
            conn.execute('UPDATE versions SET status=? WHERE id=?',(status,version_id))
    result = {'version_id':version_id,'parse_id':parse_id,'status':status,'parsed_pages':len(pages),'references':ref_count,'failed_pages':failures,'suppressed_margin_blocks':margins}
    if status=='ready' and not cancelled(run["id"]) and os.getenv('RT_DOCUMENT_CARDS','true').lower()=='true':
        # Structured metadata is an enhancement: a failure never changes the parse result.
        try:
            from .cards import build_card
            card = build_card(workspace, version_id, run["id"],
                              use_network=os.getenv('RT_CARD_NETWORK','true').lower()=='true',
                              use_model=os.getenv('RT_CARD_MODEL','true').lower()=='true')
            result["document_card"] = {"title_source": card["title"]["source"], "authors": len(card.get("authors", []))}
        except Exception as exc:
            result["document_card"] = {"status": "unavailable", "reason": type(exc).__name__}
            event(run["id"], "document_card_failed", {"reason": type(exc).__name__})
    if legacy and payload.get('index_dense',True) and not cancelled(run["id"]):
        try:
            from .retrieval import index_dense
            result["dense_index"] = index_dense(workspace, version_id, run["id"])
        except Exception as exc:
            # Safe category only; upstream exception content may contain a URL/key.
            result["dense_index"] = {"status": "unavailable", "reason": type(exc).__name__}
            event(run["id"], "dense_unavailable", {"reason": type(exc).__name__, "mode": "关键词检索仍可用"})
    return result


def compare_versions(workspace, left, right):
    versions = [one("SELECT * FROM versions WHERE workspace=? AND id=? AND deleted=0", (workspace, v)) for v in (left, right)]
    if not all(versions):
        raise ValueError("版本不存在或不属于当前工作区")
    a = [_decode(b) for b in rows("SELECT * FROM current_blocks WHERE workspace=? AND version_id=? AND type NOT IN ('figure') ORDER BY page_index,reading_order", (workspace, left))]
    b = [_decode(x) for x in rows("SELECT * FROM current_blocks WHERE workspace=? AND version_id=? AND type NOT IN ('figure') ORDER BY page_index,reading_order", (workspace, right))]
    matcher = difflib.SequenceMatcher(None, [_normalized(x["text"]) for x in a], [_normalized(x["text"]) for x in b], autojunk=False)
    changes = []
    counts = {"added": 0, "deleted": 0, "modified": 0, "unchanged": 0}
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            counts["unchanged"] += i2 - i1
            continue
        kind = {"replace": "modified", "delete": "deleted", "insert": "added"}[op]
        counts[kind] += max(i2 - i1, j2 - j1)
        for index in range(max(i2 - i1, j2 - j1)):
            changes.append({"kind": kind, "before": a[i1 + index] if i1 + index < i2 else None, "after": b[j1 + index] if j1 + index < j2 else None})
    return {"left": _decode(versions[0]), "right": _decode(versions[1]), "changes": changes, "counts": counts, "method": "normalized_paragraph_sequence_diff", "same_work": versions[0]["work_id"] == versions[1]["work_id"], "notice": "确定性段落差异；排版变动也可能形成修改。旧引用保持原版本。"}
