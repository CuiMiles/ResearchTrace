"""Private Unix-socket broker for two fixed offline runners.

Liveness is not model readiness. Only guarded jobs can establish a successful
inference, and no provider credentials or parent dynamic-library paths propagate.
"""
import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
import uvicorn

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.parsing.guard import choose_gpu, gpu_snapshot, own_gpu_usage, stop_session
from services.parsing.offline import OFFLINE_ENV
from services.parsing.runner import PINS, read_json
from services.parsing.validation import MAX_BYTES, MAX_RESULT_BYTES, validate_result

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / 'data/parsing'
SOCKET = PRIVATE / 'parser.sock'
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
lock = asyncio.Lock()
last_runs = {}
active_requests = {}
REQUEST_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z')


def interpreter_for(engine):
    if engine == 'paddleocr':
        default = ROOT / '.tools/paddle-env/bin/python'
        return Path(os.getenv('RT_PADDLE_PYTHON', str(default))).absolute()
    if engine == 'paddleocr_vl':
        default = ROOT / '.tools/mineru-env/bin/python'
        return Path(os.getenv('RT_PADDLE_VL_PYTHON', str(default))).absolute()
    default = ROOT / '.tools/mineru-env/bin/python'
    return Path(os.getenv('RT_MINERU_PYTHON', str(default))).absolute()


def limits():
    try:
        reserve = max(2048, int(os.getenv('RT_GPU_RESERVE_MIB', '2048')))
        budget = int(os.getenv('RT_GPU_MAX_MIB', '2048'))
        timeout = int(os.getenv('RT_PARSER_TIMEOUT_SECONDS', '300'))
        if not 256 <= budget <= 65536 or not 1 <= timeout <= 900:
            raise ValueError
        return reserve, budget, timeout
    except ValueError:
        raise ValueError('Invalid parser resource limits') from None


def runner_env(engine, directory):
    # Explicit allowlist. In particular HOME is private; no parent .env, keys,
    # proxies, PYTHONPATH, LD_PRELOAD or LD_LIBRARY_PATH are inherited.
    env = {
        'PATH': str(interpreter_for(engine).parent) + ':/usr/bin:/bin',
        'HOME': str(directory), 'TMPDIR': str(directory), 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
        'PYTHONNOUSERSITE': '1', 'PYTHONUNBUFFERED': '1',
        'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2',
        **OFFLINE_ENV,
        'MINERU_MODEL_BASE_DIR': os.getenv('RT_MINERU_MODELS', str(ROOT / '.tools/models/mineru-4.2')),
        'MINERU_MODEL_SOURCE': 'local', 'MINERU_MODEL_SMALL_BACKEND': 'torch',
        'MINERU_MODEL_VLM_ENGINE': 'llama-cpp', 'MINERU_DEVICE_MODE': 'cpu',
        'MINERU_MIN_BATCH_INFERENCE_SIZE': '1', 'MINERU_TABLE_MAX_TIME': '120',
        'RT_PADDLE_PYTHON': str(interpreter_for('paddleocr')),
        'RT_PADDLE_MODELS': os.getenv('RT_PADDLE_MODELS', str(ROOT / '.tools/models/paddle')),
        'RT_PADDLE_VL_MODELS': os.getenv('RT_PADDLE_VL_MODELS', str(ROOT / '.tools/models/paddle-vl')),
        'HF_HOME': str(directory / 'hf'), 'MODELSCOPE_CACHE': str(directory / 'modelscope'),
        'PADDLE_PDX_CACHE_HOME': str(directory / 'paddle'), 'CUDA_VISIBLE_DEVICES': '',
        'RT_PARSER_TIMEOUT_SECONDS': str(limits()[2]),
    }
    # NVIDIA's WSL CUDA driver location is not part of the normal Linux loader
    # search path. It is fixed, not an inherited arbitrary old Intel runtime.
    if Path('/usr/lib/wsl/lib/libcuda.so.1').is_file():
        env['LD_LIBRARY_PATH'] = '/usr/lib/wsl/lib'
    return env


