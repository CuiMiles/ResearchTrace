"""Synthetic upgrade regressions only; no model loading, downloads or providers."""
import contextlib
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from services.parsing import runner, server, validation


def test_layout_json_drops_paddlex_arrays_preserves_consumed_fields():
    boxes = [{'label': 'table', 'score': .9, 'coordinate': [1, 2, 15, 18], 'order': 2,
              'polygon': np.array([[1, 2], [15, 18]]), 'unneeded': np.int64(4)}]
    result = runner.validate_vl_boxes(boxes, 20, 20)
    assert json.loads(json.dumps(result, allow_nan=False)) == [
        {'label': 'table', 'score': .9, 'coordinate': [1., 2., 15., 18.], 'order': 2.}]


@pytest.mark.parametrize('coordinate', [[30, 0, 40, 10], [5, 0, 5, 10], [9, 0, 3, 10], [0, 0, float('nan'), 10]])
def test_invalid_vl_regions_fail_instead_of_becoming_one_pixel(coordinate):
    with pytest.raises(ValueError, match='geometry'):
        runner.validate_vl_boxes([{'label': 'text', 'coordinate': coordinate, 'score': .8}], 20, 20)


def test_region_and_table_expansion_budgets(monkeypatch):
    monkeypatch.setattr(runner, 'MAX_VL_REGIONS', 1)
    with pytest.raises(ValueError, match='region budget'):
        runner.validate_vl_boxes([{}, {}], 20, 20)
    monkeypatch.setattr(runner, 'MAX_VL_TABLE_CELLS', 10)
    with pytest.raises(ValueError, match='cell budget'):
        runner.validate_otsl_budget('<fcel>' * 6 + '<nl>' + '<fcel><nl>' * 6)


def test_formula_normalization_preserves_currency_and_table_content():
    assert runner.normalize_vl_text(r'cost $5; \(x^2\) and \[y\]', 'text') == 'cost $5; $x^2$ and $$y$$'
    assert runner.normalize_vl_text(r'\(12\)', 'formula_number') == '12'
    assert runner.normalize_vl_text('<fcel>2.5<nl>', 'table') == '<fcel>2.5<nl>'
    assert runner.OTSL_TAG.search('<lcel>')
    with pytest.raises(ValueError, match='non-text content'):
        runner.normalize_mineru([{'type': 'table', 'bbox': [1, 2, 8, 9], 'table_body': 5}], [20, 20])


def test_model_symlink_escape_and_relative_root(tmp_path, monkeypatch):
    root = tmp_path / 'models'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.write_text('synthetic')
    (root / 'weights').symlink_to(outside)
    with pytest.raises(ValueError, match='outside model root'):
        runner.check_model_tree(root, 'weights')
    with pytest.raises(ValueError, match='traversal'):
        runner.model_path(root, '../outside')
    monkeypatch.setenv('RT_PADDLE_VL_MODELS', 'relative/models')
    with pytest.raises(ValueError, match='absolute'):
        runner.check_models('paddleocr_vl')


def test_layout_pin_is_checked_before_paddlex_import(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.importlib.metadata, 'version', lambda name: '3.6.0')
    with pytest.raises(ValueError, match='3.7.0'):
        runner.paddle_vl_layout_stage(tmp_path / 'absent.png')


