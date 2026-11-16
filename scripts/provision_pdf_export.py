#!/usr/bin/env python3
"""Provision only this optional remote CPU runtime, never the app environment."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def digest(path, algorithm="sha256"):
    h = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def provision(root, base_python, sysroot_source=None, *, lock_only=False):
    os.umask(0o077)
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for child in ("private", "logs", "assets", "runtime", "cache", "source"):
        (root / child).mkdir(mode=0o700, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD"))}
    env.update({"HOME": str(root / "private/provision-home"), "XDG_CACHE_HOME": str(root / "cache"),
                "PIP_CACHE_DIR": str(root / "cache/pip"), "CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "2"})
    Path(env["HOME"]).mkdir(mode=0o700, exist_ok=True)
    # All large downloads stay on the remote host's already configured relay.
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[name] = "http://127.0.0.1:7890"
    env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost,::1"
    env["CARGO_HOME"] = str(root / "cache/cargo")
    env["RUSTUP_HOME"] = str(root / "cache/rustup")
    if not (root / ".venv/bin/python").exists():
        subprocess.run([str(base_python.resolve(strict=True)), "-m", "venv", str(root / ".venv")], check=True, env=env)
    if sysroot_source:
        source = sysroot_source.resolve(strict=True)
        target = root / "runtime/sysroot"
        if not target.exists():
            shutil.copytree(source, target, symlinks=True)
        # Use the regular loader, not lib64's absolute symlink to the host glibc.
        loader = target / "lib/x86_64-linux-gnu/ld-linux-x86-64.so.2"
        if loader.is_symlink() or not loader.is_file():
            raise RuntimeError("private_compat_loader_missing")
        config = {"loader": loader.relative_to(root).as_posix(), "library_paths": [
            "runtime/python-libs", "runtime/sysroot/lib/x86_64-linux-gnu", "runtime/sysroot/usr/lib/x86_64-linux-gnu"]}
        # Newer conda Python/ICU and PyMuPDF must agree on the C++ ABI. Copy
        # only these redistributable libraries; never change the source env.
        python_libs = root / "runtime/python-libs"
        python_libs.mkdir(exist_ok=True)
        base_lib = base_python.resolve(strict=True).parent.parent / "lib"
        for name in ("libstdc++.so.6", "libgcc_s.so.1"):
            origin = base_lib / name
            if origin.exists():
                shutil.copy2(origin.resolve(strict=True), python_libs / name)
        (root / "runtime/python-command.json").write_text(json.dumps(config, indent=2))
    package_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(package_root))
    from services.pdf_export_runtime.cli import python_command
    command = python_command(root)
    env["PYTHONPATH"] = str(package_root)

    def run(arguments, log):
        with (root / "logs" / log).open("ab") as output:
            subprocess.run(command + arguments, env=env, stdout=output, stderr=subprocess.STDOUT, check=True)

    lock = package_root / "services/pdf_export_runtime/requirements.lock"
    if not lock_only:
        spec = ["--require-hashes", "-r", str(lock)] if lock.exists() else ["pdf2zh-next==2.10.2", "babeldoc==0.7.1"]
        run(["-m", "pip", "install", "--only-binary=:all:", "--report", str(root / "private/install-report.json"), *spec], "provision-install.log")
    run(["-m", "pip", "check"], "provision-pip-check.log")
    # Freeze and retain exact wheels: both names/versions and SHA256 are locked.
    frozen = subprocess.check_output(command + ["-m", "pip", "freeze"], env=env).decode()
    freeze = root / "source/requirements.freeze"
    freeze.write_text(frozen)
    wheels = root / "source/wheelhouse"
    wheels.mkdir(exist_ok=True)
    run(["-m", "pip", "download", "--only-binary=:all:", "--no-deps", "-r", str(freeze), "--dest", str(wheels)], "provision-lock-wheels.log")
    run(["-m", "services.pdf_export_runtime.provision_assets", "--root", str(root)], "provision-assets.log")
    import zipfile
    locked = []
    wheel_manifest = []
    for path in sorted(wheels.glob("*.whl")):
        with zipfile.ZipFile(path) as archive:
            metadata = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
            import email.parser
            meta = email.parser.Parser().parsestr(archive.read(metadata).decode())
        sha = digest(path)
        locked.append(f"{meta['Name']}=={meta['Version']} --hash=sha256:{sha}")
        wheel_manifest.append({"file": path.name, "sha256": sha, "bytes": path.stat().st_size})
    (root / "source/requirements.lock").write_text("# Remote Linux x86_64 / Python 3.11; use --require-hashes\n" + "\n".join(locked) + "\n")
    (root / "source/wheels.lock.json").write_text(json.dumps(wheel_manifest, indent=2))
    compat = []
    if (root / "runtime/sysroot").exists():
        for path in sorted((root / "runtime").rglob("*")):
            if path.name in {"compat.lock.json", "python-command.json"}:
                continue
            if path.is_file() and not path.is_symlink():
                compat.append({"path": path.relative_to(root).as_posix(), "sha256": digest(path), "bytes": path.stat().st_size})
        (root / "runtime/compat.lock.json").write_text(json.dumps(compat, indent=2))
    result = {"status": "PASS", "root": str(root), "python": subprocess.check_output(command + ["-c", "import platform;print(platform.python_version())"], env=env).decode().strip(),
              "wheel_count": len(wheel_manifest), "dependency_lock_sha256": digest(root / "source/requirements.lock"),
              "asset_lock_sha256": digest(root / "assets/assets.lock.json"), "compat_file_count": len(compat),
              "device": "CPU", "provider_calls": 0}
    (root / "source/provision-result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--sysroot-source", type=Path)
    parser.add_argument("--lock-only", action="store_true", help="Use the already installed private venv; still verify/download locked wheels and assets")
    args = parser.parse_args()
    provision(args.root, args.python, args.sysroot_source, lock_only=args.lock_only)
