"""One reusable model child, continuously guarded even between HTTP requests."""
import json
import os
import select
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from . import guard
from .catalog import RuntimeUnavailable


class Busy(RuntimeUnavailable):
    pass


class Supervisor:
    def __init__(self, catalog):
        self.catalog = catalog
        self.lock = threading.Lock()
        self.process = None
        self.gpu_claims=[]
        self.claims_lock=threading.Lock()
        self.model_id = None
        self.monitor = None
        self.failure = None
        self.verified = set()
        self.gpu_budget = int(os.environ.get("RT_RETRIEVAL_GPU_MAX_MIB", "8192"))
        self.gpu_reserve = max(2048, int(os.environ.get("RT_RETRIEVAL_GPU_RESERVE_MIB", "2048")))
        self.host_budget = int(os.environ.get("RT_RETRIEVAL_HOST_MAX_MIB", "49152"))
        self.host_reserve = max(16384, int(os.environ.get("RT_RETRIEVAL_HOST_RESERVE_MIB", "16384")))
        self.mode = os.environ.get("RT_RETRIEVAL_EXECUTION_MODE", "cpu")
        self.gpu_count=int(os.getenv('RT_RETRIEVAL_GPU_COUNT','2'))
        if not 2<=self.gpu_count<=4:raise ValueError('Sharded GPU count must be2..4')
        if self.mode not in {"cpu", "cuda", "cuda_sharded", "cpu_offload", "cuda_auto"}:
            raise ValueError("Execution mode must be cpu, cuda, cuda_sharded or cpu_offload")
        if self.mode == "cpu_offload" and self.gpu_budget < 4096:
            raise ValueError("CPU offload needs >=4096 MiB whole GPU budget")
        self.timeout = min(1800, max(10, int(os.environ.get("RT_RETRIEVAL_REQUEST_TIMEOUT", "900"))))
        self.report = None

    def _close(self):
        proc = self.process
        if proc is not None:
            try:guard.stop_owned(proc)
            except subprocess.TimeoutExpired:
                self.failure='Own model child is still releasing resources; no replacement may start'
                raise RuntimeUnavailable(self.failure) from None
            self.process = None
            self.model_id = None
            for pipe in (proc.stdin, proc.stdout):
                if pipe:
                    pipe.close()
        self._release_gpu_claims()
        if self.monitor and self.monitor is not threading.current_thread():
            self.monitor.join(timeout=6)
        self.monitor = None

    def _release_gpu_claims(self,proc=None):
        with self.claims_lock:
            if proc is not None and self.process is not proc:
                return
            for handle in self.gpu_claims:handle.close()
            self.gpu_claims=[]

    def close(self):
        with self.lock:
            self._close()

    def _watch(self, proc, gpu, folder, started,mode,budget):
        peak_rss = peak_gpu = 0
        card_peaks = {}
        with (folder / "monitor.jsonl").open("a") as log:
            while self.process is proc:
                try:
                    value = guard.sample(proc.pid, gpu)
                    log.write(json.dumps(value) + "\n")
                    log.flush()
                    peak_rss = max(peak_rss, value["rss_mib"])
                    peak_gpu = max(peak_gpu, value["gpu_used_mib"])
                    for item in value.get("per_gpu", []):
                        card_peaks[item["uuid"]] = max(card_peaks.get(item["uuid"], 0), item["used_mib"])
                    self.report = {"mode": mode, "peak_rss_mib": peak_rss, "peak_gpu_mib": peak_gpu,
                                   "selected_gpus": gpu or [], "per_gpu_peak_mib": dict(card_peaks),
                                   "gpu_reserve_mib": self.gpu_reserve, "gpu_budget_mib": budget,
                                   "host_budget_mib": self.host_budget, "monitor_path": str(folder / "monitor.jsonl")}
                    if not value['pids']:
                        self._release_gpu_claims(proc)
                        return
                    reason = guard.violation(value, budget, self.gpu_reserve,
                                             self.host_budget, self.host_reserve)
                    if time.monotonic() - started > min(14400,int(os.getenv('RT_RETRIEVAL_WORKER_LIFETIME','7200'))):
                        reason = "Resident worker reached its bounded lifecycle"
                    if (folder / "stderr.log").stat().st_size > 16 * 1024 * 1024:
                        reason = "Worker log exceeded private disk budget"
                    if reason:
                        raise RuntimeError(reason)
                except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
                    self.failure = "Resource guard: " + str(error)
                    try:guard.stop_owned(proc)
                    except subprocess.TimeoutExpired:
                        self.failure+='; own process cleanup is still pending'
                    return
                time.sleep(0.5)

    def _line(self, proc):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.failure:
                raise RuntimeUnavailable(self.failure)
            if select.select([proc.stdout], [], [], 0.25)[0]:
                line = proc.stdout.readline(32 * 1024 * 1024)
                if not line:
                    raise RuntimeUnavailable("Offline model child exited; inspect private stderr.log")
                try:
                    return json.loads(line)
                except json.JSONDecodeError as error:
                    raise RuntimeUnavailable("Model child violated JSON protocol") from error
        raise RuntimeUnavailable("Bounded model request timed out")

    def _launch(self, spec):
        descriptor = self.catalog.descriptor(spec)
        if not descriptor["weights_ready"]:
            raise RuntimeUnavailable("Pinned model weights are not fully downloaded")
        if guard.memory_available_mib() < self.host_budget + self.host_reserve:
            raise RuntimeUnavailable("Insufficient host RAM for whole process budget plus reserve")
        gpu=None
        mode=self.mode;budget=self.gpu_budget
        if mode=='cuda_auto':
            try:
                gpu,self.gpu_claims=guard.claim_gpus(self.catalog.root,budget*2,self.gpu_reserve,1)
                mode='cuda';budget*=2
            except RuntimeError:
                mode='cuda_sharded'
                for count in range(2,5):
                    share=(self.gpu_budget*2)//count
                    try:
                        gpu,self.gpu_claims=guard.claim_gpus(self.catalog.root,share,self.gpu_reserve,count)
                        budget=share
                        break
                    except RuntimeError:
                        continue
                if gpu is None:raise RuntimeUnavailable('共享GPU暂时没有满足2..4卡总预算及每卡2GiB余量的资源槽')
        if mode!='cpu' and gpu is None:
            gpu,self.gpu_claims=guard.claim_gpus(self.catalog.root,budget,self.gpu_reserve,self.gpu_count if mode=='cuda_sharded' else 1)
        if mode == "cuda":
            minimum = 18432  # BF16 8.38B weights + a conservative small-input workspace.
            if budget < minimum:
                raise RuntimeUnavailable("Full GPU BF16 requires >=18432 MiB whole job budget")
        folder = self.catalog.root / "private" / "jobs" / uuid.uuid4().hex
        folder.mkdir(parents=True, mode=0o700)
        config = Path(os.environ.get("RT_RETRIEVAL_CONFIG", "configs/retrieval-models.json")).resolve()
        threads = str(min(8, max(1, int(os.environ.get("RT_RETRIEVAL_CPU_THREADS", "4")))))
        env = {"PATH": str(Path(sys.executable).parent) + ":/usr/local/bin:/usr/bin:/bin",
               "HOME": str(folder), "LANG": "C.UTF-8", "PYTHONUNBUFFERED": "1",
               "PYTHONNOUSERSITE": "1", "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
               "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
               "HF_HOME": str(folder / "hf"), "TOKENIZERS_PARALLELISM": "false",
               "OMP_NUM_THREADS": threads, "MKL_NUM_THREADS": threads, "OPENBLAS_NUM_THREADS": threads,
               "USE_TF": "0", "USE_FLAX": "0", "CUDA_VISIBLE_DEVICES": ",".join(g["uuid"] for g in gpu) if gpu else "",
               "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
               "RT_RETRIEVAL_ROOT": str(self.catalog.root), "RT_RETRIEVAL_CONFIG": str(config),
               "RT_RETRIEVAL_MODEL_ID": spec["model_id"], "RT_RETRIEVAL_EXECUTION_MODE": mode,
               "RT_RETRIEVAL_GPU_MAX_MIB": str(budget), "RT_RETRIEVAL_CPU_THREADS": threads,
               "RT_RETRIEVAL_JOB_DIR": str(folder)}
        self.failure = None
        with (folder / "stderr.log").open("w") as log:
            proc = subprocess.Popen([sys.executable, "-m", "services.retrieval_runtime.runner"],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                    env=env, text=True, bufsize=1, start_new_session=True,
                                    cwd=Path(__file__).resolve().parents[2])
        self.process, self.model_id = proc, spec["model_id"]
        self.monitor = threading.Thread(target=self._watch, args=(proc, gpu, folder, time.monotonic(),mode,budget), daemon=True)
        self.monitor.start()
        response = self._line(proc)
        if response.get("ready") is not True:
            raise RuntimeUnavailable("Offline model child failed to initialize")
        return proc

    def run(self, spec, payload):
        if not self.lock.acquire(timeout=30):
            raise Busy("Local inference queue exceeded its30-second bound")
        started = time.monotonic()
        try:
            if self.failure or self.model_id != spec["model_id"]:
                self._close()
            proc = self.process or self._launch(spec)
            if not guard.members(proc.pid):
                self._close()
                proc = self._launch(spec)
            proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            result = self._line(proc)
            if "error" in result:
                raise RuntimeUnavailable(result["error"])
            self.verified.add(self.catalog.descriptor(spec)["fingerprint"])
            result["execution"] = {**(self.report or {}), "elapsed_seconds": round(time.monotonic() - started, 4)}
            return result
        except Exception:
            self._close()
            raise
        finally:
            self.lock.release()
