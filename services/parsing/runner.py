"""Fixed, offline runners for PaddleOCR 3.7.0 / MinerU 2.7.6 pipeline.

Model provisioning belongs to the deployment process, never this entrypoint.
"""
import contextlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import sys
import time

# Also works as an absolute script in an isolated interpreter without PYTHONPATH.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.parsing.validation import MAX_BLOCKS, MAX_RESULT_BYTES, normalized_box, validate_input

PINS = {'paddleocr': '3.7.0', 'mineru': '2.7.6'}
DETECTOR = 'PP-OCRv5_mobile_det'
RECOGNIZER = 'PP-OCRv5_mobile_rec'


def check_models(engine):
    version = importlib.metadata.version(engine)
    if version != PINS[engine]:
        raise ValueError(f'{engine} requires tested API version {PINS[engine]}; found {version}')
    if engine == 'paddleocr':
        root = Path(os.environ['RT_PADDLE_MODELS'])
        for model in (DETECTOR, RECOGNIZER):
            directory = root / model
            for name in ('inference.json', 'inference.pdiparams', 'inference.yml'):
                if not (directory / name).is_file() or (directory / name).stat().st_size == 0:
                    raise ValueError(f'Offline PaddleOCR model incomplete: {model}/{name}')
        return {'version': version, 'models': [DETECTOR, RECOGNIZER]}
    config_path = Path(os.environ['MINERU_TOOLS_CONFIG_JSON'])
    if config_path.stat().st_size > 65536:
        raise ValueError('MinerU config too large')
    config = json.loads(config_path.read_text())
    # Only a sanitized local pipeline root is accepted, no provider/LLM config.
    if set(config) != {'models-dir'} or set(config['models-dir']) != {'pipeline'}:
        raise ValueError('MinerU config must contain only local models-dir.pipeline')
    root = Path(config['models-dir']['pipeline'])
    if not root.is_absolute() or not root.is_dir():
        raise ValueError('MinerU local pipeline model root missing')
    # Official pipeline model paths are versioned with the installed package.
    from mineru.utils.enum_class import ModelPath
    required = []
    for key, value in vars(ModelPath).items():
        if key.startswith('_') or not isinstance(value, str):
            continue
        if value.endswith(('.pt', '.pth', '.onnx', '.bin', '.safetensors')):
            required.append(value)
    if not required:
        raise ValueError('MinerU model-path API unavailable')
    for relative in required:
        target = root / relative
        if not target.is_file() or target.stat().st_size == 0:
            raise ValueError(f'MinerU local model missing: {relative}')
    # Formula and OCR are directory models, not covered by the file constants.
    formula = root / ModelPath.unimernet_small
    if not (formula / 'config.json').is_file() or not any(
            p.is_file() and p.stat().st_size > 0
            for pattern in ('*.safetensors', '*.bin') for p in formula.glob(pattern)):
        raise ValueError('MinerU local Unimernet model incomplete')
    import yaml
    package_root = Path(importlib.util.find_spec('mineru').origin).parent
    ocr_config = yaml.safe_load((package_root / 'model/utils/pytorchocr/utils/resources/models_config.yml').read_text())
    for language in ('ch', 'ch_lite'):
        for key in ('det', 'rec'):
            relative = str(Path(ModelPath.pytorch_paddle) / ocr_config['lang'][language][key])
            target = root / relative
            if not target.is_file() or not target.stat().st_size:
                raise ValueError(f'MinerU OCR model missing: {relative}')
            required.append(relative)
    required.append(ModelPath.unimernet_small)
    return {'version': version, 'models': required}


def preflight(engine):
    info = check_models(engine)
    if engine == 'paddleocr':
        import paddle
        from paddleocr import PaddleOCR  # noqa: F401
        info['runtime_version'] = paddle.__version__
    else:
        import torch
        from mineru.cli.common import do_parse  # noqa: F401
        info['runtime_version'] = torch.__version__
    return {**info, 'preflight_ok': True, 'inference_verified': False,
            'detail': 'Imports and local files checked; inference has not run in this process'}


def paddle_page(input_path, output_path):
    width, height = validate_input('paddleocr', input_path)
    info = check_models('paddleocr')
    from paddleocr import PaddleOCR
    model_root = Path(os.environ['RT_PADDLE_MODELS'])
    started = time.monotonic()
    ocr = PaddleOCR(
        device='cpu', text_detection_model_name=DETECTOR, text_recognition_model_name=RECOGNIZER,
        text_detection_model_dir=str(model_root / DETECTOR),
        text_recognition_model_dir=str(model_root / RECOGNIZER),
        use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
        cpu_threads=2, enable_mkldnn=False, text_det_limit_side_len=1600, text_det_limit_type='max',
        text_recognition_batch_size=1,
    )
    predictions = ocr.predict(str(input_path))
    lines = []
    for prediction in predictions:
        result = prediction.json
        if callable(result):
            result = result()
        if isinstance(result, str):
            result = json.loads(result)
        result = result.get('res', result)
        for text, score, polygon in zip(result['rec_texts'], result['rec_scores'], result['rec_polys'], strict=True):
            if not isinstance(text, str) or not math.isfinite(float(score)) or not 0 <= float(score) <= 1:
                raise ValueError('PaddleOCR invalid recognition result')
            xs = [float(p[0]) for p in polygon]
            ys = [float(p[1]) for p in polygon]
            if text.strip():
                lines.append({'text': text, 'confidence': float(score),
                              'bbox': normalized_box([min(xs), min(ys), max(xs), max(ys)], width, height)})
            if len(lines) > MAX_BLOCKS:
                raise ValueError('OCR result exceeds block bounds')
    return {'engine': 'paddleocr', **info, 'device': 'cpu', 'width': width, 'height': height,
            'lines': lines, 'elapsed_seconds': time.monotonic() - started}


