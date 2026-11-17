"""Offline fixtures test contracts/guards only; these are NOT live model tests."""
import json
import os
import subprocess
import sys
from itertools import pairwise

import pytest

from services.retrieval_runtime import guard
from services.retrieval_runtime.catalog import Catalog


@pytest.fixture
def provisioned(tmp_path):
    pytest.importorskip("tokenizers", reason="Install runtime tokenizer dependencies in an isolated environment")
    from tokenizers import Tokenizer, models, pre_tokenizers
    spec = {"model_id": "fixture/offline", "revision": "a" * 40, "kind": "embedding", "family": "qwen3",
            "dimension": 4, "dtype": "bfloat16", "context_length": 32768, "pooling": "last_token",
            "normalization": "l2", "query_template": "Instruct: search Query: {text}", "document_template": "{text}"}
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"models": [spec]}))
    directory = tmp_path / "models" / "fixture--offline" / ("a" * 40)
    directory.mkdir(parents=True)
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.save(str(directory / "tokenizer.json"))
    (directory / "tokenizer_config.json").write_text("{}")
    token = tmp_path / "auth.token"
    token.write_text("offline-fixture-token-" + "b" * 32)
    token.chmod(0o600)
    return Catalog(config, tmp_path), spec, config, token


def test_catalog_rejects_unpinned_revision(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"models": [{"model_id": "fixture/offline", "revision": "main"}]}))
    with pytest.raises(ValueError, match="immutable"):
        Catalog(config, tmp_path)


def test_fingerprint_separates_template_pooling_and_tokenizer(provisioned):
    catalog, spec, _, _ = provisioned
    original = catalog.descriptor(spec)["fingerprint"]
    changed = dict(spec, pooling="mean")
    assert catalog.descriptor(changed)["fingerprint"] != original
    changed = dict(spec, query_template="Different instruction: {text}")
    assert catalog.descriptor(changed)["fingerprint"] != original
    file = catalog.directory(spec) / "tokenizer_config.json"
    file.write_text('{"add_bos_token":true}')
    assert catalog.descriptor(spec)["fingerprint"] != original
    assert not catalog.descriptor(spec)["weights_ready"]
    assert not catalog.descriptor(spec)["inference_verified"]


def test_split_preserves_unicode_offsets_and_context(provisioned):
    from services.retrieval_runtime.tokenization import TextTokenizer
    catalog, spec, _, _ = provisioned
    tok = TextTokenizer(catalog, spec)
    text = "甲乙丙 中文 test\n\nA B C D E F G H I J K L M N O P Q R S T " * 8
    chunks = tok.split(text, "query", 12, 2)
    assert len(chunks) > 1
    assert chunks[0]["char_start"] == 0
    assert chunks[-1]["char_end"] == len(text)
    for previous, current in pairwise(chunks):
        assert previous["char_start"] < current["char_start"] <= previous["char_end"]
    for chunk in chunks:
        assert text[chunk["char_start"]:chunk["char_end"]] == chunk["text"]
        assert chunk["token_count"] == tok.count(chunk["text"], "query") <= 12
    with pytest.raises(ValueError, match="template"):
        tok.split(text, "query", 2, 0)


def test_actual_saved_nemotron_template_is_used(provisioned):
    from services.retrieval_runtime.tokenization import TextTokenizer
    catalog, spec, _, _ = provisioned
    spec.update(family="nemotron", pooling="mean")
    file = catalog.directory(spec) / "chat_template.jinja"
    file.write_text("{{ messages[0].content }} {{ messages[1].content[0].text | replace('<','SAFE') }}")
    tok = TextTokenizer(catalog, spec)
    assert tok.render("<data>", "query") == "query: SAFEdata>"
    assert tok.render("<data>", "document") == "passage: SAFEdata>"


def test_http_auth_revision_context_and_no_live_weights(provisioned):
    pytest.importorskip("jinja2")
    from fastapi.testclient import TestClient

    from services.retrieval_runtime.server import create_app
    catalog, spec, config, token = provisioned
    app = create_app(config, catalog.root, token)
    with TestClient(app) as client:
        assert client.get("/manifest").status_code == 401
        client.headers["Authorization"] = "Bearer " + token.read_text()
        manifest = client.get("/manifest").json()
        assert manifest["models"][0]["tokenizer_ready"]
        body = {"model_id": spec["model_id"], "revision": spec["revision"],
                "texts": ["new input " * 20], "task": "document", "split": {"max_tokens": 8, "overlap": 2}}
        response = client.post("/tokenize", json=body)
        assert response.status_code == 200
        result = response.json()
        assert max(c["token_count"] for c in result["items"][0]["chunks"]) <= 8
        assert result["fingerprint"] == manifest["models"][0]["fingerprint"]
        body["revision"] = "b" * 40
        assert client.post("/tokenize", json=body).status_code == 409
        body["revision"] = spec["revision"]
        body.pop("split")
        response = client.post("/embed", json=body)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "runtime_unavailable"
        body["texts"] = ["a " * 32769]
        assert client.post("/embed", json=body).status_code == 422
        body["texts"] = ["   "]
        assert client.post("/embed", json=body).status_code == 422


