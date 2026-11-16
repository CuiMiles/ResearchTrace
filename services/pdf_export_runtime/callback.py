"""At most one callback POST per job/text. No model SDK or environment keys."""
from __future__ import annotations

import hashlib
import http.client
import json
import re
import threading
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from .contract import ExportJob, json_bytes, read_token, validate_callback_url, write_private_json


class CallbackError(RuntimeError):
    pass


PLACEHOLDERS = re.compile(r"\{\s*v\s*\d+\s*\}|<\s*/?\s*style(?:\s+id\s*=\s*['\"]\d+['\"])?\s*>|\[\[RT_[A-Za-z0-9_]+\]\]|\$\$[^$]*\$\$|\\\([^\n]*?\\\)|\\\[[\s\S]*?\\\]")


def validate_placeholders(source: str, translated: str) -> None:
    if Counter(PLACEHOLDERS.findall(source)) != Counter(PLACEHOLDERS.findall(translated)):
        raise CallbackError("placeholder_mismatch")


class CallbackTransport:
    name = "rt-ledger-callback"
    model = "parent-ledger-bridge"
    ignore_cache = True

    def __init__(self, job: ExportJob):
        self.job = job
        self.lang_in, self.lang_out = job.source_lang, job.target_lang
        self.translate_call_count = self.translate_cache_call_count = 0
        self.callback_posts = 0
        self.failed = False
        self._lock = threading.Lock()
        self._keys: dict[str, threading.Lock] = {}
        self._next_request = 0.0
        self._token = read_token(job.token_file)
        self.receipts = job.directory / "callback-receipts"
        self.receipts.mkdir(mode=0o700, parents=True, exist_ok=True)

    def _check_active(self):
        if self.failed or (self.job.directory / "CANCEL_REQUESTED").exists():
            raise CallbackError("callback_stopped")

    def translate(self, text, ignore_cache=False, rate_limit_params=None):
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > 128 * 1024:
            raise CallbackError("invalid_callback_text")
        payload = {"text": text, "source_lang": self.lang_in, "target_lang": self.lang_out, "job_id": self.job.job_id}
        body = json_bytes(payload)
        key = hashlib.sha256(body).hexdigest()
        with self._lock:
            lock = self._keys.setdefault(key, threading.Lock())
            self.translate_call_count += 1
        with lock:
            self._check_active()
            receipt = self.receipts / (key + ".json")
            if receipt.exists():
                record = json.loads(receipt.read_text())
                if record.get("status") != "received":
                    self.failed = True
                    raise CallbackError("prior_request_unknown_or_failed_no_retry")
                translated = record.get("translation")
                if not isinstance(translated, str):
                    raise CallbackError("invalid_receipt")
                validate_placeholders(text, translated)
                self.translate_cache_call_count += 1
                return translated
            # Persist before sending. A crash/timeout is never interpreted as zero consumption.
            with self._lock:
                delay = max(0.0, self._next_request - time.monotonic())
                self._next_request = max(self._next_request, time.monotonic()) + 1.0 / self.job.qps
            if delay:
                time.sleep(delay)
            self._check_active()
            write_private_json(receipt, {"status": "sent_or_unknown", "request_sha256": key})
            connection = None
            try:
                url = urlsplit(validate_callback_url(self.job.callback_url))
                connection = http.client.HTTPConnection(url.hostname, url.port, timeout=self.job.callback_timeout_s)
                self.callback_posts += 1
                connection.request("POST", url.path, body=body, headers={"Authorization": "Bearer " + self._token,
                    "Content-Type": "application/json", "Content-Length": str(len(body)), "Connection": "close"})
                response = connection.getresponse()
                # http.client does not redirect, retry or read proxy variables.
                if response.status != 200:
                    raise CallbackError("callback_http_rejected")
                raw = response.read(512 * 1024 + 1)
                if len(raw) > 512 * 1024:
                    raise CallbackError("callback_response_too_large")
                result = json.loads(raw)
                if not isinstance(result, dict) or set(result) != {"translation"} or not isinstance(result["translation"], str) or not result["translation"].strip():
                    raise CallbackError("invalid_callback_response")
                translated = result["translation"]
                # Save a received response before validation, so validation failure cannot re-bill.
                write_private_json(receipt, {"status": "received_unvalidated", "request_sha256": key, "translation": translated})
                validate_placeholders(text, translated)
                write_private_json(receipt, {"status": "received", "request_sha256": key, "translation": translated})
                return translated
            except Exception:
                self.failed = True
                raise CallbackError("callback_failed_no_retry") from None
            finally:
                if connection:
                    connection.close()

    def do_translate(self, text, rate_limit_params=None):
        return self.translate(text, rate_limit_params=rate_limit_params)

    def do_llm_translate(self, text, rate_limit_params=None):
        # BabelDOC probes None to select the ordinary paragraph translation path.
        # This disables prompt-based batching, term extraction and model fallback.
        raise NotImplementedError("llm_mode_disabled")

    def llm_translate(self, text, ignore_cache=False, rate_limit_params=None):
        raise CallbackError("llm_mode_disabled")


def build_translator(job: ExportJob):
    # Inherit the pinned library's formula/style placeholders, but intentionally
    # never call BaseTranslator.__init__ (global SQLite cache and rate limiter).
    from pdf2zh_next.translator.base_translator import BaseTranslator

    class CallbackTranslator(CallbackTransport, BaseTranslator):
        pass

    return CallbackTranslator(job)
