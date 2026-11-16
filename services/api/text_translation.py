"""Durable selection translation. No credentials, DDL or provider calls at import.

Main integration: app.include_router(router); dispatch kind='text_translation'
to handle(run) in the interactive pool. No changes to app/jobs/store are needed
in this worktree. The private cache schema is initialized lazily and idempotently.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import time
from collections.abc import Mapping
from contextlib import contextmanager
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import models, store
from . import translation_service as translation

router = APIRouter(prefix="/api/v1/text", tags=["text translation"])
GLOSSARY_VERSION = translation.DEFAULT_GLOSSARY_VERSION
PROMPT_VERSION = "selection-v1:" + translation.PLAN_VERSION
SCHEMA = """CREATE TABLE IF NOT EXISTS text_translation_cache(
    workspace TEXT NOT NULL, cache_key TEXT NOT NULL, context TEXT NOT NULL,
    translation TEXT NOT NULL, model TEXT NOT NULL, created REAL NOT NULL,
    PRIMARY KEY(workspace,cache_key));"""


class TextTranslationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=12000)
    target_language: Literal["en", "zh-Hans"] = "zh-Hans"
    source_language: Literal["auto", "en", "zh"] = "auto"
    idempotency_key: str = Field(min_length=8, max_length=150)
    version_id: str | None = Field(default=None, min_length=1, max_length=150)
    parse_id: str | None = Field(default=None, min_length=1, max_length=150)
    block_id: str | None = Field(default=None, min_length=1, max_length=200)
    page_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_selection(self):
        if not self.text.strip():
            raise ValueError("请选择非空原文")
        if (
            self.parse_id or self.block_id or self.page_index is not None
        ) and not self.version_id:
            raise ValueError("解析快照、段落和物理页必须同时指定版本")
        return self


def authenticated_session(request):
    # Late import avoids an app/router import cycle. The main application keeps
    # ownership of authentication, expiry and reviewer-workspace selection.
    from .app import session

    return session(request)


def session_dependency(request: Request):
    return authenticated_session(request)


def ensure_schema():
    with store.db() as connection:
        connection.execute(SCHEMA)


def _route() -> list[str]:
    return models.role_chain("light")


def _snapshot(connection, workspace, payload, prior=None):
    payload = dict(payload)
    version_id = payload.get("version_id")
    if not version_id:
        return payload
    version = connection.execute(
        "SELECT * FROM versions WHERE id=? AND workspace=? AND deleted=0",
        (version_id, workspace),
    ).fetchone()
    if not version:
        raise HTTPException(404, "文档不存在或无权限")
    active = connection.execute(
        "SELECT parse_id FROM active_parses WHERE version_id=?", (version_id,)
    ).fetchone()
    parse_id = (
        payload.get("parse_id")
        or (prior or {}).get("parse_id")
        or (active["parse_id"] if active else version_id)
    )
    snapshot = connection.execute(
        "SELECT id FROM parses WHERE id=? AND version_id=? AND workspace=?",
        (parse_id, version_id, workspace),
    ).fetchone()
    if not snapshot:
        raise HTTPException(404, "解析快照不存在或无权限")
    payload["parse_id"] = parse_id
    page = payload.get("page_index")
    if page is not None and page >= version["page_count"]:
        raise HTTPException(422, "物理页超出文档范围")
    if payload.get("block_id"):
        block = connection.execute(
            """SELECT b.* FROM blocks b LEFT JOIN block_parses p ON p.block_id=b.id
            WHERE b.id=? AND b.version_id=? AND b.workspace=? AND COALESCE(p.parse_id,b.version_id)=?""",
            (payload["block_id"], version_id, workspace, parse_id),
        ).fetchone()
        if not block:
            raise HTTPException(404, "段落不存在于指定解析快照或无权限")
        from .jobs import canonical_quote

        needle, _ = canonical_quote(payload["text"])
        haystack, _ = canonical_quote(block["text"])
        if (
            not needle
            or needle not in haystack
            or page is not None
            and page != block["page_index"]
        ):
            raise HTTPException(422, "选段或物理页与指定原文段落不一致")
        payload["page_index"] = block["page_index"]
    return payload


@router.post("/translations")
def enqueue(
    request: TextTranslationRequest,
    session: Annotated[dict, Depends(session_dependency)],
):
    workspace = session["workspace"]
    incoming = request.model_dump(exclude={"idempotency_key"}, exclude_none=True)
    with store.db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        old = connection.execute(
            "SELECT * FROM runs WHERE workspace=? AND idempotency=?",
            (workspace, request.idempotency_key),
        ).fetchone()
        prior = json.loads(old["payload"]) if old else None
        payload = _snapshot(connection, workspace, incoming, prior)
        if old:
            if old["kind"] != "text_translation" or prior != payload:
                raise HTTPException(409, "幂等键已用于不同请求")
            return {
                "id": old["id"],
                "run_id": old["id"],
                "status": old["status"],
                "reused": True,
            }
        if (
            connection.execute(
                "SELECT count(*) FROM runs WHERE workspace=? AND status IN ('queued','running')",
                (workspace,),
            ).fetchone()[0]
            >= 6
            or connection.execute(
                "SELECT count(*) FROM runs WHERE status IN ('queued','running')"
            ).fetchone()[0]
            >= 30
        ):
            raise HTTPException(429, "队列已满；请等待或取消已有任务")
        rid, now = store.uid(), time.time()
        connection.execute(
            "INSERT INTO runs(id,workspace,kind,status,payload,idempotency,created,updated) VALUES(?,?,?,?,?,?,?,?)",
            (
                rid,
                workspace,
                "text_translation",
                "queued",
                json.dumps(payload, ensure_ascii=False),
                request.idempotency_key,
                now,
                now,
            ),
        )
    store.event(
        rid,
        "queued",
        {"kind": "text_translation", "message": "选段翻译已持久化，等待翻译执行池"},
    )
    return {"id": rid, "run_id": rid, "status": "queued"}


def _save(run_id, patch):
    with store.db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT checkpoint FROM runs WHERE id=?", (run_id,)
        ).fetchone()
        saved = json.loads(row["checkpoint"] or "{}")
        saved.update(patch)
        connection.execute(
            "UPDATE runs SET checkpoint=?,updated=? WHERE id=?",
            (json.dumps(saved, ensure_ascii=False), time.time(), run_id),
        )


@contextmanager
def _cache_lock(workspace, key):
    directory = store.DATA / "text-translation-locks"
    directory.mkdir(exist_ok=True, mode=0o700)
    # A cache lock covers checking, billing and commit, across worker processes.
    # It is never deleted while other processes might hold the same inode.
    path = directory / (
        hashlib.sha256((workspace + ":" + key).encode()).hexdigest() + ".lock"
    )
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError(
                "相同选段正在翻译；完成后恢复此任务可读取持久缓存"
            ) from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _generate(system, prompt, run_id):
    return models.generate(system, prompt, run_id, role="light", json_output=True)


def handle(run: Mapping[str, Any]) -> dict[str, Any]:
    """Return standard answer/translation. Main worker publishes run status.

    Checkpoint the intent before sending, and every received response before
    validating. Recovery reuses it; it never resends an ambiguous prior call.
    Cache hits still validate workspace and immutable snapshot ownership.
    """
    payload = (
        run["payload"]
        if isinstance(run["payload"], dict)
        else json.loads(run["payload"])
    )
    payload = TextTranslationRequest(
        **payload, idempotency_key="handler-validation"
    ).model_dump(exclude={"idempotency_key"}, exclude_none=True)
    workspace, rid = run["workspace"], run["id"]
    with store.db() as connection:
        payload = _snapshot(connection, workspace, payload)
    if payload.get("version_id") and not payload.get("parse_id"):
        raise ValueError("翻译恢复缺少已固定的解析快照")
    ensure_schema()
    context = {
        "source_language": payload["source_language"],
        "target_language": payload["target_language"],
        "glossary_version": GLOSSARY_VERSION,
        "route": _route(),
        "prompt_version": PROMPT_VERSION,
        "text": payload["text"],
    }
    context_json = json.dumps(context, ensure_ascii=False, sort_keys=True)
    cache_key = hashlib.sha256(context_json.encode()).hexdigest()
    anchor = {
        k: payload[k]
        for k in ("version_id", "parse_id", "block_id", "page_index")
        if k in payload
    }
    anchor.update(
        text_anchor={"exact": payload["text"]},
        precision="text_anchor_not_verified_bbox",
    )

    def result(text="", *, cached=False, actual_model="", cancelled=False):
        return {
            "answer": text,
            "translation": text,
            "source_text": payload["text"],
            "source_language": payload["source_language"],
            "target_language": payload["target_language"],
            "glossary_version": GLOSSARY_VERSION,
            "model": actual_model,
            "cache_hit": cached,
            "anchor": anchor,
            "integrity": "protected_spans_verified" if text else "not_completed",
            **({"cancelled": True} if cancelled else {}),
        }

    if store.cancelled(rid):
        return result(cancelled=True)
    with _cache_lock(workspace, cache_key):
        cached = store.one(
            "SELECT * FROM text_translation_cache WHERE workspace=? AND cache_key=?",
            (workspace, cache_key),
        )
        if cached:
            store.event(
                rid, "translation_cache", {"cache_hit": True, "model": cached["model"]}
            )
            return result(
                cached["translation"], cached=True, actual_model=cached["model"]
            )
        saved = json.loads(
            store.one("SELECT checkpoint FROM runs WHERE id=?", (rid,))["checkpoint"]
            or "{}"
        )
        if saved.get("text_translation_context", context) != context:
            raise ValueError("恢复时翻译模型、术语或原文已改变；请新建任务")
        _save(rid, {"text_translation_context": context})
        system = translation.translation_system(
            payload["source_language"], payload["target_language"], GLOSSARY_VERSION
        )
        block = {"id": "selection", "type": "paragraph", "text": payload["text"]}
        segments = translation._segments(
            block, system, translation.DEFAULT_INPUT_TOKEN_BUDGET
        )
        batches = translation.plan_batches(segments, system)
        responses = dict(saved.get("text_translation_responses", {}))
        outputs, actual_models = {}, set()
        for index, batch in enumerate(batches):
            if store.cancelled(rid):
                return result(cancelled=True)
            batch_key = str(index)
            response = responses.get(batch_key)
            if batch_key not in responses:
                if saved.get("text_translation_intent") == batch_key:
                    raise ValueError(
                        "上次选段翻译请求已尝试但结果未知，禁止自动重发；请核对调用账本"
                    )
                _save(rid, {"text_translation_intent": batch_key})
                try:
                    response = _generate(
                        system,
                        json.dumps([part.item for part in batch], ensure_ascii=False),
                        rid,
                    )
                except models.QuotaRefusal:
                    _save(
                        rid, {"text_translation_intent": None}
                    )  # definite local refusal, unsent
                    raise
                responses[batch_key] = response
                _save(
                    rid,
                    {
                        "text_translation_responses": responses,
                        "text_translation_intent": None,
                    },
                )
            if store.cancelled(rid):
                return result(cancelled=True)
            if not isinstance(response, Mapping):
                raise TypeError("选段翻译返回非结构化响应；已保存接收记录，不自动重发")
            raw = response.get("text")
            if (
                not isinstance(raw, str)
                or len(raw.encode()) > translation.MAX_RESPONSE_BYTES
            ):
                raise ValueError("选段翻译返回无效或超出响应预算")
            data = json.loads(raw)
            items = data.get("translations") if isinstance(data, dict) else None
            expected = {part.request_id for part in batch}
            if (
                not isinstance(items, list)
                or len(items) != len(expected)
                or any(
                    not isinstance(item, dict)
                    or not isinstance(item.get("block_id"), str)
                    or not isinstance(item.get("text"), str)
                    or not item["text"].strip()
                    for item in items
                )
                or {item["block_id"] for item in items} != expected
            ):
                raise ValueError("选段翻译返回缺段、重段或空段；未发布")
            actual_model = response.get("model")
            if not isinstance(actual_model, str) or not actual_model:
                raise ValueError("选段翻译缺少实际模型标识")
            actual_models.add(actual_model)
            by_id = {item["block_id"]: item["text"] for item in items}
            for part in batch:
                text = translation._aligned_whitespace(
                    part.text, by_id[part.request_id]
                )
                translation.restore_protected(text, part.plan)
                outputs[part.request_id] = text
            store.event(
                rid,
                "translation_progress",
                {
                    "completed_batches": index + 1,
                    "total_batches": len(batches),
                    "model": actual_model,
                },
            )
        translated = translation.restore_protected(
            "".join(outputs[part.request_id] for part in segments),
            translation.protect_text(payload["text"]),
        )
        actual_model = ", ".join(sorted(actual_models))
        with store.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM runs WHERE id=? AND workspace=?", (rid, workspace)
            ).fetchone()
            if not row or row["status"] == "cancelled":
                return result(cancelled=True)
            # Revalidate deletion/snapshot access after the potentially long call.
            _snapshot(connection, workspace, payload)
            connection.execute(
                "INSERT OR IGNORE INTO text_translation_cache VALUES(?,?,?,?,?,?)",
                (
                    workspace,
                    cache_key,
                    context_json,
                    translated,
                    actual_model,
                    time.time(),
                ),
            )
        return result(translated, actual_model=actual_model)


# Explicit alias for the main job registry.
run_text_translation = handle
