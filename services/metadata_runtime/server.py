"""Small authenticated loopback gateway over an isolated CRF GROBID process.

Python 3.6+ stdlib; no GPU, model API, proxy forwarding, training/admin routes,
database or user-controlled backend. Run via scripts/provision_grobid.py.
"""
import argparse
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import socket
import stat
import threading
import time
from socketserver import ThreadingMixIn
from urllib.parse import urlsplit

MAX_REQUEST = 64 * 1024 * 1024 + 65536
MAX_RESPONSE = 16 * 1024 * 1024
REJECT_DRAIN_BYTES = 1024 * 1024
REJECT_DRAIN_SECONDS = 2
ALLOWED = {"/api/processFulltextDocument", "/api/processHeaderDocument"}
ACTIVE = threading.BoundedSemaphore(1)
CONNECTIONS = threading.BoundedSemaphore(8)


class BoundedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

    def process_request(self, request, address):
        if not CONNECTIONS.acquire(False):
            request.close()
            return
        try:
            super().process_request(request, address)
        except BaseException:
            CONNECTIONS.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            CONNECTIONS.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "ResearchTraceMetadata/1"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)
        def expire():
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self._deadline = threading.Timer(225, expire)
        self._deadline.daemon = True
        self._deadline.start()

    def finish(self):
        self._deadline.cancel()
        super().finish()

    def log_message(self, *_):
        # No authorization headers, filenames, XML or query values in access logs.
        pass

    def _send(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _error(self, status, code):
        self._send(status, json.dumps({"error": code}).encode())
        if self.command == "POST":
            self._drain_rejected_body()

    def _drain_rejected_body(self):
        # Closing with unread data resets the socket and can destroy the response
        # before the client reads it. Discard a bounded amount, then let it close.
        deadline = time.monotonic() + REJECT_DRAIN_SECONDS
        remaining = REJECT_DRAIN_BYTES
        try:
            self.connection.shutdown(socket.SHUT_WR)
            while remaining > 0:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self.connection.settimeout(left)
                chunk = self.rfile.read1(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
        except OSError:
            pass

    def _authorized(self):
        expected = "Bearer " + self.server.token
        return hmac.compare_digest(self.headers.get("Authorization", "").encode(), expected.encode())

    def do_GET(self):
        if not self._authorized():
            return self._error(401, "unauthorized")
        if self.path != "/healthz":
            return self._error(404, "route_not_allowed")
        upstream = http.client.HTTPConnection("127.0.0.1", self.server.backend_port, timeout=3)
        try:
            upstream.request("GET", "/api/isalive")
            response = upstream.getresponse()
            ready = response.status == 200 and response.read(64).strip().lower() == b"true"
            self._send(200 if ready else 503, json.dumps({"status": "upstream_alive" if ready else "not_ready",
                       "version": "0.9.1", "engine": "wapiti_cpu", "ocr": False,
                       "inference_verified": False,
                       "source_commit": "523bb8e97f357e93682dc4eaa6d22faa8b5b93de"}).encode())
        except OSError:
            self._error(503, "upstream_unavailable")
        finally:
            upstream.close()

    def do_POST(self):
        if not self._authorized():
            return self._error(401, "unauthorized")
        if self.path not in ALLOWED:
            return self._error(404, "route_not_allowed")
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Encoding", "identity") != "identity":
            return self._error(400, "unsupported_encoding")
        try:
            if len(self.headers.get_all("Content-Length", [])) != 1:
                raise ValueError
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= MAX_REQUEST:
                raise ValueError
        except ValueError:
            return self._error(413, "request_size_limit")
        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith("multipart/form-data; boundary=") or len(ctype) > 200:
            return self._error(400, "expected_multipart_pdf")
        if not ACTIVE.acquire(False):
            return self._error(429, "metadata_worker_busy")
        upstream = None
        started = time.monotonic()
        try:
            chunks, received = [], 0
            while received < length:
                if time.monotonic() - started > 45:
                    raise TimeoutError
                chunk = self.rfile.read1(min(65536, length - received))
                if not chunk:
                    raise ValueError("truncated")
                chunks.append(chunk)
                received += len(chunk)
            upstream = http.client.HTTPConnection("127.0.0.1", self.server.backend_port, timeout=150)
            upstream.request("POST", self.path, body=b"".join(chunks),
                             headers={"Content-Type": ctype, "Accept": "application/xml", "Connection": "close"})
            del chunks
            response = upstream.getresponse()
            if response.status == 204:
                return self._error(422, "no_extractable_text_metadata")
            if response.status != 200:
                return self._error(response.status if response.status in (204, 400, 413, 503) else 502,
                                   "grobid_extraction_failed")
            response_type = response.getheader("Content-Type", "").split(";", 1)[0]
            if response_type not in ("application/xml", "text/xml", "application/tei+xml"):
                return self._error(502, "upstream_not_xml")
            body = bytearray()
            while True:
                if time.monotonic() - started > 210:
                    raise TimeoutError
                if response.fp:
                    response.fp.raw._sock.settimeout(min(30, 210 - (time.monotonic() - started)))
                chunk = response.read1(min(65536, MAX_RESPONSE + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > MAX_RESPONSE:
                    return self._error(502, "upstream_response_limit")
            self._send(200, bytes(body), "application/xml; charset=utf-8")
        except (OSError, ValueError, http.client.HTTPException):
            try:
                self._error(504, "metadata_transport_failed")
            except OSError:
                pass
        finally:
            if upstream:
                upstream.close()
            ACTIVE.release()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--token-file", required=True)
    p.add_argument("--port", type=int, default=18072)
    p.add_argument("--backend-port", type=int, default=18070)
    args = p.parse_args()
    token_path = Path(args.token_file)
    info = token_path.stat()
    if info.st_mode & 0o077 or info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode):
        raise SystemExit("Token file must be private and operator-owned")
    token = token_path.read_text(encoding="ascii").strip()
    if not 16 <= len(token) <= 1024 or any(c.isspace() for c in token):
        raise SystemExit("Invalid token file")
    server = BoundedServer(("127.0.0.1", args.port), Handler)
    server.token = token
    server.backend_port = args.backend_port
    print(json.dumps({"event": "metadata_gateway_started", "host": "127.0.0.1", "port": args.port}), flush=True)
    server.serve_forever(poll_interval=.5)


if __name__ == "__main__":
    main()
