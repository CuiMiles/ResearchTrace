#!/usr/bin/env python3
"""Fetch only the selected immutable HF revisions into a NEW private root.

Metadata is downloaded before weights, without importing or trusting model code.
Run --metadata-only first and review model.py, templates and dependency versions.
No account, key, existing model cache or application environment is modified.
"""
import argparse
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path


def model_dir(root, spec):
    return root / "models" / spec["model_id"].replace("/", "--") / spec["revision"]


def fetch(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "ResearchTrace-retrieval-provision/1"})
    with urllib.request.urlopen(request, timeout=90) as response:
        content = response.read()
    temporary = path.with_name(path.name + ".partial")
    temporary.write_bytes(content)
    temporary.replace(path)
    return content


def provision(root, config, metadata_only=False, weights_only=False):
    os.umask(0o077)
    root.mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)
    records = []
    for spec in config["models"]:
        dest = model_dir(root, spec)
        info_path = root / "logs" / (spec["model_id"].replace("/", "--") + ".hf.json")
        info = json.loads(info_path.read_text()) if weights_only else json.loads(fetch(
            "https://huggingface.co/api/models/" + spec["model_id"] + "/revision/" + spec["revision"],
            info_path,
        ))
        if info["sha"] != spec["revision"]:
            raise RuntimeError("HF revision mismatch")
        files = []
        for item in info["siblings"]:
            name = item["rfilename"]
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise RuntimeError("Unsafe repository filename")
            if name.endswith((".safetensors", ".bin", ".pt", ".pth")):
                continue
            content = (dest / name).read_bytes() if weights_only else fetch("https://huggingface.co/" + spec["model_id"] + "/resolve/" + spec["revision"] + "/" + name, dest / name)
            files.append({"path": name, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)})
        record = {"model_id": spec["model_id"], "revision": spec["revision"], "metadata": files,
                  "metadata_ready": True, "weights_ready": False, "updated_at": time.time()}
        records.append(record)
        (root / "download-state.json").write_text(json.dumps(records, indent=2))
        print(json.dumps({"stage": "metadata_ready", "model_id": spec["model_id"], "revision": spec["revision"]}), flush=True)
    if metadata_only:
        return
    from huggingface_hub import snapshot_download
    # One model and at most two files at a time to bound bandwidth/disk pressure.
    if __import__("shutil").disk_usage(root).free < 70 * 1024**3:
        raise RuntimeError("Need 70 GiB free disk for three BF16 models plus reserve")
    import concurrent.futures
    import threading
    state_lock = threading.Lock()
    def download(pair):
        spec, record = pair
        dest = model_dir(root, spec)
        snapshot_download(repo_id=spec["model_id"], revision=spec["revision"],
                          local_dir=str(dest), max_workers=2, token=False,
                          allow_patterns=["*.safetensors", "2_Dense/*.safetensors"])
        index = json.loads((dest / "model.safetensors.index.json").read_text())
        names = sorted(set(index["weight_map"].values()))
        if spec["kind"] == "reranker":
            names += ["2_Dense/model.safetensors"]
        record["weights"] = [{"path": n, "bytes": (dest / n).stat().st_size} for n in names]
        record["weights_ready"] = all(x["bytes"] > 1000 for x in record["weights"])
        record["updated_at"] = time.time()
        (dest / "weights-ready.json").write_text(json.dumps(record, indent=2))
        with state_lock:
            temporary = root / "download-state.json.partial"
            temporary.write_text(json.dumps(records, indent=2))
            temporary.replace(root / "download-state.json")
        print(json.dumps({"stage": "weights_ready", "model_id": spec["model_id"]}), flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(download, zip(config["models"], records)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/retrieval-models.json"))
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--weights-only", action="store_true")
    args = parser.parse_args()
    provision(args.root.resolve(), json.loads(args.config.read_text()), args.metadata_only, args.weights_only)
