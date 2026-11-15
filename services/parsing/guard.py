"""Linux/WSL GPU accounting and termination confined to a spawned session."""
import csv
import io
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time


def _nvidia_smi():
    found = shutil.which('nvidia-smi')
    if found:
        return found
    for candidate in ('/usr/bin/nvidia-smi', '/usr/lib/wsl/lib/nvidia-smi'):
        if Path(candidate).is_file():
            return candidate
    return 'nvidia-smi'


def _query(fields, kind='gpu'):
    result = subprocess.run(
        [_nvidia_smi(), f'--query-{kind}={fields}', '--format=csv,noheader,nounits'],
        capture_output=True, text=True, timeout=3, check=True,
    )
    return list(csv.reader(io.StringIO(result.stdout)))


def gpu_snapshot():
    rows = _query('index,uuid,memory.free,memory.total')
    result = []
    for row in rows:
        if len(row) != 4:
            raise ValueError('GPU memory telemetry unavailable')
        index, uid, free, total = (v.strip() for v in row)
        free, total = int(free), int(total)
        if not uid.startswith('GPU-') or not 0 <= free <= total:
            raise ValueError('GPU memory telemetry invalid')
        result.append({'index': index, 'uuid': uid, 'free': free, 'total': total})
    if not result:
        raise ValueError('GPU memory telemetry unavailable')
    return result


def session_pids(session_id):
    """Include grandchildren even after the direct runner exits (Linux /proc)."""
    pids = set()
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            # comm can contain spaces or ')'; stat fields after final ')' are stable.
            fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[3]) == session_id:
                pids.add(int(entry.name))
        except (OSError, ValueError, IndexError):
            continue
    return pids


def own_gpu_usage(session_id, gpu_uuid):
    """WSL NVML commonly reports N/A or host PIDs: never treat these as zero."""
    rows = _query('pid,gpu_uuid,used_memory', 'compute-apps')
    owned = session_pids(session_id)
    used = 0
    matched = False
    for row in rows:
        if len(row) != 3:
            raise ValueError('Per-process GPU accounting unavailable')
        pid, uid, memory = (v.strip() for v in row)
        if uid != gpu_uuid:
            continue
        if not pid.isdecimal() or not memory.isdecimal():
            raise ValueError('Per-process GPU accounting unavailable (WSL/NVML)')
        if int(pid) in owned:
            used += int(memory)
            matched = True
        elif not Path('/proc', pid).exists():
            raise ValueError('GPU PID cannot be mapped to this namespace (WSL/NVML)')
    return used, matched


def choose_gpu(reserve_mib, budget_mib):
    if reserve_mib < 2048 or budget_mib < 256:
        raise ValueError('GPU requires reserve >=2048 MiB and budget >=256 MiB')
    # Keep a margin beyond the minimum reserve; the budget is never silently raised.
    candidates = [g for g in gpu_snapshot() if g['free'] >= reserve_mib + budget_mib + 256]
    if not candidates:
        raise ValueError('GPU free memory insufficient for reserve plus requested budget')
    return max(candidates, key=lambda g: g['free'])


def stop_session(proc, grace=1.0):
    """Only call for Popen(..., start_new_session=True) children we created.

    Signal the session's groups before reaping the leader, preventing a recycled
    group ID. Repeat with SIGKILL even if the leader exited on SIGTERM.
    """
    if proc.pid == os.getpgrp():
        raise ValueError('Refusing to signal broker process group')
    for sig in (signal.SIGTERM, signal.SIGKILL):
        # Re-enumerate after TERM: the leader may exit first or a native worker
        # may have formed another group in our session while unwinding.
        members = session_pids(proc.pid)
        groups = set()
        for pid in members:
            try:
                if os.getsid(pid) == proc.pid:
                    groups.add(os.getpgid(pid))
            except ProcessLookupError:
                pass
        # No unconditional killpg(proc.pid): once reaped, that ID could be
        # reused by another process. Only groups with current session members.
        for group in groups:
            try:
                os.killpg(group, sig)
            except ProcessLookupError:
                pass
        if sig == signal.SIGTERM and members:
            time.sleep(grace)
    proc.wait(timeout=5)
