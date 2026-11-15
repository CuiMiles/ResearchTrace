"""Guard/contract tests with synthetic inputs. No model or availability claims."""
import asyncio
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from fastapi.testclient import TestClient
from PIL import Image
import pytest
from reportlab.pdfgen import canvas

from services.parsing import guard, runner, server, validation


def png_bytes(size=(20, 20)):
    out = io.BytesIO()
    Image.new('RGB', size, 'white').save(out, format='PNG')
    return out.getvalue()


def test_selection_reserve_budget_and_live_query(monkeypatch):
    snapshots = iter([
        [{'uuid': 'GPU-a', 'free': 5776, 'total': 8188}, {'uuid': 'GPU-b', 'free': 7000, 'total': 8192}],
        [{'uuid': 'GPU-a', 'free': 5776, 'total': 8188}, {'uuid': 'GPU-b', 'free': 2500, 'total': 8192}],
    ])
    monkeypatch.setattr(guard, 'gpu_snapshot', lambda: next(snapshots))
    assert guard.choose_gpu(2048, 2048)['uuid'] == 'GPU-b'
    assert guard.choose_gpu(2048, 2048)['uuid'] == 'GPU-a'
    with pytest.raises(ValueError):
        guard.choose_gpu(2047, 2048)
    monkeypatch.setattr(guard, 'gpu_snapshot', lambda: [{'free': 4200}])
    with pytest.raises(ValueError):
        guard.choose_gpu(2048, 2048)


def test_reserve_cannot_be_lowered(monkeypatch):
    monkeypatch.setenv('RT_GPU_RESERVE_MIB', '1')
    assert server.limits()[0] == 2048
    monkeypatch.setenv('RT_GPU_MAX_MIB', '0')
    with pytest.raises(ValueError):
        server.limits()


def test_descendant_accounting_and_wsl_fail_closed(monkeypatch):
    monkeypatch.setattr(guard, 'session_pids', lambda sid: {100, 101, 102})
    monkeypatch.setattr(guard, '_query', lambda *a: [['101', 'GPU-a', '1200'], ['102', 'GPU-a', '900'], ['100', 'GPU-b', '500']])
    assert guard.own_gpu_usage(100, 'GPU-a') == (2100, True)
    monkeypatch.setattr(guard, '_query', lambda *a: [['101', 'GPU-a', '[N/A]']])
    with pytest.raises(ValueError, match='WSL'):
        guard.own_gpu_usage(100, 'GPU-a')
    monkeypatch.setattr(guard, '_query', lambda *a: [['999999999', 'GPU-a', '32']])
    with pytest.raises(ValueError, match='namespace'):
        guard.own_gpu_usage(100, 'GPU-a')


