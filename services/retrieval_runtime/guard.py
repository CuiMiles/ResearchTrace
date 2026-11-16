"""Resource telemetry and signals limited to our unreaped child session."""
import csv
import fcntl
import io
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
_nvml=None
_stop_lock=threading.Lock()


def query(fields, kind="gpu"):
    global _nvml
    try:
        import pynvml
    except ImportError:
        pynvml=None
    if pynvml is not None:
        try:
            if _nvml is None:pynvml.nvmlInit();_nvml=pynvml
            rows=[]
            for index in range(_nvml.nvmlDeviceGetCount()):
                handle=_nvml.nvmlDeviceGetHandleByIndex(index)
                uid=_nvml.nvmlDeviceGetUUID(handle)
                if isinstance(uid,bytes):uid=uid.decode()
                if kind=='gpu' and fields=='index,uuid,memory.free,memory.total':
                    info=_nvml.nvmlDeviceGetMemoryInfo(handle)
                    rows.append([str(index),uid,str(info.free//1024**2),str(info.total//1024**2)])
                elif kind=='compute-apps' and fields=='pid,gpu_uuid,used_memory':
                    for proc in _nvml.nvmlDeviceGetComputeRunningProcesses(handle):
                        used=proc.usedGpuMemory
                        if used is None or used>=2**63:raise RuntimeError('Per-PID NVML memory unavailable')
                        rows.append([str(proc.pid),uid,str((used+1024**2-1)//1024**2)])
                else:raise ValueError('Unknown telemetry query')
            return rows
        except pynvml.NVMLError as error:
            raise RuntimeError('NVML telemetry unavailable: '+type(error).__name__) from None
    command = shutil.which("nvidia-smi") or "/usr/lib/wsl/lib/nvidia-smi"
    result = subprocess.run([command, "--query-" + kind + "=" + fields,
                             "--format=csv,noheader,nounits"],
                            capture_output=True, text=True, timeout=10, check=True)
    return [[part.strip() for part in row] for row in csv.reader(io.StringIO(result.stdout))]


def gpus():
    result = []
    for row in query("index,uuid,memory.free,memory.total"):
        if len(row) != 4 or not row[2].isdigit() or not row[3].isdigit():
            raise RuntimeError("GPU memory telemetry unavailable")
        result.append({"index": int(row[0]), "uuid": row[1], "free_mib": int(row[2]), "total_mib": int(row[3])})
    return result


def choose_gpus(budget_mib, reserve_mib, count=1):
    if reserve_mib < 2048 or budget_mib < 1024:
        raise ValueError("GPU reserve must be >=2048 MiB; budget >=1024 MiB")
    candidates = [g for g in gpus() if g["free_mib"] >= budget_mib + reserve_mib + 256]
    if len(candidates) < count:
        raise RuntimeError("Insufficient free GPU memory for whole job budget plus reserve")
    return sorted(candidates, key=lambda item: item["free_mib"], reverse=True)[:count]


def choose_gpu(budget_mib, reserve_mib):
    return choose_gpus(budget_mib, reserve_mib)[0]


def claim_gpus(root,budget_mib,reserve_mib,count):
    """Coordinate only our brokers, including CUDA's cold allocation interval."""
    if reserve_mib<2048:raise ValueError('Reserve must be at least2048MiB')
    directory=Path(root)/'private/gpu-slots';directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    selected=[];handles=[]
    for gpu in sorted(gpus(),key=lambda item:item['free_mib'],reverse=True):
        if gpu['free_mib']<budget_mib+reserve_mib+256:continue
        handle=(directory/(gpu['uuid']+'.lock')).open('a')
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:handle.close();continue
        handles.append(handle);selected.append(gpu)
        if len(selected)==count:return selected,handles
    for handle in handles:handle.close()
    raise RuntimeError('No unclaimed project GPU slots meet the live budget and reserve')


def members(session_id):
    result = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if fields[0] not in {'Z','X'} and int(fields[3]) == session_id:
                result.add(int(entry.name))
        except (OSError, ValueError, IndexError):
            continue
    return result


def memory_available_mib():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    raise RuntimeError("Host memory telemetry unavailable")


def sample(session_id, gpu=None):
    owned = members(session_id)
    rss_kib = 0
    for pid in owned:
        try:
            for line in Path("/proc", str(pid), "status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    rss_kib += int(line.split()[1])
        except FileNotFoundError:
            continue
    result = {"time": time.time(), "pids": sorted(owned), "rss_mib": rss_kib // 1024,
              "host_available_mib": memory_available_mib(), "gpu_used_mib": 0}
    if gpu is not None:
        selected = [gpu] if isinstance(gpu, dict) else gpu
        telemetry = {item["uuid"]: item for item in gpus()}
        per_gpu = {}
        for item in selected:
            if item["uuid"] not in telemetry:
                raise RuntimeError("Selected GPU disappeared from telemetry")
            per_gpu[item["uuid"]] = {"uuid": item["uuid"], "index": item.get("index"),
                                     "free_mib": telemetry[item["uuid"]]["free_mib"], "used_mib": 0}
        for row in query("pid,gpu_uuid,used_memory", "compute-apps"):
            if len(row) != 3 or not row[0].isdigit():
                raise RuntimeError("Per-PID GPU accounting unavailable")
            if int(row[0]) in owned:
                if not row[2].isdigit() or row[1] not in per_gpu:
                    raise RuntimeError("Own GPU accounting unavailable or unexpected GPU")
                result["gpu_used_mib"] += int(row[2])
                per_gpu[row[1]]["used_mib"] += int(row[2])
            elif row[1] in per_gpu and not row[2].isdigit():
                raise RuntimeError("GPU accounting unavailable; fail closed")
        result["per_gpu"] = list(per_gpu.values())
        result["gpu_free_mib"] = min(item["free_mib"] for item in per_gpu.values())
    return result


def violation(sample_data, gpu_budget_mib, gpu_reserve_mib, host_budget_mib, host_reserve_mib):
    if sample_data["rss_mib"] > host_budget_mib:
        return "Own process tree exceeded host RSS budget"
    if sample_data["host_available_mib"] < host_reserve_mib:
        return "Host available memory below reserve"
    card_used = max((item["used_mib"] for item in sample_data.get("per_gpu", [])),
                    default=sample_data["gpu_used_mib"])
    if card_used > gpu_budget_mib:
        return "Own process tree exceeded GPU memory budget"
    if sample_data.get("gpu_free_mib", gpu_reserve_mib) < gpu_reserve_mib:
        return "GPU free memory below 2048 MiB minimum reserve"
    return None


def stop_owned(proc):
    # Must be a live, unreaped Popen(start_new_session=True) owned by this broker.
    # Never accepts an arbitrary PID, and never signals another user's job.
    # The watcher and request cleanup may arrive together. Keep the unreaped
    # Popen as the identity anchor until the one serialized cleanup has finished.
    with _stop_lock:
        if proc.returncode is not None:
            return
        _stop_unreaped(proc)


def _stop_unreaped(proc):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        groups = set()
        for pid in members(proc.pid):
            try:
                if os.getsid(pid) == proc.pid and os.stat("/proc/" + str(pid)).st_uid == os.getuid():
                    groups.add(os.getpgid(pid))
            except (FileNotFoundError, ProcessLookupError):
                continue
        for group in groups:
            if group == os.getpgrp():
                raise RuntimeError("Refusing to signal broker")
            try:
                os.killpg(group, sig)
            except ProcessLookupError:
                pass
        if sig == signal.SIGTERM and groups:
            time.sleep(0.3)
    proc.wait(timeout=20)
