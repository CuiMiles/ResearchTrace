"""Explicit identity fixture smoke for real layout, never translation quality."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import threading
from pathlib import Path

from .cli import supervise
from .contract import private_path, sha256_file, write_private_json
from .identity_fixture import create_server


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--page", type=int)
    parser.add_argument("--identity-fixture", action="store_true", required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    source = private_path(root, args.input)
    directory = private_path(root, f"private/jobs/{args.job_id}", must_exist=False)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    token_path = directory / "callback.token"
    token_path.write_text(secrets.token_urlsafe(32))
    token_path.chmod(0o600)
    server = create_server(token_path, directory / "identity-statistics.json")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    job = {"job_id": args.job_id, "input_pdf": args.input, "input_sha256": sha256_file(source),
           "token_file": token_path.relative_to(root).as_posix(),
           "callback_url": f"http://127.0.0.1:{server.server_port}/translate", "source_lang": "en", "target_lang": "zh-Hans",
           "mode": "preview", "qps": 2, "pool": 2,
           "callback_label": "TEST_IDENTITY_FIXTURE", "timeout_s": 600,
           "provenance": {"provider_model": "TEST_IDENTITY_FIXTURE"}}
    if args.page is not None:
        job["pages"] = {"start": args.page, "end": args.page}
    job_file = f"private/requests/{args.job_id}.json"
    write_private_json(root / job_file, job)
    try:
        return supervise(root, job_file, 2)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    raise SystemExit(main())