def test_kills_own_descendant_after_leader_exit_preserves_other_process(tmp_path):
    pidfile = tmp_path / 'child.pid'
    child_code = 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'
    parent_code = ('import subprocess,sys,time; from pathlib import Path; '
                   'p=subprocess.Popen([sys.executable,"-c",sys.argv[2]]); '
                   'Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(60)')
    own = subprocess.Popen([sys.executable, '-c', parent_code, str(pidfile), child_code], start_new_session=True)
    other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        child_pid = int(pidfile.read_text())
        time.sleep(.1)  # ensure child has installed its TERM handler
        os.kill(own.pid, signal.SIGTERM)
        own.wait(timeout=5)
        assert child_pid in guard.session_pids(own.pid)
        guard.stop_session(own, grace=.05)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                state = Path(f'/proc/{child_pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
            except FileNotFoundError:
                break
            if state == 'Z':
                break
            time.sleep(.02)
        else:
            pytest.fail('Owned descendant still running')
        assert other.poll() is None
    finally:
        guard.stop_session(own, grace=.01)
        guard.stop_session(other, grace=.01)


def test_bounded_inputs_and_geometry(tmp_path):
    image = tmp_path / 'page.png'
    image.write_bytes(png_bytes())
    assert validation.validate_input('paddleocr', image) == [20, 20]
    image.write_bytes(png_bytes((8193, 1)))
    with pytest.raises(ValueError, match='bounds'):
        validation.validate_input('paddleocr', image)
    image.write_bytes(b'\x89PNG\r\n\x1a\ninvalid')
    with pytest.raises(ValueError):
        validation.validate_input('paddleocr', image)
    pdf = tmp_path / 'page.pdf'
    out = io.BytesIO()
    doc = canvas.Canvas(out)
    for _ in range(2):
        doc.drawString(10, 10, 'synthetic guard fixture')
        doc.showPage()
    doc.save()
    pdf.write_bytes(out.getvalue())
    with pytest.raises(ValueError, match='exactly one'):
        validation.validate_input('mineru', pdf)
    for box in ([0, 0, float('nan'), 1], [1, 0, 0, 1], [1, 2]):
        with pytest.raises(ValueError):
            validation.normalized_box(box)


def test_mineru_contract_preserves_table_equation_order():
    content = [
        {'type': 'table', 'bbox': [10, 20, 900, 500], 'table_caption': ['caption'], 'table_body': '<table></table>', 'table_footnote': ['footnote'], 'page_idx': 0},
        {'type': 'equation', 'bbox': [10, 600, 500, 700], 'text': 'x^2'},
    ]
    middle = {'pdf_info': [{'page_size': [612, 792]}]}
    blocks, size = runner.normalize_mineru(content, middle)
    assert size == [612, 792]
    assert blocks[0]['type'] == 'table'
    assert blocks[0]['bbox'] == [.01, .02, .9, .5]
    assert blocks[0]['text'] == 'caption\n<table></table>\nfootnote'
    assert blocks[1]['text'] == 'x^2'
    with pytest.raises(ValueError, match='geometry'):
        runner.normalize_mineru([{'text': 'unlocatable'}], middle)
    with pytest.raises(ValueError, match='unexpected page'):
        runner.normalize_mineru([dict(content[0], page_idx=1)], middle)


def test_environment_secrets_and_library_paths_not_inherited(tmp_path, monkeypatch):
    for key in ('API_KEY', 'HF_TOKEN', 'LD_PRELOAD', 'PYTHONPATH', 'HTTP_PROXY'):
        monkeypatch.setenv(key, 'synthetic-never-propagate')
    monkeypatch.setenv('LD_LIBRARY_PATH', '/old/intel')
    env = server.runner_env('mineru', tmp_path)
    assert all(key not in env for key in ('API_KEY', 'HF_TOKEN', 'LD_PRELOAD', 'PYTHONPATH', 'HTTP_PROXY'))
    assert '/old/intel' not in env.get('LD_LIBRARY_PATH', '')
    assert env['HOME'] == str(tmp_path)
    assert env['MINERU_MODEL_SOURCE'] == 'local'
    assert env['CUDA_VISIBLE_DEVICES'] == ''


def test_readiness_is_not_liveness(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'PRIVATE', tmp_path)
    monkeypatch.setattr(server, 'interpreter_for', lambda engine: tmp_path / 'not-installed')
    with TestClient(server.app) as client:
        assert client.get('/healthz').json()['ready'] is False
        response = client.get('/readyz')
    assert response.status_code == 503
    assert response.json()['inference_verified'] is False
    assert not response.json()['libraries']['mineru']['preflight_ok']


def test_request_rejects_wrong_device_large_body_and_input(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'PRIVATE', tmp_path)
    with TestClient(server.app) as client:
        assert client.post('/parse/paddleocr?device=gpu', files={'file': ('x.png', png_bytes())}).status_code == 422
        assert client.post('/parse/mineru', files={'file': ('x.pdf', b'bad')}).status_code == 422
        assert client.post('/parse/mineru', content=b'', headers={'content-length': str(30 * 1024 * 1024)}).status_code == 413


def test_streamed_body_bound_without_content_length():
    messages = iter([{'type': 'http.request', 'body': b'x' * (validation.MAX_BYTES + 1024 * 1024 + 1)}])
    sent = []

    async def consume(scope, receive, send):
        message = await receive()
        assert message['type'] == 'http.disconnect'
        raise RuntimeError('multipart disconnected')

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    asyncio.run(server.BoundedBody(consume)({'type': 'http', 'headers': []}, receive, send))
    assert sent[0]['status'] == 413


def test_fixed_api_pin_refuses_new_major_before_import(monkeypatch):
    monkeypatch.setattr(runner.importlib.metadata, 'version', lambda engine: '4.2.2')
    with pytest.raises(ValueError, match='2.7.6'):
        runner.check_models('mineru')


def test_offline_policy_in_separate_owned_process():
    code = ('from services.parsing.offline import disable_network; import socket; disable_network(); '
            'socket.create_connection(("127.0.0.1",9),timeout=.1)')
    proc = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=5)
    assert proc.returncode != 0
    assert 'Parser network access disabled' in proc.stderr


