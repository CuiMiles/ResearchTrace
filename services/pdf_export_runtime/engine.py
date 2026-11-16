"""The real high-level entry. Called only by the owned child process."""
from __future__ import annotations

import asyncio
import importlib.metadata
import logging
import os
import platform
import resource
import socket
import time
import traceback
from pathlib import Path
from urllib.parse import urlsplit

from .callback import build_translator
from .contract import ContractError, ExportJob, sha256_file, write_private_json

VERSIONS = {"pdf2zh-next": "2.10.2", "babeldoc": "0.7.1"}


def event(job: ExportJob, kind: str, **fields):
    import json
    record = {"time_unix": time.time(), "job_id": job.job_id, "type": kind, **fields}
    with (job.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def restrict_network(callback_url: str):
    """Defense in depth: runtime assets are offline; only this callback can connect."""
    parsed = urlsplit(callback_url)
    allowed = (parsed.hostname, parsed.port)
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def check(address):
        if not isinstance(address, tuple) or len(address) < 2 or address[:2] != allowed:
            raise PermissionError("runtime_network_denied")

    def connect(sock, address):
        check(address)
        return original_connect(sock, address)

    def connect_ex(sock, address):
        check(address)
        return original_connect_ex(sock, address)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex


def verify_assets(root: Path) -> dict:
    import json
    lock_path = root / "assets/assets.lock.json"
    if not lock_path.is_file():
        raise ContractError("assets_not_provisioned")
    lock = json.loads(lock_path.read_text())
    pinned_lock = Path(__file__).with_name("assets.lock.json")
    if not pinned_lock.is_file() or sha256_file(pinned_lock) != sha256_file(lock_path):
        raise ContractError("asset_lock_differs_from_pinned_release")
    if lock.get("engine_versions") != VERSIONS or not lock.get("files"):
        raise ContractError("asset_lock_incompatible")
    for entry in lock["files"]:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ContractError("invalid_asset_lock")
        path = root / "assets" / relative
        if path.is_symlink() or not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise ContractError("asset_hash_mismatch")
    return {"lock_sha256": sha256_file(lock_path), "file_count": len(lock["files"]),
            "total_bytes": sum(x["bytes"] for x in lock["files"])}


def settings_for_job(job, start, end):
    from pdf2zh_next.config.model import SettingsModel
    # This validation-only engine descriptor never constructs an Ollama client.
    # Both factories are replaced before create_babeldoc_config can call them.
    return SettingsModel.model_validate({
        "basic": {"debug": True},
        "translation": {"lang_in": job.source_lang, "lang_out": layout_language(job.target_lang),
            "output": str(job.directory / "output"), "qps": job.qps, "pool_max_workers": job.pool,
            "term_qps": job.qps, "term_pool_max_workers": job.pool, "ignore_cache": True,
            "no_auto_extract_glossary": True, "save_auto_extracted_glossary": False},
        "pdf": {"pages": f"{start}-{end}", "only_include_translated_page": True,
            "no_dual": False, "no_mono": False, "translate_table_text": False,
            "auto_enable_ocr_workaround": False, "ocr_workaround": False,
            "use_alternating_pages_dual": True, "watermark_output_mode": "no_watermark"},
        "translate_engine_settings": {"translate_engine_type": "Ollama", "ollama_model": "callback-only-NOT-A-PROVIDER",
            "ollama_host": job.callback_url, "support_llm": "no"},
    })


def layout_language(language: str) -> str:
    # BabelDOC 0.7.1 checks 'CN' rather than 'ZH' to choose Simplified Chinese
    # fonts. Keep the callback's original language unchanged.
    return "zh-CN" if language in {"zh", "zh-Hans"} else language


async def translate_job(job: ExportJob, max_pages: int) -> dict:
    # Mute third-party Python and C stdout/stderr: debug logs may include document
    # paragraphs, prompts and responses. Only explicitly filtered events survive.
    logging.disable(logging.CRITICAL)
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 1)
    os.dup2(null, 2)
    os.close(null)
    started = time.time()
    event(job, "engine_start", callback_label=job.callback_label, mode=job.mode)
    try:
        installed = {name: importlib.metadata.version(name) for name in VERSIONS}
        if installed != VERSIONS:
            raise ContractError("engine_version_mismatch")
        asset_summary = verify_assets(job.root)
        restrict_network(job.callback_url)
        # Pin SQLite's native dependencies before PyMuPDF/ONNX load their libs.
        # BabelDOC's import-time empty cache stays under this job's HOME, while
        # asset functions use the separately immutable, verified asset folder.
        import sqlite3
        import babeldoc.const as babel_const
        import babeldoc.translator.cache
        babel_const.CACHE_FOLDER = job.root / "assets/babeldoc"
        babel_const.TIKTOKEN_CACHE_FOLDER = babel_const.CACHE_FOLDER / "tiktoken"
        os.environ["TIKTOKEN_CACHE_DIR"] = str(babel_const.TIKTOKEN_CACHE_FOLDER)
        import pymupdf
        with pymupdf.open(job.input_pdf) as document:
            if document.needs_pass:
                raise ContractError("encrypted_pdf_rejected")
            total_pages = len(document)
        start, end = job.page_selection(total_pages, max_pages)
        selected = end - start + 1
        event(job, "source_verified", source_sha256=job.input_sha256, document_pages=total_pages,
              selected_pages={"start": start, "end": end}, preview=job.mode == "preview")
        import pdf2zh_next.high_level as high_level
        from pdf2zh_next.high_level import do_translate_async_stream
        import onnxruntime
        original_session = onnxruntime.InferenceSession

        def cpu_session(*args, **kwargs):
            options = kwargs.pop("sess_options", None) or onnxruntime.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            kwargs["sess_options"] = options
            kwargs["providers"] = ["CPUExecutionProvider"]
            return original_session(*args, **kwargs)

        onnxruntime.InferenceSession = cpu_session
        translator = build_translator(job)
        high_level.get_translator = lambda settings: translator
        high_level.get_term_translator = lambda settings: translator
        original_create = high_level.create_babeldoc_config

        def create(settings, file):
            config = original_create(settings, file)
            config.disable_same_text_fallback = True
            config.auto_extract_glossary = False
            config.save_auto_extracted_glossary = False
            config.use_rich_pbar = False
            # basic.debug selects the high-level in-process entry. BabelDOC's
            # own debug flag would add overlays and decompressed duplicate PDFs.
            config.debug = False
            return config

        high_level.create_babeldoc_config = create
        settings = settings_for_job(job, start, end)
        finished = False
        translate_result = None
        from babeldoc.format.pdf.high_level import TRANSLATE_STAGES
        allowed_stages = {name for name, _ in TRANSLATE_STAGES}
        # A second config is deliberately avoided (ONNX can be large).
        async for item in do_translate_async_stream(settings, job.input_pdf):
            kind = item.get("type")
            if kind == "error":
                raise RuntimeError("engine_error_event")
            if kind in {"progress_start", "progress_update", "progress_end"}:
                # Stages are fixed by the pinned engine, never paragraph text.
                stage = item.get("stage", "")
                if stage not in allowed_stages:
                    stage = "engine-stage"
                numeric = {k: v for k in ("stage_progress", "stage_current", "stage_total", "overall_progress")
                           if type(v := item.get(k)) in (int, float)}
                event(job, kind, stage=stage, **numeric)
            if kind == "finish":
                finished = True
                translate_result = item.get("translate_result")
                break
        if not finished or translator.failed or translator.callback_posts + translator.translate_cache_call_count == 0:
            raise RuntimeError("engine_did_not_complete_callback_chain")
        output = job.directory / "output"
        artifacts = []
        for role in ("mono", "dual"):
            result_path = getattr(translate_result, f"{role}_pdf_path", None)
            if not result_path:
                raise RuntimeError("engine_pdf_artifact_missing")
            path = Path(result_path)
            path.resolve(strict=True).relative_to(output.resolve(strict=True))
            if path.is_symlink() or path.suffix.lower() != ".pdf":
                raise RuntimeError("engine_pdf_artifact_invalid")
            with pymupdf.open(path) as document:
                actual_pages = len(document)
                if actual_pages != selected * (2 if role == "dual" else 1):
                    raise RuntimeError("output_page_count_mismatch")
            artifacts.append({"role": role, "path": path.relative_to(job.root).as_posix(), "sha256": sha256_file(path),
                              "bytes": path.stat().st_size, "pages": actual_pages})
        if sha256_file(job.input_pdf) != job.input_sha256:
            raise ContractError("source_mutated")
        manifest = {"status": "PASS", "job_id": job.job_id, "contract_sha256": job.contract_sha256,
            "engine_versions": installed, "entrypoint": "pdf2zh_next.high_level.do_translate_async_stream",
            "source_sha256": job.input_sha256, "source_document_pages": total_pages,
            "selected_pages": {"start": start, "end": end, "count": selected}, "mode": job.mode,
            "preview": job.mode == "preview", "whole_document": selected == total_pages and job.mode == "full",
            "source_lang": job.source_lang, "target_lang": job.target_lang, "callback_label": job.callback_label,
            "engine_target_lang": layout_language(job.target_lang),
            "translation_quality": "NOT RUN" if job.callback_label == "TEST_IDENTITY_FIXTURE" else "NOT INDEPENDENTLY REVIEWED",
            "runtime_provider_calls": 0, "callback_posts": translator.callback_posts,
            "job_scoped_receipt_hits": translator.translate_cache_call_count,
            "provider_usage_source": "parent callback ledger only; callback POST count is not provider request count",
            "formula_and_style_placeholders": "checked per callback; visual formula quality requires inspection",
            "glossary_extraction": False, "model_fallback": False, "sent_request_retry": False,
            "qps": job.qps, "pool": job.pool, "assets": asset_summary, "artifacts": artifacts,
            "provenance": job.provenance, "device": "CPU", "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "python": platform.python_version(), "elapsed_seconds": round(time.time() - started, 3)}
        manifest["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        write_private_json(job.directory / "manifest.json", manifest)
        event(job, "finish", artifact_count=len(artifacts), callback_posts=translator.callback_posts)
        return manifest
    except BaseException as exc:
        # No exception strings/source lines/locals: libraries embed text in errors.
        frames = [{"file": Path(f.filename).name, "function": f.name, "line": f.lineno}
                  for f in traceback.extract_tb(exc.__traceback__)][-12:]
        failure = {"status": "FAIL", "job_id": job.job_id, "error_type": type(exc).__name__,
                   "frames": frames, "callback_label": job.callback_label, "translation_quality": "NOT RUN",
                   "elapsed_seconds": round(time.time() - started, 3)}
        if isinstance(exc, ContractError):
            failure["error_code"] = str(exc)
        write_private_json(job.directory / "failure.json", failure)
        event(job, "failed", error_type=type(exc).__name__)
        return failure


def run_engine(job, max_pages):
    result = asyncio.run(translate_job(job, max_pages))
    return 0 if result["status"] == "PASS" else 1
