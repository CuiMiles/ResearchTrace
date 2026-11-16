"""Download/check pinned engine assets at provision time, never during a job."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path

from .contract import sha256_file, write_private_json
from .engine import VERSIONS


def main(root):
    import babeldoc.const as const
    const.CACHE_FOLDER = root / "assets/babeldoc"
    const.TIKTOKEN_CACHE_FOLDER = const.CACHE_FOLDER / "tiktoken"
    const.TIKTOKEN_CACHE_FOLDER.mkdir(parents=True, exist_ok=True)
    os.environ["TIKTOKEN_CACHE_DIR"] = str(const.TIKTOKEN_CACHE_FOLDER)
    from babeldoc.assets.assets import generate_all_assets_file_list, warmup
    warmup()
    expected = generate_all_assets_file_list()
    files = []
    for folder, entries in expected.items():
        for entry in entries:
            path = const.CACHE_FOLDER / folder / entry["name"]
            if not path.is_file():
                raise RuntimeError("asset_missing_after_warmup")
            content = path.read_bytes()
            if hashlib.sha3_256(content).hexdigest() != entry["sha3_256"]:
                raise RuntimeError("upstream_asset_hash_mismatch")
            files.append({"path": path.relative_to(root / "assets").as_posix(), "bytes": len(content),
                          "sha256": hashlib.sha256(content).hexdigest(), "upstream_sha3_256": entry["sha3_256"]})
    installed = {name: importlib.metadata.version(name) for name in VERSIONS}
    if installed != VERSIONS:
        raise RuntimeError("engine_version_mismatch")
    write_private_json(root / "assets/assets.lock.json", {"engine_versions": installed, "files": files})
    print(json.dumps({"status": "PASS", "asset_count": len(files), "total_bytes": sum(x["bytes"] for x in files),
                      "asset_lock_sha256": sha256_file(root / "assets/assets.lock.json")}))


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    main(parser.parse_args().root.resolve(strict=True))
