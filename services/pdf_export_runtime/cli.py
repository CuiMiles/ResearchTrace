"""Fixed CLI; JSON is data, never shell or a provider configuration."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from .contract import ContractError, load_job, private_path, sha256_file, write_private_json


def child_environment(root: Path, directory: Path) -> dict[str, str]:
    # No parent API keys, global proxy or model configuration reaches the engine.
    package_root = Path(__file__).resolve().parents[2]
    env = {"PATH": str(root / ".venv/bin") + ":/usr/bin:/bin", "HOME": str(directory / "home"),
           "LANG": "C.UTF-8", "PYTHONPATH": str(package_root), "PYTHONUNBUFFERED": "1",
           "CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2",
           "MKL_NUM_THREADS": "2", "NUMEXPR_NUM_THREADS": "2", "RAYON_NUM_THREADS": "2",
           "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    return env


def python_command(root: Path) -> list[str]:
    """Optional private old-host glibc loader, all paths pinned by provisioning."""
    config = root / "runtime/python-command.json"
    if config.exists():
        obj = json.loads(config.read_text())
        loader = (root / obj["loader"]).resolve(strict=True)
        loader.relative_to(root.resolve())
        libs = []
        for relative in obj["library_paths"]:
            path = (root / relative).resolve(strict=True)
            path.relative_to(root.resolve())
            libs.append(str(path))
        # Conda's Python executable locates its original OpenSSL via rpath.
        return [str(loader), "--library-path", ":".join(libs), str(root / ".venv/bin/python")]
    return [str(root / ".venv/bin/python")]


def stop_owned(process: subprocess.Popen):
    # This Popen belongs to this invocation and is deliberately unreaped until
    # poll confirms exit. No persisted arbitrary PID can become a kill target.
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
        except ProcessLookupError:
            process.wait(timeout=10)


def supervise(root: Path, job_file: str, max_pages: int) -> int:
    job = load_job(root, job_file)
    directory = job.directory
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / "run.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ContractError("job_already_running") from None
        binding = directory / "binding.json"
        if binding.exists() and json.loads(binding.read_text()).get("contract_sha256") != job.contract_sha256:
            raise ContractError("job_id_reuse_with_different_contract")
        write_private_json(binding, {"contract_sha256": job.contract_sha256})
        manifest_path = directory / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            if (manifest.get("status") != "PASS" or manifest.get("job_id") != job.job_id
                    or manifest.get("contract_sha256") != job.contract_sha256
                    or len(manifest.get("artifacts", [])) != 2
                    or {entry.get("role") for entry in manifest["artifacts"]} != {"mono", "dual"}):
                raise ContractError("cached_manifest_incomplete_or_incompatible")
            for artifact in manifest.get("artifacts", []):
                path = private_path(root, artifact["path"])
                if sha256_file(path) != artifact["sha256"]:
                    raise ContractError("cached_artifact_hash_mismatch")
            print(json.dumps({"status": "PASS", "job_id": job.job_id, "cached": True,
                              "manifest": manifest_path.relative_to(root).as_posix()}))
            return 0
        if (directory / "CANCEL_REQUESTED").exists():
            raise ContractError("job_cancelled_new_job_required")
        (directory / "home").mkdir(mode=0o700, exist_ok=True)
        command = python_command(root) + ["-m", "services.pdf_export_runtime.cli", "_engine", "--root", str(root),
                                         "--job", job_file, "--max-pages", str(max_pages)]
        cancelled = False

        def cancel(signum, frame):
            nonlocal cancelled
            cancelled = True

        old_handlers = {s: signal.signal(s, cancel) for s in (signal.SIGINT, signal.SIGTERM)}
        process = None
        started = time.monotonic()
        try:
            process = subprocess.Popen(command, cwd=directory, env=child_environment(root, directory),
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       start_new_session=True)
            while process.poll() is None:
                if cancelled or (directory / "CANCEL_REQUESTED").exists() or time.monotonic() - started > job.timeout_s:
                    stop_owned(process)
                    status = "CANCELLED" if cancelled or (directory / "CANCEL_REQUESTED").exists() else "TIMEOUT"
                    write_private_json(directory / "supervisor.json", {"status": status, "owned_child_pid": process.pid})
                    print(json.dumps({"status": "FAIL", "reason": status, "job_id": job.job_id}))
                    return 1
                time.sleep(0.2)
            code = process.returncode
            print(json.dumps({"status": "PASS" if code == 0 and manifest_path.exists() else "FAIL", "job_id": job.job_id,
                              "exit_code": code, "manifest": manifest_path.relative_to(root).as_posix() if manifest_path.exists() else None}))
            return 0 if code == 0 and manifest_path.exists() else 1
        finally:
            if process is not None:
                stop_owned(process)
            for s, handler in old_handlers.items():
                signal.signal(s, handler)


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("run", "cancel", "_engine"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--job")
    parser.add_argument("--job-id")
    parser.add_argument("--max-pages", type=int, default=2)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        if not 1 <= args.max_pages <= 10000:
            raise ContractError("invalid_operator_page_limit")
        if args.command == "cancel":
            if not args.job_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", args.job_id):
                raise ContractError("invalid_job_id")
            directory = private_path(root, f"private/jobs/{args.job_id}")
            write_private_json(directory / "CANCEL_REQUESTED", {"cancel": True})
            print(json.dumps({"status": "CANCEL_REQUESTED", "job_id": args.job_id}))
            return 0
        if not args.job:
            raise ContractError("missing_job_file")
        if args.command == "_engine":
            os.nice(10)
            from .engine import run_engine
            return run_engine(load_job(root, args.job), args.max_pages)
        return supervise(root, args.job, args.max_pages)
    except (ContractError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "FAIL", "error_type": type(exc).__name__,
                          "error_code": str(exc) if isinstance(exc, ContractError) else "runtime_input_rejected"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