def test_token_file_must_be_private(provisioned):
    from services.retrieval_runtime.server import create_app
    catalog, _, config, token = provisioned
    token.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        create_app(config, catalog.root, token)


def test_guard_reserves_whole_budget_and_rejects_unaccounted_gpu(monkeypatch):
    monkeypatch.setattr(guard, "gpus", lambda: [{"index": 0, "uuid": "GPU-test", "free_mib": 10000, "total_mib": 24000}])
    with pytest.raises(RuntimeError, match="Insufficient"):
        guard.choose_gpu(8192, 2048)
    with pytest.raises(ValueError, match="2048"):
        guard.choose_gpu(4096, 100)
    monkeypatch.setattr(guard, "members", lambda sid: {1234})
    monkeypatch.setattr(guard, "query", lambda *args: [["1234", "GPU-test", "[N/A]"]])
    with pytest.raises(RuntimeError, match="accounting unavailable"):
        guard.sample(1234, {"uuid": "GPU-test"})


def test_guard_counts_child_gpu_and_all_stops_are_own(monkeypatch):
    monkeypatch.setattr(guard, "memory_available_mib", lambda: 200000)
    monkeypatch.setattr(guard, "members", lambda sid: {100, 101})
    monkeypatch.setattr(guard, "gpus", lambda: [{"uuid": "GPU-test", "free_mib": 5000}])
    monkeypatch.setattr(guard, "query", lambda *args: [["100", "GPU-test", "1000"], ["101", "GPU-test", "2000"], ["500", "GPU-test", "15000"]])
    sample = guard.sample(100, {"uuid": "GPU-test"})
    assert sample["gpu_used_mib"] == 3000
    assert guard.violation(sample, 2048, 2048, 49152, 16384) == "Own process tree exceeded GPU memory budget"
    sample["gpu_used_mib"] = 1000
    sample["per_gpu"][0]["used_mib"] = 1000
    sample["gpu_free_mib"] = 2047
    assert "reserve" in guard.violation(sample, 2048, 2048, 49152, 16384)


def test_two_gpu_guard_checks_each_card_and_child(monkeypatch):
    monkeypatch.setattr(guard, "memory_available_mib", lambda: 200000)
    monkeypatch.setattr(guard, "members", lambda sid: {100, 101})
    cards = [{"index": 3, "uuid": "GPU-a", "free_mib": 13000},
             {"index": 5, "uuid": "GPU-b", "free_mib": 14000}]
    monkeypatch.setattr(guard, "gpus", lambda: cards)
    selected = guard.choose_gpus(10000, 2048, 2)
    monkeypatch.setattr(guard, "query", lambda *args: [["100", "GPU-a", "8000"], ["101", "GPU-b", "8500"], ["999", "GPU-b", "4000"]])
    value = guard.sample(100, selected)
    assert value["gpu_used_mib"] == 16500
    assert guard.violation(value, 10000, 2048, 49152, 16384) is None
    cards[1]["free_mib"] = 2047
    value = guard.sample(100, selected)
    assert "reserve" in guard.violation(value, 10000, 2048, 49152, 16384)
    with pytest.raises(RuntimeError, match="Insufficient"):
        guard.choose_gpus(10000, 2048, 2)


def test_guard_terminates_only_spawned_session():
    own = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"], start_new_session=True)
    unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"], start_new_session=True)
    try:
        assert unrelated.pid not in guard.members(own.pid)
        guard.stop_owned(own)
        assert own.returncode is not None
        assert unrelated.poll() is None
    finally:
        if own.returncode is None:
            guard.stop_owned(own)
        guard.stop_owned(unrelated)


