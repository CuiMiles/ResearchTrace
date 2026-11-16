#!/usr/bin/env python3
"""Real authenticated HTTP smoke. Fixtures never enter this script.

Outputs only status/provenance/measurements, not the bearer token or whole vectors.
No LLM/API-provider requests or quota configuration are made.
"""
import argparse
import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path


def call(base, token, route, body=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    request = urllib.request.Request(base.rstrip("/") + route, data=data,
                                     headers={"Authorization": "Bearer " + token,
                                              "Content-Type": "application/json"})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=1000) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def smoke(base, token_file, output, tokenizer_only=False):
    token = token_file.read_text().strip()
    status, manifest = call(base, token, "/manifest")
    if status != 200:
        raise RuntimeError("Authenticated manifest failed: HTTP " + str(status))
    rows = []
    for spec in manifest["models"]:
        selection = {"model_id": spec["model_id"], "revision": spec["revision"]}
        text = "训练用了多少张显卡？ The experiment used eight GPUs. <text> [IMG] 🙂 " * 40
        before = time.monotonic()
        status, result = call(base, token, "/tokenize", {**selection, "texts": [text], "task": "document",
                                                      "split": {"max_tokens": 64, "overlap": 8}})
        if status != 200:
            raise RuntimeError("Live tokenizer failed: " + str(result))
        chunks = result["items"][0]["chunks"]
        covered = 0
        for chunk in chunks:
            assert chunk["char_start"] <= covered
            assert text[chunk["char_start"]:chunk["char_end"]] == chunk["text"]
            assert 0 < chunk["token_count"] <= 64
            covered = max(covered, chunk["char_end"])
        assert covered == len(text)
        assert result["fingerprint"] == spec["fingerprint"]
        row = {**selection, "fingerprint": spec["fingerprint"], "tokenizer_status": "PASS",
               "split_chunks": len(chunks), "tokenizer_seconds": round(time.monotonic() - before, 4),
               "inference_status": "NOT RUN"}
        if not tokenizer_only:
            if not spec["weights_ready"]:
                row.update(inference_status="BLOCKED", reason="Weights are still downloading")
            elif spec["kind"] == "embedding":
                status, result = call(base, token, "/embed", {**selection, "task": "document", "texts": [
                    "The experiment used eight GPUs.", "The experiment used eight GPUs.", "A botanical study measures leaf growth."]})
                if status == 200:
                    vectors = result["vectors"]
                    assert len(vectors) == 3 and all(len(v) == spec["dimension"] for v in vectors)
                    norms = [math.sqrt(sum(x*x for x in vector)) for vector in vectors]
                    assert all(math.isfinite(n) and abs(n - 1) < 0.005 for n in norms)
                    repeated = max(abs(a - b) for a, b in zip(vectors[0], vectors[1]))
                    assert repeated < 0.005
                    assert result["fingerprint"] == spec["fingerprint"]
                    row.update(inference_status="PASS", norms=norms, repeat_max_abs=repeated,
                               usage=result["usage"], execution=result["execution"], device_map=result.get("device_map"))
                else:
                    row.update(inference_status="BLOCKED" if status == 503 else "FAIL", reason=result)
            else:
                status, result = call(base, token, "/rerank", {**selection, "query": "How many GPUs were used?", "documents": [
                    "The experiment used eight GPUs.", "A botanical study measures leaf growth."]})
                if status == 200:
                    assert len(result["scores"]) == 2 and all(math.isfinite(s) for s in result["scores"])
                    assert result["fingerprint"] == spec["fingerprint"]
                    row.update(inference_status="PASS", scores=result["scores"], usage=result["usage"],
                               execution=result["execution"], device_map=result.get("device_map"))
                else:
                    row.update(inference_status="BLOCKED" if status == 503 else "FAIL", reason=result)
        rows.append(row)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"live_http": True, "cases": rows, "provider_llm_calls": 0}, indent=2))
        print(json.dumps({"model_id": row["model_id"], "tokenizer_status": row["tokenizer_status"],
                          "inference_status": row["inference_status"]}), flush=True)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:18985")
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tokenizer-only", action="store_true")
    args = parser.parse_args()
    smoke(args.base, args.token_file, args.output, args.tokenizer_only)
