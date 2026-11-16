"""TEST_IDENTITY_FIXTURE: real engine smoke only, never translation quality."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .contract import read_token, write_private_json


def create_server(token_file: Path, statistics: Path, port=0):
    token = read_token(token_file)
    lock = threading.Lock()
    stats = {"callback_label": "TEST_IDENTITY_FIXTURE", "provider_calls": 0, "translation_quality": "NOT RUN", "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != "/translate" or not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.send_error(403)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 1 <= size <= 256 * 1024:
                    raise ValueError
                obj = json.loads(self.rfile.read(size))
                if set(obj) != {"text", "source_lang", "target_lang", "job_id"} or not isinstance(obj["text"], str):
                    raise ValueError
            except (ValueError, TypeError):
                self.send_error(400)
                return
            with lock:
                stats["requests"].append({"job_id": obj["job_id"], "source_lang": obj["source_lang"], "target_lang": obj["target_lang"],
                    "text_sha256": hashlib.sha256(obj["text"].encode()).hexdigest(), "characters": len(obj["text"])})
                write_private_json(statistics, stats)
            body = json.dumps({"translation": obj["text"]}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--statistics", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    server = create_server(args.token_file, args.statistics, args.port)
    print(json.dumps({"callback_label": "TEST_IDENTITY_FIXTURE", "url": f"http://127.0.0.1:{server.server_port}/translate"}), flush=True)
    server.serve_forever()
