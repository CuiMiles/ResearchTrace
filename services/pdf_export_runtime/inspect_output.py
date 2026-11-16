"""Offline PDF inspection/rendering. Does not print extracted document text."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

from .contract import load_job, private_path, sha256_file, write_private_json


def inspect(root, job_file):
    import pymupdf
    job = load_job(root, job_file)
    manifest = json.loads((job.directory / "manifest.json").read_text())
    directory = job.directory / "inspection"
    directory.mkdir(mode=0o700, exist_ok=True)
    pages = manifest["selected_pages"]
    with pymupdf.open(job.input_pdf) as source:
        text = "\n".join(source[p].get_text() for p in range(pages["start"] - 1, pages["end"]))
        source[pages["start"] - 1].get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3)).save(directory / "source-first-selected.png")
    summary = {"job_id": job.job_id, "callback_label": job.callback_label, "source_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
               "source_characters": len(text), "artifacts": [], "rendered_images": []}
    for entry in manifest["artifacts"]:
        path = private_path(root, entry["path"])
        if sha256_file(path) != entry["sha256"]:
            raise RuntimeError("artifact_hash_mismatch")
        with pymupdf.open(path) as document:
            extracted = "\n".join(page.get_text() for page in document)
            artifact = {"role": entry["role"], "pages": len(document), "sha256": entry["sha256"],
                        "characters": len(extracted), "text_sha256": hashlib.sha256(extracted.encode()).hexdigest(),
                        "page_sizes": [[page.rect.width, page.rect.height] for page in document]}
            if job.callback_label == "TEST_IDENTITY_FIXTURE" and entry["role"] == "mono":
                # Diagnostic only: token extraction changes with fonts/layout.
                expected = Counter(re.findall(r"[A-Za-z0-9]+", text.casefold()))
                observed = Counter(re.findall(r"[A-Za-z0-9]+", extracted.casefold()))
                artifact["identity_source_token_coverage"] = {"numerator": sum((expected & observed).values()), "denominator": sum(expected.values())}
            for index in range(min(2, len(document))):
                image = directory / f"{entry['role']}-{index + 1}.png"
                document[index].get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3)).save(image)
            summary["artifacts"].append(artifact)
    for image in sorted(directory.glob("*.png")):
        summary["rendered_images"].append({"path": image.relative_to(root).as_posix(), "sha256": sha256_file(image), "bytes": image.stat().st_size})
    write_private_json(directory / "inspection.json", summary)
    print(json.dumps(summary))


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    inspect(args.root.resolve(strict=True), args.job)
