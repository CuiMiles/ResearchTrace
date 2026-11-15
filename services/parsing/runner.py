"""Fixed, offline runners for PaddleOCR 3.7.0 / PaddleOCR-VL-1.6 / MinerU 4.2.2 pipeline.

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
import subprocess
import sys
import time

# Also works as an absolute script in an isolated interpreter without PYTHONPATH.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.parsing.validation import MAX_BLOCKS, MAX_RESULT_BYTES, normalized_box, validate_input

ROOT = Path(__file__).resolve().parents[2]
PINS = {'paddleocr': '3.7.0', 'paddleocr_vl': 'v1.6', 'mineru': '4.2.2'}
DETECTOR = 'PP-OCRv5_mobile_det'
RECOGNIZER = 'PP-OCRv5_mobile_rec'
VL_LAYOUT_MODEL = 'PP-DocLayoutV3'
VL_REC_DIR = 'PaddleOCR-VL-1.6'
VL_REC_MODEL = 'PaddleOCR-VL-1.6-0.9B'
VL_REQUIRED_FILES = (
    'config.json',
    'model.safetensors',
    'tokenizer.json',
    'tokenizer.model',
    'preprocessor_config.json',
    'processor_config.json',
)


def paddle_python_path():
    return Path(os.getenv('RT_PADDLE_PYTHON', str(ROOT / '.tools/paddle-env/bin/python'))).absolute()


def check_models(engine):
    if engine == 'paddleocr_vl':
        root = Path(os.environ['RT_PADDLE_VL_MODELS'])
        layout_dir = root / VL_LAYOUT_MODEL
        for name in ('inference.json', 'inference.pdiparams', 'inference.yml'):
            if not (layout_dir / name).is_file() or (layout_dir / name).stat().st_size == 0:
                raise ValueError(f'Offline PaddleOCR-VL layout model incomplete: {VL_LAYOUT_MODEL}/{name}')
        vlm_dir = root / VL_REC_DIR
        for name in VL_REQUIRED_FILES:
            if not (vlm_dir / name).is_file() or (vlm_dir / name).stat().st_size == 0:
                raise ValueError(f'Offline PaddleOCR-VL recognition model incomplete: {VL_REC_DIR}/{name}')
        if not paddle_python_path().is_file():
            raise ValueError('PaddleOCR layout interpreter unavailable for PaddleOCR-VL-1.6')
        for pkg in ('torch', 'transformers'):
            if importlib.util.find_spec(pkg) is None:
                raise ValueError(f'PaddleOCR-VL-1.6 runtime package missing: {pkg}')
        return {'version': PINS['paddleocr_vl'], 'models': [VL_LAYOUT_MODEL, VL_REC_MODEL]}
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
    base_dir = Path(os.environ.get('MINERU_MODEL_BASE_DIR', ''))
    if not base_dir.is_absolute() or not base_dir.is_dir():
        raise ValueError('MinerU 4.2.2 local MINERU_MODEL_BASE_DIR missing')
    if os.environ.get('MINERU_MODEL_SOURCE', '') != 'local':
        raise ValueError('MinerU 4.2.2 requires MINERU_MODEL_SOURCE=local')
    if os.environ.get('MINERU_MODEL_SMALL_BACKEND', '') != 'torch':
        raise ValueError('MinerU 4.2.2 requires MINERU_MODEL_SMALL_BACKEND=torch')
    # Reject any injected remote VLM URL/provider env in the isolated runner.
    for key in ('MINERU_MODEL_VLM_SERVER_URL', 'MINERU_VLM_SERVER_URL'):
        if os.environ.get(key):
            raise ValueError(f'Remote MinerU VLM config not permitted: {key}')
    from mineru.model.download import verify_model_repo
    from mineru.model.registry import MINERU_2_5_PRO_2605_1_2B_GGUF, MINERU_4_MODELS_TORCH

    small_ready = verify_model_repo(MINERU_4_MODELS_TORCH)
    if not small_ready.ready:
        raise ValueError(f'MinerU 4.2.2 local torch models incomplete: {", ".join(small_ready.missing_paths)}')
    models = [f'{MINERU_4_MODELS_TORCH.name}/{rel}' for rel in MINERU_4_MODELS_TORCH.paths.values()]
    gguf_ready = verify_model_repo(MINERU_2_5_PRO_2605_1_2B_GGUF)
    if gguf_ready.ready:
        models.extend(f'{MINERU_2_5_PRO_2605_1_2B_GGUF.name}/{rel}' for rel in MINERU_2_5_PRO_2605_1_2B_GGUF.paths.values())
    return {'version': version, 'models': models}


def preflight(engine):
    info = check_models(engine)
    if engine == 'paddleocr':
        import paddle
        from paddleocr import PaddleOCR  # noqa: F401
        info['runtime_version'] = paddle.__version__
    elif engine == 'paddleocr_vl':
        import torch
        from transformers import AutoConfig, AutoProcessor, PaddleOCRVLForConditionalGeneration  # noqa: F401
        info['runtime_version'] = torch.__version__
    else:
        import torch
        from mineru.backend.analyze import doc_analyze  # noqa: F401
        from mineru.render import render_content_list  # noqa: F401
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


def normalize_mineru(content, size):
    if not isinstance(content, list) or len(content) > MAX_BLOCKS:
        raise ValueError('MinerU single-page output contract violated')
    if not size or len(size) != 2 or any(not math.isfinite(float(x)) or float(x) <= 0 for x in size):
        raise ValueError('MinerU page geometry missing')
    blocks = []
    for item in content:
        if item.get('page_idx', 0) != 0:
            raise ValueError('MinerU returned an unexpected page')
        # Missing geometry must fail visibly, not silently drop evidence.
        bbox = normalized_box(item.get('bbox'), 1000, 1000)
        kind = item.get('type', 'text')
        if kind == 'table':
            parts = item.get('table_caption', []) + [item.get('table_body', '')] + item.get('table_footnote', [])
            text = '\n'.join(p for p in parts if isinstance(p, str) and p)
        elif kind == 'image':
            parts = item.get('image_caption', []) + ([item['content']] if isinstance(item.get('content'), str) else []) + item.get('image_footnote', [])
            text = '\n'.join(p for p in parts if isinstance(p, str) and p)
        elif kind == 'chart':
            parts = item.get('chart_caption', []) + ([item['content']] if isinstance(item.get('content'), str) else []) + item.get('chart_footnote', [])
            text = '\n'.join(p for p in parts if isinstance(p, str) and p)
        elif kind == 'code':
            parts = item.get('code_caption', []) + [item.get('code_body', '')] + item.get('code_footnote', [])
            text = '\n'.join(p for p in parts if isinstance(p, str) and p)
        elif kind in ('list', 'index'):
            text = '\n'.join(x for x in item.get('list_items', []) if isinstance(x, str) and x)
        else:
            text = item.get('text', '')
        if not isinstance(text, str):
            raise ValueError('MinerU returned non-text content')
        blocks.append({'bbox': bbox, 'type': {'text': 'paragraph', 'equation': 'equation',
                       'table': 'table', 'image': 'figure', 'chart': 'figure'}.get(kind, 'paragraph'), 'text': text,
                       'metadata': {'mineru_type': kind, 'text_level': item.get('text_level'),
                                    'reconstruction': 'MinerU structured output; verify against original region'}})
    return blocks, list(size)


def mineru_page(input_path, output_path):
    size = validate_input('mineru', input_path)
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
    from mineru.backend.analyze import doc_analyze
    from mineru.render import render_content_list
    started = time.monotonic()
    middle_json, _ = doc_analyze(
        Path(input_path).read_bytes(),
        effort='medium',
        parse_mode='auto',
        image_analysis=False,
        file_suffix='pdf',
    )
    if len(middle_json.pages) != 1:
        raise ValueError('MinerU single-page output contract violated')
    content = render_content_list(middle_json)
    blocks, size = normalize_mineru(content, size)
    return {'engine': 'mineru', **info, 'device': device, 'backend': 'hybrid-torch', 'blocks': blocks,
            'page_info': size, 'elapsed_seconds': time.monotonic() - started,
            'cuda_peak_allocated_mib': torch.cuda.max_memory_allocated() / 1048576 if device == 'cuda' else 0,
            'cuda_peak_reserved_mib': torch.cuda.max_memory_reserved() / 1048576 if device == 'cuda' else 0}


def paddle_vl_layout_stage(input_path):
    """Run Stage 1 PP-DocLayoutV3 inside the Paddle environment (offline, bounded)."""
    model_dir = Path(os.environ['RT_PADDLE_VL_MODELS']) / VL_LAYOUT_MODEL
    from paddlex import create_model
    from paddlex.inference.pipelines.paddleocr_vl.uilts import filter_overlap_boxes

    detector = create_model(VL_LAYOUT_MODEL, model_dir=str(model_dir), device='cpu')
    outputs = list(detector.predict(str(input_path), threshold=0.3, layout_nms=True))
    boxes = []
    for item in outputs:
        filtered = filter_overlap_boxes(item, layout_shape_mode='auto')
        raw_boxes = filtered.get('boxes', []) if isinstance(filtered, dict) else []
        for entry in raw_boxes:
            coord = entry.get('coordinate')
            if not coord or len(coord) != 4:
                continue
            boxes.append({
                'label': str(entry.get('label', 'text')),
                'score': float(entry.get('score', 0.0)),
                'coordinate': [float(v) for v in coord],
                'order': entry.get('order'),
            })
    boxes.sort(key=lambda b: (b['order'] is None, b['order'] if b['order'] is not None else 0, b['coordinate'][1], b['coordinate'][0]))
    return boxes


def paddle_vl_otsl_stage(payload_json):
    """Convert OTSL table strings returned by PaddleOCR-VL-1.6 into HTML using PaddleX."""
    from paddlex.inference.pipelines.paddleocr_vl.uilts import convert_otsl_to_html
    texts = json.loads(payload_json)
    return [convert_otsl_to_html(t) if ('<fcel>' in t or '<nl>' in t or '<ecel>' in t) else t for t in texts]


def _vl_label_spec(label):
    if label in ('image', 'header_image', 'footer_image'):
        return 'figure', None, None
    if label == 'table':
        return 'table', 'Table Recognition:', None
    if 'formula' in label and label != 'formula_number':
        return 'equation', 'Formula Recognition:', None
    if label == 'doc_title':
        return 'heading', 'OCR:', 1
    if label == 'paragraph_title':
        return 'heading', 'OCR:', 2
    if label == 'chart':
        return 'figure', 'OCR:', None
    return 'paragraph', 'OCR:', None


def paddle_vl_page(input_path, output_path):
    width, height = validate_input('paddleocr_vl', input_path)
    info = check_models('paddleocr_vl')
    started = time.monotonic()
    # Stage 1 runs PP-DocLayoutV3 in a short-lived child inside the same process group
    # and exits before loading the 0.9B VLM so host peak RSS stays under ~2.5 GiB.
    stage1 = subprocess.run(
        [str(paddle_python_path()), str(Path(__file__).resolve()), '--layout-v3', str(input_path)],
        capture_output=True, text=True, check=True,
    )
    boxes = json.loads(stage1.stdout)
    if not boxes:
        boxes = [{'label': 'text', 'score': 1.0, 'coordinate': [0.0, 0.0, float(width), float(height)], 'order': 1}]
    if len(boxes) > MAX_BLOCKS:
        boxes = boxes[:MAX_BLOCKS]

    import torch
    from PIL import Image
    from transformers import AutoConfig, AutoProcessor, PaddleOCRVLForConditionalGeneration

    vlm_dir = str(Path(os.environ['RT_PADDLE_VL_MODELS']) / VL_REC_DIR)
    cfg = AutoConfig.from_pretrained(vlm_dir, trust_remote_code=False, local_files_only=True)
    proc = AutoProcessor.from_pretrained(vlm_dir, trust_remote_code=True, local_files_only=True)
    model = PaddleOCRVLForConditionalGeneration.from_pretrained(
        vlm_dir, config=cfg, local_files_only=True, dtype=torch.bfloat16,
    ).eval()

    blocks = []
    otsl_indices = []
    with Image.open(input_path) as raw_img:
        page_img = raw_img.convert('RGB')
        for box in boxes:
            label = str(box.get('label', 'text'))
            x0, y0, x1, y1 = [float(v) for v in box['coordinate']]
            x0c = max(0, min(width - 1, int(math.floor(x0))))
            y0c = max(0, min(height - 1, int(math.floor(y0))))
            x1c = max(x0c + 1, min(width, int(math.ceil(x1))))
            y1c = max(y0c + 1, min(height, int(math.ceil(y1))))
            norm = normalized_box([x0c, y0c, x1c, y1c], width, height)
            kind, prompt_label, text_level = _vl_label_spec(label)
            text = ''
            if prompt_label is not None:
                crop = page_img.crop((x0c, y0c, x1c, y1c))
                if crop.width < 8 or crop.height < 8:
                    crop = crop.resize((max(8, crop.width), max(8, crop.height)))
                messages = [{'role': 'user', 'content': [{'type': 'image', 'image': crop}, {'type': 'text', 'text': prompt_label}]}]
                prompt = proc.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                inputs = proc(text=prompt, images=crop, return_tensors='pt')
                with torch.inference_mode():
                    ids = model.generate(**inputs, max_new_tokens=1024, use_cache=True)
                text = proc.batch_decode(ids[:, inputs['input_ids'].shape[1]:], skip_special_tokens=True)[0].strip()
            if kind == 'table' and ('<fcel>' in text or '<nl>' in text or '<ecel>' in text):
                otsl_indices.append(len(blocks))
            meta = {
                'vl_label': label,
                'layout_score': float(box.get('score', 0.0)),
                'pipeline_version': 'v1.6',
                'dtype': 'bfloat16',
                'reconstruction': 'PaddleOCR-VL-1.6 structured output; verify against original region',
            }
            if text_level is not None:
                meta['text_level'] = text_level
            if text or kind == 'figure':
                blocks.append({'bbox': norm, 'type': kind, 'text': text, 'metadata': meta})
    if otsl_indices:
        raw_tables = [blocks[i]['text'] for i in otsl_indices]
        converted = subprocess.run(
            [str(paddle_python_path()), str(Path(__file__).resolve()), '--otsl-to-html', json.dumps(raw_tables)],
            capture_output=True, text=True, check=True,
        )
        for idx, html_table in zip(otsl_indices, json.loads(converted.stdout), strict=True):
            blocks[idx]['text'] = html_table
    return {'engine': 'paddleocr_vl', **info, 'device': 'cpu', 'backend': 'bfloat16-transformers',
            'width': width, 'height': height, 'blocks': blocks, 'elapsed_seconds': time.monotonic() - started}


if __name__ == '__main__':
    from services.parsing.offline import disable_network
    disable_network()
    if len(sys.argv) == 3 and sys.argv[1] == '--layout-v3':
        with contextlib.redirect_stdout(sys.stderr):
            boxes = paddle_vl_layout_stage(sys.argv[2])
        print(json.dumps(boxes, ensure_ascii=False, allow_nan=False))
    elif len(sys.argv) == 3 and sys.argv[1] == '--otsl-to-html':
        with contextlib.redirect_stdout(sys.stderr):
            converted = paddle_vl_otsl_stage(sys.argv[2])
        print(json.dumps(converted, ensure_ascii=False, allow_nan=False))
    elif len(sys.argv) == 3 and sys.argv[1] == '--check':
        with contextlib.redirect_stdout(sys.stderr):
            result = preflight(sys.argv[2])
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    else:
        engine, input_path, output_path = sys.argv[1:4]
        if engine not in PINS:
            raise SystemExit('Unsupported parser')
        started = time.monotonic()
        with contextlib.redirect_stdout(sys.stderr):
            if engine == 'paddleocr':
                result = paddle_page(input_path, output_path)
            elif engine == 'paddleocr_vl':
                result = paddle_vl_page(input_path, output_path)
            else:
                result = mineru_page(input_path, output_path)
        result['total_seconds'] = time.monotonic() - started
        result['peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        payload = json.dumps(result, ensure_ascii=False, allow_nan=False)
        if len(payload.encode()) > MAX_RESULT_BYTES:
            raise ValueError('Parser result exceeds bounds')
        temporary = Path(output_path).with_suffix('.tmp')
        temporary.write_text(payload)
        temporary.replace(output_path)