@pytest.mark.parametrize('cause', ['cancel', 'reserve', 'budget', 'telemetry'])
def test_execute_terminates_owned_job_and_records_reason(tmp_path, monkeypatch, cause):
    monkeypatch.setattr(server, 'interpreter_for', lambda engine: Path(sys.executable))
    monkeypatch.setattr(server, 'choose_gpu', lambda *a: {'uuid': 'GPU-test', 'free': 5776, 'total': 8188})
    monkeypatch.setattr(server, 'gpu_snapshot', lambda: [{'uuid': 'GPU-test', 'free': 1024 if cause == 'reserve' else 5776}])
    calls = 0

    def usage(*args):
        nonlocal calls
        calls += 1
        if cause == 'telemetry' and calls > 1:
            raise ValueError('N/A')
        return (4096 if cause == 'budget' and calls > 1 else 0), True
    monkeypatch.setattr(server, 'own_gpu_usage', usage)
    real_popen = subprocess.Popen
    children = []

    def fake_runner(command, **kwargs):
        proc = real_popen([sys.executable, '-c', 'import time; time.sleep(60)'], **kwargs)
        children.append(proc)
        return proc
    monkeypatch.setattr(server.subprocess, 'Popen', fake_runner)
    cancel = threading.Event()
    if cause == 'cancel':
        cancel.set()
    with pytest.raises(ValueError):
        server.execute('mineru', tmp_path, input_path=tmp_path / 'page.pdf', device='gpu', cancel_event=cancel)
    assert children[0].poll() is not None
    monitor = json.loads((tmp_path / 'result.monitor.json').read_text())
    assert monitor['terminated_reason']
    assert monitor['budget_mib'] == 2048


def test_request_cancellation_only_named_job_and_waits_for_release(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'PRIVATE', tmp_path)
    started = threading.Event()
    children = []
    unrelated = threading.Event()
    monkeypatch.setattr(server, 'active_requests', {'unrelated': unrelated})

    real_popen = subprocess.Popen
    monkeypatch.setattr(server, 'interpreter_for', lambda engine: Path(sys.executable))

    def waiting_runner(command, **kwargs):
        # Substitute only inference, retaining the real broker monitor, event,
        # cancellation endpoint, session cleanup and response lifetime.
        proc = real_popen([sys.executable, '-c', 'import time; time.sleep(60)'], **kwargs)
        children.append(proc)
        started.set()
        return proc

    monkeypatch.setattr(server.subprocess, 'Popen', waiting_runner)
    with TestClient(server.app) as client:
        response = []
        worker = threading.Thread(target=lambda: response.append(client.post(
            '/parse/paddleocr?request_id=run_abc-123', files={'file': ('page.png', png_bytes())})))
        worker.start()
        try:
            assert started.wait(5)
            duplicate = client.post('/parse/paddleocr?request_id=run_abc-123', files={'file': ('page.png', png_bytes())})
            assert duplicate.status_code == 409
            cancel = client.post('/cancel/run_abc-123')
            assert cancel.status_code == 200
            assert cancel.json()['released'] is False
            assert not unrelated.is_set()
            assert client.post('/cancel/missing').status_code == 404
            assert client.post('/cancel/bad.id').status_code == 422
        finally:
            event = server.active_requests.get('run_abc-123')
            if event:
                event.set()
            worker.join(6)
        assert not worker.is_alive()
        assert children[0].poll() is not None
        assert response[0].status_code == 503
        assert 'run_abc-123' not in server.active_requests
        assert not server.lock.locked()
        assert client.post('/cancel/run_abc-123').status_code == 404
        invalid = client.post('/parse/paddleocr?request_id=bad.id', files={'file': ('page.png', png_bytes())})
        assert invalid.status_code == 422
