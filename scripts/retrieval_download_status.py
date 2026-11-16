#!/usr/bin/env python3
"""Private, credential-free progress for BF16 downloads (not readiness proof)."""
import argparse
import json
from pathlib import Path


def status(root, config):
    result = []
    for spec in json.loads(config.read_text())["models"]:
        directory = root / "models" / spec["model_id"].replace("/", "--") / spec["revision"]
        index = directory / "model.safetensors.index.json"
        expected = json.loads(index.read_text()).get("metadata", {}).get("total_size") if index.exists() else None
        parts = [file for file in directory.rglob("*") if file.is_file() and
                 (file.name.endswith(".safetensors") or file.name.endswith(".incomplete"))]
        result.append({"model_id": spec["model_id"], "revision": spec["revision"],
                       "downloaded_bytes": sum(file.stat().st_size for file in parts),
                       "expected_weight_bytes": expected, "weights_ready": (directory / "weights-ready.json").is_file()})
    return {"models": result, "total_downloaded_bytes": sum(item["downloaded_bytes"] for item in result)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/retrieval-models.json"))
    args = parser.parse_args()
    print(json.dumps(status(args.root, args.config), indent=2))