def test_exited_unreaped_child_releases_slots_and_repeated_cleanup_is_safe(tmp_path,monkeypatch):
    from services.retrieval_runtime.supervisor import Supervisor
    from types import SimpleNamespace
    import fcntl
    own=subprocess.Popen([sys.executable,'-c','pass'],start_new_session=True)
    try:
        os.waitid(os.P_PID,own.pid,os.WEXITED|os.WNOWAIT)
        assert own.returncode is None  # Still anchors its original session ID.
        assert not guard.members(own.pid)
        monkeypatch.setattr(guard,'gpus',lambda:[{'index':0,'uuid':'GPU-fixture','free_mib':14000}])
        _,handles=guard.claim_gpus(tmp_path,10000,2048,1)
        with pytest.raises(RuntimeError,match='unclaimed'):
            guard.claim_gpus(tmp_path,10000,2048,1)
        manager=Supervisor(SimpleNamespace())
        manager.process=own;manager.gpu_claims=handles
        (tmp_path/'stderr.log').touch()
        manager._watch(own,None,tmp_path,0,'cpu',10000)
        assert manager.gpu_claims==[] and manager.failure is None
        _,released=guard.claim_gpus(tmp_path,10000,2048,1)
        for handle in released:handle.close()
        guard.stop_owned(own)
        monkeypatch.setattr(guard,'members',lambda sid:pytest.fail('Already reaped PID must never be scanned for signals'))
        guard.stop_owned(own)
    finally:
        if own.returncode is None:own.wait(timeout=10)


def test_no_application_provider_keys_pass_to_runner(provisioned, monkeypatch):
    from services.retrieval_runtime import supervisor
    catalog, spec, _, _ = provisioned
    descriptor = catalog.descriptor(spec)
    descriptor["weights_ready"] = True
    monkeypatch.setattr(catalog, "descriptor", lambda spec: descriptor)
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture-not-a-real-key")
    monkeypatch.setenv("RT_RETRIEVAL_EXECUTION_MODE", "cpu")
    monkeypatch.setattr(guard, "memory_available_mib", lambda: 200000)
    captured = {}
    class FakeProcess:
        pid = 99999999
    def popen(*args, **kwargs):
        captured.update(kwargs["env"])
        return FakeProcess()
    class FakeThread:
        def __init__(self, **kwargs):
            pass
        def start(self):
            pass
    monkeypatch.setattr(supervisor.subprocess, "Popen", popen)
    monkeypatch.setattr(supervisor.threading, "Thread", FakeThread)
    manager = supervisor.Supervisor(catalog)
    monkeypatch.setattr(manager, "_line", lambda proc: {"ready": True})
    manager._launch(spec)
    assert "GEMINI_API_KEY" not in captured
    assert captured["HF_HUB_OFFLINE"] == "1"
    assert captured["CUDA_VISIBLE_DEVICES"] == ""
    assert os.getpid() not in guard.members(-1)


@pytest.mark.parametrize("single", ["1", "0"])
def test_cuda_auto_can_be_kept_split_on_shared_gpus(provisioned, monkeypatch, single):
    from services.retrieval_runtime import supervisor
    catalog, spec, _, _ = provisioned
    descriptor = catalog.descriptor(spec)
    descriptor["weights_ready"] = True
    monkeypatch.setattr(catalog, "descriptor", lambda spec: descriptor)
    monkeypatch.setenv("RT_RETRIEVAL_EXECUTION_MODE", "cuda_auto")
    monkeypatch.setenv("RT_RETRIEVAL_GPU_MAX_MIB", "10240")
    monkeypatch.setenv("RT_RETRIEVAL_SINGLE_GPU", single)
    monkeypatch.setattr(guard, "memory_available_mib", lambda: 200000)
    claims = []
    def claim(root, share, reserve, count):
        claims.append((share, count))
        return [{"uuid": f"GPU-{i}", "index": i} for i in range(count)], []
    monkeypatch.setattr(guard, "claim_gpus", claim)
    captured = {}
    class FakeProcess:
        pid = 99999999
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *a, **kw: captured.update(kw["env"]) or FakeProcess())
    monkeypatch.setattr(supervisor.threading, "Thread", lambda **kw: type("T", (), {"start": lambda self: None})())
    manager = supervisor.Supervisor(catalog)
    monkeypatch.setattr(manager, "_line", lambda proc: {"ready": True})
    manager._launch(spec)
    if single == "1":
        assert claims[0] == (20480, 1) and captured["RT_RETRIEVAL_EXECUTION_MODE"] == "cuda"
    else:  # never one card at double budget: split, each card within 10240 MiB
        assert claims == [(10240, 2)] and captured["RT_RETRIEVAL_EXECUTION_MODE"] == "cuda_sharded"
        assert int(captured["RT_RETRIEVAL_GPU_MAX_MIB"]) <= 10240