def execute(engine, directory, *, input_path=None, device='cpu', cancel_event=None):
    if engine not in ('paddleocr', 'paddleocr_vl', 'mineru') or device not in ('cpu', 'gpu'):
        raise ValueError('Unsupported parser or device')
    if engine in ('paddleocr', 'paddleocr_vl') and device != 'cpu':
        raise ValueError(f'{engine} runner supports CPU only; GPU is MinerU pipeline')
    interpreter = interpreter_for(engine)
    if not interpreter.is_file():
        raise ValueError(f'{engine} environment unavailable')
    directory = Path(directory)
    output_path = directory / 'result.json'
    reserve, budget, timeout = limits()
    env = runner_env(engine, directory)
    gpu = None
    command = [str(interpreter), str(ROOT / 'services/parsing/runner.py')]
    command += [engine, str(input_path), str(output_path)] if input_path else ['--check', engine]
    samples = []
    start = time.monotonic()
    reason = None
    proc = None
    # Bounded pipe output goes to private disk; guard also bounds disk growth.
    log_path = directory / 'runner.log'
    try:
        if device == 'gpu':
            try:
                gpu = choose_gpu(reserve, budget)  # live selection for every job, never cached
                # Fail before starting a GPU job when NVML cannot even answer this query.
                own_gpu_usage(-1, gpu['uuid'])
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                reason = str(exc)
                raise ValueError(reason) from None
            env.update(CUDA_VISIBLE_DEVICES=gpu['uuid'], MINERU_DEVICE_MODE='cuda',
                       RT_GPU_LIMIT_MIB=str(budget), PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')
        with log_path.open('wb') as logfile:
            proc = subprocess.Popen(command, env=env, cwd=directory, stdout=logfile,
                                    stderr=logfile, start_new_session=True)
            while proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    reason = 'Parser cancelled'
                elif time.monotonic() - start > (timeout if input_path else min(timeout, 45)):
                    reason = 'Parser time limit exceeded'
                elif log_path.stat().st_size > 8 * 1024 * 1024:
                    reason = 'Parser diagnostic output limit exceeded'
                if gpu and not reason:
                    try:
                        current = next(g for g in gpu_snapshot() if g['uuid'] == gpu['uuid'])
                        used, matched = own_gpu_usage(proc.pid, gpu['uuid'])
                        samples.append({'elapsed': round(time.monotonic() - start, 3),
                                        'free_mib': current['free'], 'own_used_mib': used})
                        if output_path.with_suffix('.cuda-started').exists() and not matched:
                            raise ValueError('CUDA PID telemetry unavailable in WSL namespace')
                        if current['free'] < reserve or used > budget:
                            reason = 'GPU reserve or per-test memory budget reached'
                    except (OSError, subprocess.SubprocessError, ValueError, StopIteration):
                        reason = 'GPU accounting unavailable; stopping this job conservatively (WSL/NVML)'
                if reason:
                    break
                # Event.wait allows cancellation without delaying the entire interval.
                if cancel_event is not None:
                    cancel_event.wait(.25)
                else:
                    time.sleep(.25)
    finally:
        if reason is None and log_path.exists() and log_path.stat().st_size > 8 * 1024 * 1024:
            reason = 'Parser diagnostic output limit exceeded'
        if proc is not None:
            # Clean remaining descendants even on successful leader exit or
            # monitor exception. Never pkill by name, never signal other jobs.
            stop_session(proc)
        monitor = {'engine': engine, 'device': device, 'gpu': gpu, 'reserve_mib': reserve,
                   'budget_mib': budget if gpu else None, 'samples': samples,
                   'terminated_reason': reason, 'elapsed': round(time.monotonic() - start, 3),
                   'returncode': proc.returncode if proc else None}
        (directory / 'result.monitor.json').write_text(json.dumps(monitor, ensure_ascii=False, indent=2))
    if reason or proc.returncode:
        raise ValueError(reason or f'{engine} failed; private diagnostics {directory.name}')
    if input_path:
        if not output_path.is_file() or output_path.stat().st_size > MAX_RESULT_BYTES:
            raise ValueError('Parser output missing or exceeds bounds')
        result = read_json(output_path)
        validate_result(result, engine, PINS[engine], 'cuda' if device == 'gpu' else 'cpu')
        result['monitor'] = monitor
        return result
    # Preflight's last stdout line is protocol; native chatter is stderr.
    try:
        result = json.loads(log_path.read_text().splitlines()[-1])
    except (ValueError, IndexError, UnicodeError):
        raise ValueError('Parser preflight did not return valid diagnostics') from None
    return result


def run_library(engine, input_path, output_path, device='cpu', cancel_event=None):
    """Preserve existing caller signature; broker output lives in its job folder."""
    output_path = Path(output_path)
    if output_path.name != 'result.json':
        raise ValueError('Output must use private job result.json')
    return execute(engine, output_path.parent, input_path=Path(input_path), device=device,
                   cancel_event=cancel_event)


def new_directory():
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = PRIVATE / uuid.uuid4().hex
    directory.mkdir(mode=0o700)
    return directory


@app.get('/healthz')
def health():
    return {'status': 'ok', 'ready': False, 'transport': 'private Unix socket',
            'detail': 'Broker liveness only; use /readyz for offline preflight',
            'gpu_reserve_mib': limits()[0], 'last_runs': dict(last_runs)}


@app.get('/readyz')
async def readiness():
    if lock.locked():
        return JSONResponse(status_code=503, content={'ready': False, 'detail': 'Parser busy'})
    libraries = {}
    async with lock:
        for engine in ('paddleocr', 'paddleocr_vl', 'mineru'):
            cancel = threading.Event()
            task = asyncio.create_task(asyncio.to_thread(execute, engine, new_directory(), cancel_event=cancel))
            try:
                libraries[engine] = await asyncio.shield(task)
            except asyncio.CancelledError:
                cancel.set()
                await asyncio.gather(task, return_exceptions=True)
                raise
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                libraries[engine] = {'preflight_ok': False, 'inference_verified': False, 'detail': str(exc)}
    preflight_ok = all(value.get('preflight_ok') for value in libraries.values())
    return JSONResponse(status_code=200 if preflight_ok else 503,
                        content={'ready': preflight_ok, 'readiness_level': 'offline_preflight',
                                 'inference_verified': False, 'libraries': libraries, 'last_runs': dict(last_runs)})


def validated_request_id(value):
    if not REQUEST_ID.fullmatch(value):
        raise HTTPException(422, 'request_id must be 1..96 ASCII letters, digits, underscores or hyphens')
    return value


@app.post('/cancel/{request_id}')
async def cancel_request(request_id: str):
    request_id = validated_request_id(request_id)
    event = active_requests.get(request_id)
    if event is None:
        raise HTTPException(404, 'No active parser request with this ID')
    event.set()
    # Accepted is not completion. Parse response/monitor establishes cleanup.
    return {'request_id': request_id, 'status': 'cancellation_requested', 'released': False}


@app.post('/parse/{engine}')
async def parse(engine: str, request: Request, file: UploadFile = File(...),
                device: str = 'cpu', request_id: str | None = None):
    try:
        identifier = validated_request_id(request_id) if request_id is not None else uuid.uuid4().hex
        if engine not in ('paddleocr', 'paddleocr_vl', 'mineru') or device not in ('cpu', 'gpu') or (engine in ('paddleocr', 'paddleocr_vl') and device == 'gpu'):
            raise HTTPException(422, 'Unsupported parser or device')
        if identifier in active_requests:
            raise HTTPException(409, 'Parser request ID already active')
        if lock.locked():
            raise HTTPException(429, 'Parser busy; durable main worker can resume later')
    except BaseException:
        await file.close()
        raise
    async with lock:
        cancel = threading.Event()
        active_requests[identifier] = cancel
        task = None
        try:
            directory = new_directory()
            path = directory / ('input.pdf' if engine == 'mineru' else 'input.png')
            count = 0
            with path.open('wb') as stream:
                while chunk := await file.read(65536):
                    count += len(chunk)
                    if count > MAX_BYTES:
                        raise HTTPException(413, 'Input exceeds 20 MiB')
                    if cancel.is_set():
                        raise HTTPException(409, 'Parser cancelled before launch')
                    stream.write(chunk)
            with path.open('rb') as stream:
                signature = stream.read(8)
            if not signature.startswith(b'%PDF-' if engine == 'mineru' else b'\x89PNG\r\n\x1a\n'):
                raise HTTPException(422, 'Expected single-page PDF / PNG')
            if cancel.is_set():
                raise HTTPException(409, 'Parser cancelled before launch')
            task = asyncio.create_task(asyncio.to_thread(run_library, engine, path, directory / 'result.json', device, cancel))
            while not task.done():
                await asyncio.sleep(.1)
                if await request.is_disconnected():
                    cancel.set()
            result = await asyncio.shield(task)
            if cancel.is_set():
                raise ValueError('Parser cancelled')
            last_runs[engine] = {'status': 'PASS', 'version': result['version'], 'device': result['device'],
                                 'inference_verified': True, 'time': time.time()}
            result['request_id'] = identifier
            return result
        except asyncio.CancelledError:
            cancel.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            raise
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            last_runs[engine] = {'status': 'FAIL', 'inference_verified': False, 'time': time.time()}
            raise HTTPException(503, str(exc)) from None
        finally:
            cancel.set()
            active_requests.pop(identifier, None)
            await file.close()


class BoundedBody:
    """Limit the multipart body before Starlette spools arbitrarily large input."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        total = 0
        maximum = MAX_BYTES + 1024 * 1024
        headers = dict(scope.get('headers', []))
        try:
            length = int(headers.get(b'content-length', b'0'))
        except ValueError:
            return await JSONResponse({'detail': 'Invalid Content-Length'}, status_code=400)(scope, receive, send)
        if length < 0 or length > maximum:
            return await JSONResponse({'detail': 'Request body exceeds bounds'}, status_code=413)(scope, receive, send)
        exceeded = False

        async def bounded_receive():
            nonlocal total, exceeded
            message = await receive()
            total += len(message.get('body', b''))
            if total > maximum:
                exceeded = True
                # A receive disconnect stops multipart parsing without passing
                # attacker-controlled unlimited chunks to the multipart spooler.
                return {'type': 'http.disconnect'}
            return message

        async def bounded_send(message):
            if not exceeded:
                await send(message)
        try:
            await self.app(scope, bounded_receive, bounded_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded:
            await JSONResponse({'detail': 'Request body exceeds bounds'}, status_code=413)(scope, receive, send)


app.add_middleware(BoundedBody)


def main():
    import fcntl
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.umask(0o077)
    with (PRIVATE / 'broker.lock').open('a') as owned_lock:
        fcntl.flock(owned_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if SOCKET.exists():
            if not SOCKET.is_socket():
                raise ValueError('Refusing to replace a non-socket file')
            SOCKET.unlink()
        uvicorn.run(app, uds=str(SOCKET), workers=1, log_level='warning')


if __name__ == '__main__':
    main()