def read_json(path):
    if path.stat().st_size > MAX_RESULT_BYTES:
        raise ValueError('Parser result exceeds bounds')
    return json.loads(path.read_text())


def normalize_mineru(content, middle):
    pages = middle.get('pdf_info', [])
    if len(pages) != 1 or not isinstance(content, list) or len(content) > MAX_BLOCKS:
        raise ValueError('MinerU single-page output contract violated')
    size = pages[0].get('page_size')
    if not size or len(size) != 2 or any(not math.isfinite(float(x)) or float(x) <= 0 for x in size):
        raise ValueError('MinerU page geometry missing')
    blocks = []
    for item in content:
        if item.get('page_idx', 0) != 0:
            raise ValueError('MinerU returned an unexpected page')
        # Missing geometry must fail visibly, not silently drop evidence.
        bbox = normalized_box(item.get('bbox'), 1000, 1000)
        kind = item.get('type', 'text')
        text = item.get('text', '')
        if kind == 'table':
            text = '\n'.join(item.get('table_caption', []) + [item.get('table_body', '')] + item.get('table_footnote', []))
        elif kind == 'image':
            text = '\n'.join(item.get('image_caption', []) + item.get('image_footnote', []))
        if not isinstance(text, str):
            raise ValueError('MinerU returned non-text content')
        blocks.append({'bbox': bbox, 'type': {'text': 'paragraph', 'equation': 'equation',
                       'table': 'table', 'image': 'figure'}.get(kind, 'paragraph'), 'text': text,
                       'metadata': {'mineru_type': kind, 'text_level': item.get('text_level'),
                                    'reconstruction': 'MinerU structured output; verify against original region'}})
    return blocks, size


def mineru_page(input_path, output_path):
    validate_input('mineru', input_path)
    info = check_models('mineru')
    import torch
    device = os.getenv('MINERU_DEVICE_MODE', 'cpu')
    if device not in ('cpu', 'cuda'):
        raise ValueError('Unsupported MinerU device')
    if device == 'cuda':
        if not torch.cuda.is_available():
            raise ValueError('CUDA unavailable; GPU test cannot silently fall back')
        total = torch.cuda.get_device_properties(0).total_memory
        cap = int(os.environ['RT_GPU_LIMIT_MIB']) * 1048576
        torch.cuda.set_per_process_memory_fraction(min(1.0, cap / total), 0)
        torch.cuda.reset_peak_memory_stats(0)
        # Lets the broker detect WSL missing PID attribution once CUDA initialized.
        Path(output_path).with_suffix('.cuda-started').touch(mode=0o600)
    from mineru.cli.common import do_parse
    output = Path(output_path).parent / 'mineru-result'
    output.mkdir(exist_ok=True)
    started = time.monotonic()
    do_parse(str(output), ['page'], [Path(input_path).read_bytes()], ['ch'], backend='pipeline',
             parse_method='auto', formula_enable=True, table_enable=True, start_page_id=0, end_page_id=0,
             f_dump_md=False, f_dump_middle_json=True, f_dump_model_output=False,
             f_dump_orig_pdf=False, f_dump_content_list=True, f_draw_layout_bbox=False, f_draw_span_bbox=False)
    contents = list(output.rglob('*_content_list.json'))
    middles = list(output.rglob('*_middle.json'))
    if len(contents) != 1 or len(middles) != 1:
        raise ValueError('MinerU did not produce structured content and source geometry')
    blocks, size = normalize_mineru(read_json(contents[0]), read_json(middles[0]))
    return {'engine': 'mineru', **info, 'device': device, 'backend': 'pipeline', 'blocks': blocks,
            'page_info': size, 'elapsed_seconds': time.monotonic() - started,
            'cuda_peak_allocated_mib': torch.cuda.max_memory_allocated() / 1048576 if device == 'cuda' else 0,
            'cuda_peak_reserved_mib': torch.cuda.max_memory_reserved() / 1048576 if device == 'cuda' else 0}


if __name__ == '__main__':
    from services.parsing.offline import disable_network
    disable_network()
    if len(sys.argv) == 3 and sys.argv[1] == '--check':
        with contextlib.redirect_stdout(sys.stderr):
            result = preflight(sys.argv[2])
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    else:
        engine, input_path, output_path = sys.argv[1:4]
        if engine not in PINS:
            raise SystemExit('Unsupported parser')
        started = time.monotonic()
        with contextlib.redirect_stdout(sys.stderr):
            result = paddle_page(input_path, output_path) if engine == 'paddleocr' else mineru_page(input_path, output_path)
        result['total_seconds'] = time.monotonic() - started
        result['peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        payload = json.dumps(result, ensure_ascii=False, allow_nan=False)
        if len(payload.encode()) > MAX_RESULT_BYTES:
            raise ValueError('Parser result exceeds bounds')
        temporary = Path(output_path).with_suffix('.tmp')
        temporary.write_text(payload)
        temporary.replace(output_path)
