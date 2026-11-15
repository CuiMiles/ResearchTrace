"""Actual FTS5 + provider dense retrieval, with per-workspace immutable version scope."""
import json
import os
import re
import time

import numpy as np

from .store import cancelled, db, event, one, rows


def _decode(block):
    block = dict(block)
    for key in ("bbox", "metadata"):
        if isinstance(block.get(key), str):
            block[key] = json.loads(block[key])
    block.pop("workspace", None)
    return block


def index_dense(workspace, version_id, run_id):
    if os.environ.get("ENABLE_DENSE", "true").lower() == "false" or os.environ.get("RT_DISABLE_DENSE", "false").lower() == "true":
        return {"status": "disabled", "model": None, "dense_pages": 0, "notice": "密集索引已关闭；仅使用关键词检索"}
    from .models import embed
    version = one("SELECT * FROM versions WHERE workspace=? AND id=? AND deleted=0", (workspace, version_id))
    if not version:
        raise ValueError("文档不存在")
    model = os.environ.get("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    blocks = rows("SELECT b.* FROM current_blocks b WHERE b.workspace=? AND b.version_id=? AND length(b.text)>10 AND b.type NOT IN ('header','footer') AND NOT EXISTS(SELECT 1 FROM embeddings e WHERE e.block_id=b.id AND e.model=?) ORDER BY b.page_index,b.reading_order", (workspace, version_id, model))
    completed = 0
    # Bound by the adapter's conservative UTF-8-byte input reservation, not only count.
    batches = []
    current = []
    byte_budget = 0
    for block in blocks:
        text = block["text"][:5000]
        size = len(text.encode("utf-8"))
        if current and (len(current) >= 16 or byte_budget + size > 24000):
            batches.append(current)
            current, byte_budget = [], 0
        current.append(block)
        byte_budget += size
    if current:
        batches.append(current)
    for batch in batches:
        if cancelled(run_id):
            break
        waited = 0
        while True:
            try:
                response = embed([b["text"][:5000] for b in batch], run_id, task="RETRIEVAL_DOCUMENT")
                break
            except Exception as exc:
                # Only a locally rejected reservation can be safely waited/retried.
                # No actual failed HTTP call is repeated here.
                if "分钟额度/并发预算不足" not in str(exc) or waited >= 70:
                    raise
                if cancelled(run_id):
                    return {"status": "cancelled", "new_blocks": completed, "model": model}
                if waited == 0:
                    event(run_id, "dense_quota_wait", {"model": model, "reason": "等待项目级分钟窗口，不重复上游请求"})
                time.sleep(5)
                waited += 5
        actual_model = response["model"].removeprefix("models/")
        vectors = response["vectors"]
        if len(vectors) != len(batch):
            raise ValueError("embedding response count mismatch")
        with db() as conn:
            for block, vector in zip(batch, vectors, strict=True):
                array = np.asarray(vector, dtype=np.float32)
                if array.ndim != 1 or len(array) < 1 or not np.isfinite(array).all():
                    raise ValueError("invalid embedding vector")
                conn.execute("INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?,?,?)", (block["id"], workspace, version_id, actual_model, len(array), array.tobytes()))
            covered = conn.execute("SELECT count(*) FROM current_pages p WHERE p.version_id=? AND p.status IN ('ready','ocr','ocr_review_required') AND NOT EXISTS(SELECT 1 FROM current_blocks b WHERE b.version_id=p.version_id AND b.page_index=p.page_index AND length(b.text)>10 AND b.type NOT IN ('header','footer') AND NOT EXISTS(SELECT 1 FROM embeddings e WHERE e.block_id=b.id AND e.model=?))", (version_id, actual_model)).fetchone()[0]
            conn.execute("UPDATE versions SET dense_pages=? WHERE id=?", (covered, version_id))
        completed += len(batch)
        event(run_id, "dense_batch_indexed", {"tool": "embed_document", "model": actual_model, "dimension": response["dimension"], "blocks": completed, "dense_pages": covered, "page_count": version["page_count"]})
    return {"status": "complete" if completed == len(blocks) else "partial", "new_blocks": completed, "model": model, "dense_pages": one("SELECT dense_pages FROM versions WHERE id=?", (version_id,))["dense_pages"]}


def retrieve(workspace, version_ids, question, limit=16):
    limit = min(max(int(limit), 1), 50)
    if not version_ids:
        return {"blocks": [], "sparse": [], "dense": [], "mode": "keyword", "notice": "请选择文档版本"}
    requested = list(dict.fromkeys(version_ids))
    placeholders = ",".join("?" for _ in requested)
    allowed = rows(f"SELECT id FROM versions WHERE workspace=? AND deleted=0 AND id IN ({placeholders})", (workspace, *requested))
    if len(allowed) != len(requested):
        raise ValueError("检索版本不存在或不属于当前工作区")
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]*|[βγδε]\s*\d*|\d+(?:\.\d+)?|[\u4e00-\u9fff]+", question, re.UNICODE)
    # Chinese segmentation supports meaningful local keyword search without pretending it is semantic.
    expanded = []
    for token in tokens:
        if re.search(r"[\u4e00-\u9fff]", token) and len(token) > 3:
            expanded.extend(token[i:i + 2] for i in range(len(token) - 1))
        else:
            expanded.append(re.sub(r"\s+", "", token))
    # PDF text can separate β and its subscript; retrieve the source context
    # while preserving the actual quote and symbol values for verification.
    for token in list(expanded):
        if re.fullmatch(r"[βγδε]\d+", token):
            expanded.append(token[0])
    query = " OR ".join('"' + t.replace('"', '""') + '"' + ('*' if re.fullmatch(r"[A-Za-z]{3,}", t) else '') for t in expanded[:40] if len(t) > 1 or t in ("β", "γ", "δ"))
    sparse = []
    if query:
        sparse = rows(f"SELECT b.*,bm25(block_fts) AS sparse_score FROM block_fts JOIN current_blocks b ON b.id=block_fts.id JOIN versions v ON v.id=b.version_id WHERE block_fts MATCH ? AND b.workspace=? AND b.version_id IN ({placeholders}) AND v.deleted=0 ORDER BY sparse_score LIMIT ?", (query, workspace, *requested, limit * 3))
    dense = []
    notice = "当前使用关键词检索；密集索引未配置或未完成"
    model = os.environ.get("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    dense_rows = rows(f"SELECT e.block_id,e.model,e.dimension,e.vector FROM embeddings e JOIN current_blocks cb ON cb.id=e.block_id JOIN versions v ON v.id=e.version_id WHERE e.workspace=? AND e.version_id IN ({placeholders}) AND v.deleted=0 AND e.model=?", (workspace, *requested, model))
    if dense_rows and os.environ.get("RT_DISABLE_DENSE", "false").lower() != "true":
        try:
            from .models import embed
            response = embed([question], "retrieval-query", task="RETRIEVAL_QUERY")
            vector = np.asarray(response["vectors"][0], dtype=np.float32)
            actual_model = response["model"].removeprefix("models/")
            norms = float(np.linalg.norm(vector))
            scored = []
            for row in dense_rows:
                if row["dimension"] != len(vector) or row["model"] != actual_model:
                    continue
                candidate = np.frombuffer(row["vector"], dtype=np.float32)
                score = float(np.dot(vector, candidate) / max(norms * np.linalg.norm(candidate), 1e-9))
                scored.append((row["block_id"], score))
            scored.sort(key=lambda x: x[1], reverse=True)
            for block_id, score in scored[:limit * 3]:
                block = one("SELECT * FROM current_blocks WHERE id=? AND workspace=?", (block_id, workspace))
                if block:
                    dense.append({**block, "dense_score": score})
            notice = "FTS5 与真实 embedding 余弦候选经 RRF 合并；覆盖率见版本详情"
        except Exception as exc:
            notice = "密集查询不可用（" + type(exc).__name__ + "）；当前使用关键词检索"
    by_id = {}
    scores = {}
    for candidates in (sparse, dense):
        for rank, block in enumerate(candidates):
            by_id[block["id"]] = block
            scores[block["id"]] = scores.get(block["id"], 0) + 1 / (60 + rank + 1)
    picked = sorted(scores, key=scores.get, reverse=True)[:limit]
    blocks = [{**_decode(by_id[k]), "rrf_score": scores[k]} for k in picked]
    # Adjacent blocks recover table headers/conditions without changing evidence identities.
    added = set(picked)
    for item in blocks[:max(1, limit // 3)]:
        neighbors = rows("SELECT * FROM current_blocks WHERE workspace=? AND version_id=? AND page_index=? AND reading_order BETWEEN ? AND ? AND length(text)>0 ORDER BY reading_order", (workspace, item["version_id"], item["page_index"], item["reading_order"] - 1, item["reading_order"] + 1))
        for neighbor in neighbors:
            if neighbor["id"] not in added and len(blocks) < limit + 6:
                blocks.append({**_decode(neighbor), "neighbor_context": True})
                added.add(neighbor["id"])
    return {"blocks": blocks, "sparse": [{"block_id": b["id"], "score": b["sparse_score"]} for b in sparse], "dense": [{"block_id": b["id"], "score": b["dense_score"]} for b in dense], "mode": "hybrid" if dense else "keyword", "notice": notice, "version_ids": requested, "method": "FTS5_BM25+cosine+RRF" if dense else "FTS5_BM25"}