def test_figures_only_vl_page_cleanup(tmp_path, monkeypatch):
    image = tmp_path / 'page.png'
    Image.new('RGB', (20, 20)).save(image)
    model_root = tmp_path / 'models'
    (model_root / runner.VL_REC_DIR).mkdir(parents=True)
    monkeypatch.setenv('RT_PADDLE_VL_MODELS', str(model_root))
    monkeypatch.setattr(runner, 'check_models', lambda _: {'version': 'v1.6'})
    monkeypatch.setattr(runner, 'run_paddle_stage', lambda *a: [
        {'label': 'image', 'coordinate': [1, 2, 18, 19], 'score': .8, 'order': 1}])
    def forbidden(*a, **kw):
        pytest.fail('Figure-only region must not invoke generation')
    model = SimpleNamespace(eval=lambda: SimpleNamespace(generate=forbidden))
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(bfloat16='synthetic', inference_mode=contextlib.nullcontext))
    monkeypatch.setitem(sys.modules, 'transformers', SimpleNamespace(
        AutoConfig=SimpleNamespace(from_pretrained=lambda *a, **kw: None),
        AutoProcessor=SimpleNamespace(from_pretrained=lambda *a, **kw: SimpleNamespace()),
        PaddleOCRVLForConditionalGeneration=SimpleNamespace(from_pretrained=lambda *a, **kw: model)))
    result = runner.paddle_vl_page(image, tmp_path / 'result.json')
    assert result['blocks'][0]['type'] == 'figure'
    assert result['blocks'][0]['text'] == ''
    assert result['blocks'][0]['metadata']['layout_parser_version'] == '3.7.0'


@pytest.mark.parametrize('mode', ['ok', 'oversize', 'timeout'])
def test_helper_uses_private_file_clean_environment_and_reaps(tmp_path, monkeypatch, mode):
    monkeypatch.setenv('RT_PADDLE_VL_MODELS', str(tmp_path))
    monkeypatch.setenv('API_KEY', 'synthetic-must-not-propagate')
    monkeypatch.setenv('HF_TOKEN', 'synthetic-must-not-propagate')
    monkeypatch.setattr(runner, 'paddle_python_path', lambda: Path(sys.executable))
    real_popen = subprocess.Popen
    children = []
    table = '<fcel>' + 'x' * 150000 + '<nl>'  # larger than Linux single-argument bound
    def fake_stage(command, **kwargs):
        assert table not in command
        assert 'API_KEY' not in kwargs['env'] and 'HF_TOKEN' not in kwargs['env']
        assert kwargs['env']['HF_HUB_OFFLINE'] == '1'
        assert kwargs['env']['CUDA_VISIBLE_DEVICES'] == ''
        assert Path(kwargs['env']['HOME']).is_relative_to(tmp_path)
        assert kwargs['env']['TMPDIR'] == kwargs['env']['HOME']
        if mode == 'ok':
            code = 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))))'
        elif mode == 'oversize':
            code = 'print("x" * 200000)'
        else:
            code = 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'
        proc = real_popen([sys.executable, '-c', code, command[-1]], **kwargs)
        children.append(proc)
        return proc
    monkeypatch.setattr(runner.subprocess, 'Popen', fake_stage)
    monkeypatch.setattr(runner, 'MAX_RESULT_BYTES', 180000)
    if mode == 'ok':
        assert runner.run_paddle_stage('--otsl-to-html', [table], tmp_path, time.monotonic() + 5) == [table]
    else:
        with pytest.raises(ValueError, match='bounds|time budget'):
            runner.run_paddle_stage('--otsl-to-html', [table], tmp_path, time.monotonic() + (.15 if mode == 'timeout' else 5))
    assert children[0].poll() is not None
    assert not list(tmp_path.glob('vl-stage-*'))


def test_result_provenance_and_geometry_cannot_pass_on_version_presence_only():
    result = {'engine': 'mineru', 'version': '4.2.2', 'device': 'cpu', 'page_info': [20, 20],
              'blocks': [{'type': 'equation', 'text': 'x^2', 'bbox': [.1, .2, .5, .8], 'metadata': {}}]}
    validation.validate_result(result, 'mineru', '4.2.2', 'cpu')
    with pytest.raises(ValueError, match='provenance'):
        validation.validate_result({**result, 'version': '2.7.6'}, 'mineru', '4.2.2', 'cpu')
    result['blocks'][0]['bbox'] = [1.1, .2, 1.5, .8]
    with pytest.raises(ValueError, match='geometry'):
        validation.validate_result(result, 'mineru', '4.2.2', 'cpu')
    assert server.runner_env('paddleocr_vl', Path('/tmp'))['HF_HUB_DISABLE_IMPLICIT_TOKEN'] == '1'
