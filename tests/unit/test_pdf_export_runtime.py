"""Contract/failure tests, not evidence of translation or engine layout quality."""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from services.pdf_export_runtime.callback import CallbackError, CallbackTransport, validate_placeholders
from services.pdf_export_runtime.cli import child_environment, python_command, stop_owned, supervise
from services.pdf_export_runtime.contract import ContractError, load_job, private_path, sha256_file, validate_callback_url, write_private_json
from services.pdf_export_runtime.engine import layout_language, restrict_network, verify_assets


@pytest.fixture
def job_root(tmp_path):
    (tmp_path / "private/inputs").mkdir(parents=True)
    source = tmp_path / "private/inputs/source.pdf"
    source.write_bytes(b"%PDF-1.4\n%CONTRACT_ONLY_FIXTURE_NOT_A_RENDERABLE_PDF\n")
    token = tmp_path / "private/callback.token"
    token.write_text("TEST_TOKEN_ONLY_0123456789abcdef")
    token.chmod(0o600)
    job = {"job_id": "unit-job", "input_pdf": "private/inputs/source.pdf", "input_sha256": sha256_file(source),
           "token_file": "private/callback.token", "callback_url": "http://127.0.0.1:17888/translate",
           "source_lang": "en", "target_lang": "zh", "callback_label": "TEST_IDENTITY_FIXTURE", "qps": 4, "pool": 4}
    write_private_json(tmp_path / "private/job.json", job)
    return tmp_path, job


def rewrite(root, data):
    write_private_json(root / "private/job.json", data)
    return load_job(root, "private/job.json")


@pytest.mark.parametrize("url", ["http://localhost:80/x", "http://example.com:80/x", "http://169.254.169.254:80/x",
    "http://192.168.1.1:80/x", "https://127.0.0.1:80/x", "http://user:secret@127.0.0.1:80/x",
    "http://127.0.0.1:80/x?token=bad", "http://127.0.0.1:80/x#fragment", "http://127.0.0.1/x",
    "http://127.0.0.1:80/../x", "http://2130706433:80/x", "http://127.0.0.1:80/x\n"])
def test_callback_rejects_url_escape(url):
    with pytest.raises(ContractError):
        validate_callback_url(url)


def test_literal_loopback_supported():
    assert validate_callback_url("http://127.0.0.1:17888/translate")
    assert validate_callback_url("http://[::1]:17888/translate")


def test_default_preview_is_bounded(job_root):
    root, data = job_root
    job = load_job(root, "private/job.json")
    assert job.mode == "preview" and job.page_selection(10, 2) == (1, 2)
    assert job.page_selection(1, 2) == (1, 1)
    data["pages"] = {"start": 1, "end": 3}
    with pytest.raises(ContractError, match="page_limit"):
        rewrite(root, data).page_selection(10, 2)
    data["mode"] = "full"
    with pytest.raises(ContractError, match="full_requires"):
        rewrite(root, data).page_selection(10, 20)


@pytest.mark.parametrize("field,value", [("input_pdf", "../../etc/passwd"), ("input_pdf", "/etc/passwd"),
    ("input_pdf", "https://example.com/file.pdf"), ("shell", "echo unsafe"), ("qps", 5), ("pool", 0),
    ("qps", True), ("job_id", "../escape"), ("callback_label", "REAL_TRANSLATION"), ("mode", "anything")])
def test_job_rejects_arbitrary_fields_and_limits(job_root, field, value):
    root, data = job_root
    data[field] = value
    with pytest.raises(ContractError):
        rewrite(root, data)


def test_source_hash_and_symlink_are_enforced(job_root):
    root, data = job_root
    data["input_sha256"] = "0" * 64
    with pytest.raises(ContractError, match="hash_mismatch"):
        rewrite(root, data)
    (root / "private/escape").symlink_to(root.parent, target_is_directory=True)
    with pytest.raises(ContractError, match="symlink"):
        private_path(root, "private/escape/test.pdf", must_exist=False)


def test_no_public_token_and_no_credential_environment(job_root, monkeypatch):
    root, data = job_root
    (root / "private/callback.token").chmod(0o644)
    with pytest.raises(ContractError, match="private_owner"):
        rewrite(root, data)
    monkeypatch.setenv("GOOGLE_API_KEY", "TEST_ONLY_DO_NOT_PROPAGATE")
    monkeypatch.setenv("HTTPS_PROXY", "http://invalid:9")
    env = child_environment(root, root / "private/jobs/unit-job")
    assert "GOOGLE_API_KEY" not in env and "HTTPS_PROXY" not in env
    assert env["CUDA_VISIBLE_DEVICES"] == ""


def test_placeholder_preservation():
    original = "Value {v1} <style id='2'>test</style> [[RT_FORMULA_1]] \\(x+y\\)"
    validate_placeholders(original, original.replace("Value", "数值").replace("test", "测试"))
    with pytest.raises(CallbackError, match="placeholder"):
        validate_placeholders(original, original.replace("{v1}", "v1"))


def server_for(result):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((request, self.headers["Authorization"]))
            code, response = result(request)
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            if code == 302:
                self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            body = json.dumps(response).encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, calls


