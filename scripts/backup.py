#!/usr/bin/env python3
"""Private, consistent SQLite + files backup; no application imports or credentials.

A separate BEGIN IMMEDIATE connection briefly excludes application writers while
the SQLite backup API and file copy run. Readers continue in WAL mode. A backup
that exceeds its bounded writer-pause window is discarded, never published.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import time


DATABASE = "researchtrace.sqlite"
SKIP_DIRS = {"run_locks", "cache", "matplotlib", "backups", "__pycache__"}


def document_relative(name: str, data: Path) -> Path:
    path=Path(name)
    if not path.is_absolute():
        if '..' in path.parts:raise ValueError('Document path escapes data root')
        return path
    if path.is_relative_to('/app/data'):
        relative=path.relative_to('/app/data')
        if '..' in relative.parts:raise ValueError('Document path escapes container data root')
        return relative
    return path.resolve().relative_to(data)


def _private_copy(source: Path, target: Path, deadline: float):
    if time.monotonic() >= deadline:
        raise TimeoutError("Backup exceeded maximum writer-pause window")
    mode = source.lstat().st_mode
    if stat.S_ISLNK(mode):
        raise ValueError("Symbolic links are not allowed in a private backup")
    if stat.S_ISDIR(mode):
        target.mkdir(mode=0o700)
        for child in sorted(source.iterdir()):
            if child.name not in SKIP_DIRS:
                _private_copy(child, target / child.name, deadline)
    elif stat.S_ISREG(mode):
        if source.name.endswith((".sock", ".lock", ".log", ".pid", ".tmp", "-wal", "-shm", "-journal")):
            return
        with source.open("rb") as src, target.open("xb") as dst:
            os.chmod(target, 0o600)
            while chunk := src.read(1024 * 1024):
                if time.monotonic() >= deadline:
                    raise TimeoutError("Backup exceeded maximum writer-pause window")
                dst.write(chunk)
            dst.flush()
            os.fsync(dst.fileno())


def backup(data: Path, destination: Path, env: Path | None = None,
           retain: int = 7, max_pause: float = 20) -> Path:
    data, destination = data.resolve(), destination.resolve()
    if destination == data or destination.is_relative_to(data):
        raise ValueError("Backup destination must be outside the live data directory")
    if not (data / DATABASE).is_file():
        raise FileNotFoundError("Application SQLite database is missing")
    if retain < 1 or max_pause <= 0:
        raise ValueError("Retention and maximum pause must be positive")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.stat().st_mode & 0o077:
        raise PermissionError("Backup destination must be private (mode 700)")
    with (destination / ".backup.lock").open("a+") as lock:
        os.chmod(destination / ".backup.lock", 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        staging = Path(tempfile.mkdtemp(prefix=".incomplete-", dir=destination))
        try:
            started = time.monotonic()
            deadline = started + max_pause
            with closing(sqlite3.connect(data / DATABASE, timeout=5)) as gate:
                gate.execute("BEGIN IMMEDIATE")
                with closing(sqlite3.connect(f"file:{data / DATABASE}?mode=ro", uri=True)) as src:
                    with closing(sqlite3.connect(staging / DATABASE)) as target:
                        def progress(*_):
                            if time.monotonic() >= deadline:
                                raise TimeoutError("SQLite backup exceeded maximum writer-pause window")
                        src.backup(target, pages=256, progress=progress)
                        target.commit()
                os.chmod(staging / DATABASE, 0o600)
                for source in sorted(data.iterdir()):
                    if source.name == DATABASE or source.name in SKIP_DIRS:
                        continue
                    _private_copy(source, staging / source.name, deadline)
                gate.rollback()
            with closing(sqlite3.connect(staging / DATABASE)) as verify:
                if verify.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("SQLite integrity check failed")
                tables = {r[0] for r in verify.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                counts = {name: verify.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                          for name in ("versions", "blocks", "quota", "runs") if name in tables}
                if "versions" in tables:
                    for (name,) in verify.execute("SELECT path FROM versions"):
                        try:
                            relative = document_relative(name,data)
                        except ValueError:
                            raise ValueError("A document path is outside the live data directory") from None
                        if not (staging / relative).is_file():
                            raise FileNotFoundError("A referenced PDF is missing from the backup")
            if env is not None:
                if env.is_symlink() or env.stat().st_mode & 0o077:
                    raise PermissionError("Private environment file must have mode 600")
                _private_copy(env, staging / "runtime.env", time.monotonic() + 5)
            summary = {"status": "PASS", "created": datetime.now(timezone.utc).isoformat(),
                       "source_data": str(data), "sqlite_integrity": "ok", "row_counts": counts,
                       "writer_pause_seconds": round(time.monotonic() - started, 3),
                       "environment_included": env is not None, "quota_reset": False}
            (staging / "backup.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
            os.chmod(staging / "backup.json", 0o600)
            name = "backup-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            final = destination / name
            staging.rename(final)
            # Only remove directories carrying our own valid manifest; never unrelated files.
            backups = sorted(p for p in destination.glob("backup-*")
                             if p.is_dir() and not p.is_symlink() and (p / "backup.json").is_file())
            for old in backups[:-retain]:
                shutil.rmtree(old)
            return final
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise


def restore(snapshot: Path, destination: Path):
    """Restore only into a fresh location. Relocate copied PDF paths, retain quota."""
    snapshot, destination = snapshot.resolve(), destination.resolve()
    if destination.exists():
        raise FileExistsError("Restore destination must not exist")
    metadata = json.loads((snapshot / "backup.json").read_text())
    old_data = Path(metadata["source_data"])
    destination.mkdir(mode=0o700, parents=True)
    try:
        for source in snapshot.iterdir():
            if source.name not in {"backup.json", "runtime.env"}:
                _private_copy(source, destination / source.name, time.monotonic() + 300)
        with closing(sqlite3.connect(destination / DATABASE)) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "versions" in tables:
                for vid, name in conn.execute("SELECT id,path FROM versions").fetchall():
                    relative = document_relative(name,old_data)
                    if not (destination / relative).is_file():
                        raise FileNotFoundError("Restored PDF missing")
                    conn.execute("UPDATE versions SET path=? WHERE id=?", (str(destination / relative), vid))
            conn.commit()
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Restored SQLite integrity check failed")
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--env", type=Path)
    parser.add_argument("--retain", type=int, default=7)
    parser.add_argument("--max-pause", type=float, default=20)
    parser.add_argument("--restore", type=Path, metavar="SNAPSHOT")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.restore:
            restore(args.restore, args.destination)
            print(json.dumps({"status": "PASS", "restored": True, "quota_reset": False}))
        else:
            if args.data is None:
                parser.error("--data is required for backup")
            target = backup(args.data, args.destination, args.env, args.retain, args.max_pause)
            print(json.dumps({"status": "PASS", "backup": target.name, "quota_reset": False}))
    except Exception as exc:
        # Exception messages may contain application paths: do not log private content.
        print(json.dumps({"status": "FAIL", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
