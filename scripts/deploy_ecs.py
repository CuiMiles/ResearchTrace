#!/usr/bin/env python3
"""Deploy ResearchTrace through the existing node01 Workbench session.

No passwords, signing URLs, provider keys or Workbench credential files are read
by this script. Workbench authenticates using its existing private configuration.
An exec command must come from a reviewed operator-owned file, never model output
or uploaded paper content. This is deployment tooling, not a product Agent tool.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
import uuid

ROOT = "/opt/researchtrace"


def sanitise(text: str) -> str:
    text = re.sub(r"https?://[^\s\"'<>]+\?[^\s\"'<>]+", "[private signed URL omitted]", text)
    text = re.sub(r"AIza[\w-]{20,}", "[key omitted]", text)
    text = re.sub(r"(?im)^.*(?:authorization:|x-goog-api-key:|secretaccesskey|accesskeysecret).*$",
                  "[private credential line omitted]", text)
    return text


class Workbench:
    def __init__(self, relay="10.184.17.163", instance="i-bp13r66a7w9gwi5fs48n",
                 binary="/home/CuiMinghao/.local/bin/workbench"):
        self.relay, self.instance, self.binary = relay, instance, binary

    def ssh(self, args: list[str], timeout=100):
        result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                                 self.relay, shlex.join(args)], capture_output=True, text=True,
                                timeout=timeout)
        if result.returncode:
            raise RuntimeError(sanitise(result.stderr + result.stdout)[-2000:])
        return sanitise(result.stdout)

    def command(self, command: str):
        return self.ssh([self.binary, "exec", "-i", self.instance, "--timeout", "30", "-c", command])

    def upload(self, source: Path, remote: str):
        target = PurePosixPath(remote)
        if not target.is_relative_to(ROOT) or ".." in target.parts:
            raise ValueError("Uploads are confined to /opt/researchtrace")
        if not source.is_file() or source.is_symlink():
            raise ValueError("A regular local source file is required")
        # Temporary relay folder has no predictable filename and no public server.
        stage = "/tmp/researchtrace-deploy-" + uuid.uuid4().hex
        self.ssh(["install", "-d", "-m", "0700", stage])
        try:
            result = subprocess.run(["scp", "-q", "-o", "BatchMode=yes", str(source.resolve()),
                                     self.relay + ":" + stage + "/payload"], capture_output=True,
                                    text=True, timeout=300)
            if result.returncode:
                raise RuntimeError("Relay transfer failed; no credential output retained")
            # Upload output may contain signed OSS URLs; never print or persist it.
            self.ssh([self.binary, "upload", stage + "/payload", str(target), "-i", self.instance, "-f"], timeout=360)
        finally:
            self.ssh(["rm", "-rf", "--", stage])
        return json.dumps({"status": "PASS", "uploaded": str(target), "bytes": source.stat().st_size})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relay", default="10.184.17.163")
    parser.add_argument("--instance", default="i-bp13r66a7w9gwi5fs48n")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("inventory")
    execute = sub.add_parser("exec")
    execute.add_argument("--file", type=Path, required=True)
    upload = sub.add_parser("upload")
    upload.add_argument("source", type=Path)
    upload.add_argument("remote")
    args = parser.parse_args()
    wb = Workbench(args.relay, args.instance)
    try:
        if args.action == "upload":
            print(wb.upload(args.source, args.remote))
        elif args.action == "exec":
            print(wb.command(args.file.read_text()), end="")
        else:
            print(wb.command("hostname; uname -sr; free -m; df -h /; ss -lnt; "
                             "command -v docker; docker compose version 2>/dev/null; "
                             "ls -l /etc/nginx/sites-enabled; getent ahostsv4 researchtrace.sluna.xyz"))
    except Exception as exc:
        # Intentionally omit traceback/command argv; they can contain private data.
        print(sanitise(str(exc)), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