def test_callback_real_http_exact_contract_and_single_flight(job_root):
    root, data = job_root
    server, thread, calls = server_for(lambda obj: (200, {"translation": obj["text"] + " 译"}))
    try:
        data["callback_url"] = f"http://127.0.0.1:{server.server_port}/translate"
        job = rewrite(root, data)
        client = CallbackTransport(job)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(client.translate, ["text {v1}"] * 4))
        assert results == ["text {v1} 译"] * 4
        assert len(calls) == 1
        assert set(calls[0][0]) == {"text", "source_lang", "target_lang", "job_id"}
        assert calls[0][1].startswith("Bearer TEST_TOKEN_ONLY")
        # Successful receipts survive restarts but only inside this exact job.
        assert CallbackTransport(job).translate("text {v1}") == "text {v1} 译"
        assert len(calls) == 1
        second = dataclasses.replace(job, job_id="other-job")
        CallbackTransport(second).translate("text {v1}")
        assert len(calls) == 2
        with pytest.raises(NotImplementedError):
            client.do_llm_translate(None)
        with pytest.raises(CallbackError, match="llm_mode"):
            client.llm_translate("no provider prompts")
        assert len(calls) == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("code,response", [(302, {}), (429, {}), (200, {"translation": "lost placeholder"}),
    (200, {"translation": "source {v1}", "extra": "unsafe"})])
def test_sent_or_invalid_response_never_retried(job_root, code, response):
    root, data = job_root
    server, thread, calls = server_for(lambda obj: (code, response))
    try:
        data["callback_url"] = f"http://127.0.0.1:{server.server_port}/translate"
        job = rewrite(root, data)
        client = CallbackTransport(job)
        with pytest.raises(CallbackError):
            client.translate("source {v1}")
        for text in ("source {v1}", "library fallback modified input"):
            with pytest.raises(CallbackError):
                client.translate(text)
        with pytest.raises(CallbackError):
            CallbackTransport(job).translate("source {v1}")
        assert len(calls) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_pending_receipt_blocks_unknown_request_after_restart(job_root):
    root, _ = job_root
    job = load_job(root, "private/job.json")
    import hashlib
    from services.pdf_export_runtime.contract import json_bytes
    payload = {"text": "source", "source_lang": "en", "target_lang": "zh", "job_id": job.job_id}
    key = hashlib.sha256(json_bytes(payload)).hexdigest()
    write_private_json(job.directory / "callback-receipts" / (key + ".json"), {"status": "sent_or_unknown"})
    client = CallbackTransport(job)
    with pytest.raises(CallbackError, match="no_retry"):
        client.translate("source")
    assert client.callback_posts == 0


def test_job_id_cannot_be_rebound(job_root):
    root, data = job_root
    job = load_job(root, "private/job.json")
    write_private_json(job.directory / "binding.json", {"contract_sha256": "0" * 64})
    with pytest.raises(ContractError, match="different_contract"):
        supervise(root, "private/job.json", 2)


def test_cancel_only_stops_owned_child():
    owned = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        stop_owned(owned)
        assert owned.poll() is not None
        assert other.poll() is None
        stop_owned(owned)  # An already reaped PID is never signalled again.
        assert other.poll() is None
    finally:
        stop_owned(owned)
        stop_owned(other)


def test_compat_loader_is_confined_to_runtime(job_root):
    root, _ = job_root
    (root / "runtime").mkdir()
    (root / "runtime/python-command.json").write_text(json.dumps({"loader": "/bin/sh", "library_paths": []}))
    with pytest.raises(ValueError):
        python_command(root)


def test_chinese_layout_font_mapping_keeps_callback_language(job_root):
    root, data = job_root
    data["target_lang"] = "zh-Hans"
    job = rewrite(root, data)
    assert layout_language(job.target_lang) == "zh-CN"
    assert job.target_lang == "zh-Hans"
    assert layout_language("en") == "en"


def test_assets_cannot_be_replaced_with_an_unpinned_lock(job_root):
    root, _ = job_root
    write_private_json(root / "assets/assets.lock.json", {"engine_versions": {"pdf2zh-next": "2.10.2", "babeldoc": "0.7.1"},
                                                         "files": [{"path": "arbitrary-model", "sha256": "0" * 64}]})
    with pytest.raises(ContractError, match="pinned_release"):
        verify_assets(root)


def test_incomplete_manifest_cannot_be_claimed_as_cached_success(job_root):
    root, _ = job_root
    job = load_job(root, "private/job.json")
    write_private_json(job.directory / "manifest.json", {"status": "PASS", "job_id": job.job_id,
                                                        "contract_sha256": job.contract_sha256, "artifacts": []})
    with pytest.raises(ContractError, match="incomplete"):
        supervise(root, "private/job.json", 2)


def test_engine_network_denies_other_ports_and_hosts(monkeypatch):
    import socket
    original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex
    try:
        restrict_network("http://127.0.0.1:17888/translate")
        for address in (("169.254.169.254", 80), ("8.8.8.8", 443), ("127.0.0.1", 17889)):
            with socket.socket() as sock:
                with pytest.raises(PermissionError, match="network_denied"):
                    sock.connect(address)
                with pytest.raises(PermissionError, match="network_denied"):
                    sock.connect_ex(address)
    finally:
        socket.socket.connect, socket.socket.connect_ex = original_connect, original_connect_ex
