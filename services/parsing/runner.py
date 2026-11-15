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
import re
import resource
import subprocess
import sys
import tempfile
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
    'tokenizer_config.json',
    'processing_paddleocr_vl.py',
    'image_processing_paddleocr_vl.py',
)
# Layout regions are much more expensive than plain OCR lines: each can start
# another autoregressive decode. Fail visibly rather than dropping regions.
MAX_VL_REGIONS = 128
MAX_VL_PAGE_TOKENS = 16384
MAX_VL_REGION_TOKENS = 1024
MAX_VL_INPUT_TOKENS = 4096
MAX_VL_TABLE_CELLS = 8192


def model_root(variable):
    root = Path(os.environ.get(variable, ''))
    if not root.is_absolute() or '..' in root.parts:
        raise ValueError('Offline model root must be absolute and contain no traversal')
    return root.resolve()


def model_path(root, relative):
    """Constrain resolved files (including symlinks) to the provisioned root."""
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Offline model path traversal')
    path = root / relative
    try:
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f'Offline model path outside model root: {relative}')
        if not resolved.exists():
            raise ValueError(f'Offline model incomplete: {relative}')
    except (OSError, RuntimeError):
        raise ValueError(f'Invalid offline model path: {relative}') from None
    return path


def check_model_tree(root, relative):
    """Check nested model/config/code files without loading weights into memory."""
    path = model_path(root, relative)
    count = 0
    if path.is_dir():
        for directory, dirs, files in os.walk(path, followlinks=False):
            for name in dirs + files:
                child = Path(directory) / name
                checked = model_path(root, child.relative_to(root))
                # os.walk does not inspect directory symlink contents. Reject
                # those instead of giving an unchecked subtree to a loader.
                if checked.is_symlink() and checked.is_dir():
                    raise ValueError('Offline model directory symlinks are not supported')
                count += 1
                if count > 10000:
                    raise ValueError('Offline model tree exceeds bounds')
    elif not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f'Offline model incomplete: {relative}')
    return path


def require_model_files(root, directory, names):
    check_model_tree(root, directory)
    for name in names:
        path = model_path(root, Path(directory) / name)
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'Offline model incomplete: {directory}/{name}')


def paddle_python_path():
    return Path(os.getenv('RT_PADDLE_PYTHON', str(ROOT / '.tools/paddle-env/bin/python'))).absolute()


def check_models(engine):
    if engine == 'paddleocr_vl':
        root = model_root('RT_PADDLE_VL_MODELS')
        require_model_files(root, VL_LAYOUT_MODEL, ('inference.json', 'inference.pdiparams', 'inference.yml'))
        require_model_files(root, VL_REC_DIR, VL_REQUIRED_FILES)
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
        root = model_root('RT_PADDLE_MODELS')
        for model in (DETECTOR, RECOGNIZER):
            require_model_files(root, model, ('inference.json', 'inference.pdiparams', 'inference.yml'))
        return {'version': version, 'models': [DETECTOR, RECOGNIZER]}
    base_dir = model_root('MINERU_MODEL_BASE_DIR')
    if not base_dir.is_dir():
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

    for repo in (MINERU_4_MODELS_TORCH, MINERU_2_5_PRO_2605_1_2B_GGUF):
        # GGUF is optional for the medium-effort pipeline, but if provisioned
        # its files must obey the same boundary as the required torch models.
        if repo is MINERU_4_MODELS_TORCH or (base_dir / repo.name).exists() or (base_dir / repo.name).is_symlink():
            check_model_tree(base_dir, repo.name)
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
        info['layout_runtime'] = run_paddle_stage('--check-layout-v3', '', Path(os.environ['TMPDIR']),
                                                 time.monotonic() + 40)
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
    with Path(path).open('rb') as stream:
        payload = stream.read(MAX_RESULT_BYTES + 1)
    if len(payload) > MAX_RESULT_BYTES:
        raise ValueError('Parser result exceeds bounds')
    def invalid_constant(value):
        raise ValueError('Parser returned non-finite JSON')
    return json.loads(payload, parse_constant=invalid_constant)


def text_parts(item, key):
    parts = item.get(key, [])
    if not isinstance(parts, list) or any(not isinstance(part, str) for part in parts):
        raise ValueError(f'MinerU returned invalid {key}')
    return parts


def normalize_mineru(content, size):
    if not isinstance(content, list) or len(content) > MAX_BLOCKS:
        raise ValueError('MinerU single-page output contract violated')
    if not size or len(size) != 2 or any(not math.isfinite(float(x)) or float(x) <= 0 for x in size):
        raise ValueError('MinerU page geometry missing')
    blocks = []
    text_bytes = 0
    for item in content:
        if not isinstance(item, dict):
            raise ValueError('MinerU returned invalid block')
        if item.get('page_idx', 0) != 0:
            raise ValueError('MinerU returned an unexpected page')
        # Missing geometry must fail visibly, not silently drop evidence.
        bbox = normalized_box(item.get('bbox'), 1000, 1000)
        kind = item.get('type', 'text')
        if kind == 'table':
            parts = text_parts(item, 'table_caption') + [item.get('table_body', '')] + text_parts(item, 'table_footnote')
        elif kind == 'image':
            parts = text_parts(item, 'image_caption') + [item.get('content', '')] + text_parts(item, 'image_footnote')
        elif kind == 'chart':
            parts = text_parts(item, 'chart_caption') + [item.get('content', '')] + text_parts(item, 'chart_footnote')
        elif kind == 'code':
            parts = text_parts(item, 'code_caption') + [item.get('code_body', '')] + text_parts(item, 'code_footnote')
        elif kind in ('list', 'index'):
            parts = text_parts(item, 'list_items')
        else:
            parts = [item.get('text', '')]
        if any(not isinstance(part, str) for part in parts):
            raise ValueError('MinerU returned non-text content')
        text = '\n'.join(part for part in parts if part)
        text_bytes += len(text.encode('utf-8'))
        if text_bytes > MAX_RESULT_BYTES:
            raise ValueError('MinerU text exceeds result bounds')
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
    check_layout_runtime()
    width, height = validate_input('paddleocr_vl', input_path)
    root = model_root('RT_PADDLE_VL_MODELS')
    require_model_files(root, VL_LAYOUT_MODEL, ('inference.json', 'inference.pdiparams', 'inference.yml'))
    model_dir = root / VL_LAYOUT_MODEL
    from paddlex import create_model
    from paddlex.inference.pipelines.paddleocr_vl.uilts import filter_overlap_boxes

    detector = create_model(VL_LAYOUT_MODEL, model_dir=str(model_dir), device='cpu')
    boxes = []
    for item in detector.predict(str(input_path), threshold=0.3, layout_nms=True):
        filtered = filter_overlap_boxes(item, layout_shape_mode='auto')
        if not isinstance(filtered, dict) or not isinstance(filtered.get('boxes'), list):
            raise ValueError('VL layout returned invalid boxes')
        raw_boxes = filtered['boxes']
        for entry in raw_boxes:
            if len(boxes) >= MAX_VL_REGIONS:
                raise ValueError('VL layout exceeds region budget')
            if not isinstance(entry, dict):
                raise ValueError('VL layout returned invalid box')
            try:
                # PaddleX coordinates/scores may be NumPy scalars or arrays;
                # normalize their representation before the strict JSON contract.
                boxes.append({**entry, 'coordinate': [float(v) for v in entry['coordinate']],
                              'score': float(entry['score']),
                              'order': float(entry['order']) if entry.get('order') is not None else None})
            except (KeyError, TypeError, ValueError, OverflowError):
                raise ValueError('VL layout returned invalid geometry or score') from None
    boxes = validate_vl_boxes(boxes, width, height)
    boxes.sort(key=lambda b: (b['order'] is None, b['order'] if b['order'] is not None else 0, b['coordinate'][1], b['coordinate'][0]))
    return boxes


def check_layout_runtime():
    version = importlib.metadata.version('paddleocr')
    if version != PINS['paddleocr']:
        raise ValueError(f'VL layout requires paddleocr {PINS["paddleocr"]}; found {version}')
    root = model_root('RT_PADDLE_VL_MODELS')
    require_model_files(root, VL_LAYOUT_MODEL, ('inference.json', 'inference.pdiparams', 'inference.yml'))
    return {'version': version, 'model': VL_LAYOUT_MODEL, 'preflight_ok': True,
            'inference_verified': False}


OTSL_TAG = re.compile(r'<(?:fcel|ecel|nl|lcel|ucel|xcel)>')


def validate_otsl_budget(text):
    # PaddleX pads ragged rows to a rectangle. Bound the *padded* work, not
    # just the short source string (one long row plus many narrow rows).
    rows = text.split('<nl>')
    widths = [len(OTSL_TAG.findall(row)) for row in rows if row.strip()]
    if len(widths) * max(widths, default=0) > MAX_VL_TABLE_CELLS:
        raise ValueError('VL table exceeds cell budget')


def paddle_vl_otsl_stage(payload_path):
    """Convert OTSL table strings returned by PaddleOCR-VL-1.6 into HTML using PaddleX."""
    texts = read_json(Path(payload_path))
    if not isinstance(texts, list) or len(texts) > MAX_VL_REGIONS or any(not isinstance(t, str) for t in texts):
        raise ValueError('VL table conversion payload invalid')
    for text in texts:
        validate_otsl_budget(text)
    from paddlex.inference.pipelines.paddleocr_vl.uilts import convert_otsl_to_html
    return [convert_otsl_to_html(t) if OTSL_TAG.search(t) else t for t in texts]


def validate_vl_boxes(boxes, width, height):
    if not isinstance(boxes, list) or len(boxes) > min(MAX_BLOCKS, MAX_VL_REGIONS):
        raise ValueError('VL layout exceeds region budget or is invalid')
    valid = []
    for box in boxes:
        if not isinstance(box, dict) or not isinstance(box.get('label'), str):
            raise ValueError('VL layout returned invalid label')
        norm = normalized_box(box.get('coordinate'), width, height)
        score, order = box.get('score'), box.get('order')
        if (isinstance(score, bool) or not isinstance(score, (float, int))
                or not math.isfinite(score) or not 0 <= score <= 1):
            raise ValueError('VL layout returned invalid score')
        if order is not None and (isinstance(order, bool) or not isinstance(order, (int, float)) or not math.isfinite(order)):
            raise ValueError('VL layout returned invalid reading order')
        valid.append({'label': box['label'], 'score': float(score), 'order': float(order) if order is not None else None,
                      'coordinate': [norm[0] * width, norm[1] * height, norm[2] * width, norm[3] * height]})
    return valid


def normalize_vl_text(text, label):
    if not isinstance(text, str):
        raise ValueError('VL recognition returned invalid text')
    text = text.strip().replace(r'\[\[', r'\[').replace(r'\]\]', r'\]')
    # Preserve currency and escaped dollars; only convert explicit math pairs.
    text = re.sub(r'\\\((.*?)\\\)', lambda m: '$' + m[1].strip() + '$', text, flags=re.S)
    text = re.sub(r'\\\[(.*?)\\\]', lambda m: '$$' + m[1].strip() + '$$', text, flags=re.S)
    if label == 'formula_number':
        text = text.strip('$').strip()
    return text


def run_paddle_stage(flag, payload, directory, deadline):
    """Bound helper output on disk; helpers stay in the broker-owned session.

    Table text is private file content, never argv (ARG_MAX and process-list
    exposure). The direct child is reaped even on errors; the broker additionally
    cleans all session descendants on cancellation and every other exit path.
    """
    from services.parsing.offline import OFFLINE_ENV
    with tempfile.TemporaryDirectory(prefix='vl-stage-', dir=directory) as scratch:
        scratch = Path(scratch)
        argument = str(payload)
        if flag == '--otsl-to-html':
            argument = str(scratch / 'input.json')
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
            if len(encoded) > MAX_RESULT_BYTES:
                raise ValueError('VL helper input exceeds bounds')
            Path(argument).write_bytes(encoded)
        interpreter = paddle_python_path()
        env = {**OFFLINE_ENV,
               'PATH': str(interpreter.parent) + ':/usr/bin:/bin',
               'HOME': str(scratch), 'TMPDIR': str(scratch), 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
               'PYTHONNOUSERSITE': '1', 'PYTHONUNBUFFERED': '1',
               'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2',
               'CUDA_VISIBLE_DEVICES': '', 'RT_PADDLE_VL_MODELS': str(model_root('RT_PADDLE_VL_MODELS')),
               'HF_HOME': str(scratch / 'hf'), 'MODELSCOPE_CACHE': str(scratch / 'modelscope'),
               'PADDLE_PDX_CACHE_HOME': str(scratch / 'paddle')}
        stdout_path, stderr_path = scratch / 'stdout.json', scratch / 'stderr.log'
        if time.monotonic() >= deadline:
            raise ValueError('VL page time budget exceeded')
        with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
            args = [flag] if flag == '--check-layout-v3' else [flag, argument]
            child = subprocess.Popen([str(interpreter), str(Path(__file__).resolve()), *args],
                                     stdout=stdout, stderr=stderr, cwd=scratch, env=env)
            try:
                while True:
                    if stdout_path.stat().st_size > MAX_RESULT_BYTES or stderr_path.stat().st_size > 8 * 1024 * 1024:
                        raise ValueError('VL helper output exceeds bounds')
                    if time.monotonic() >= deadline:
                        raise ValueError('VL page time budget exceeded')
                    if child.poll() is not None:
                        break
                    time.sleep(.05)
                if child.returncode:
                    # Keep a bounded diagnostic in the broker's private runner log.
                    with stderr_path.open('rb') as log:
                        print(log.read(8192).decode('utf-8', errors='replace'), file=sys.stderr)
                    raise ValueError('VL helper failed; see private runner diagnostics')
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=.5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                child.wait(timeout=5)
        return read_json(stdout_path)


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
    deadline = started + min(900, max(1, int(os.getenv('RT_PARSER_TIMEOUT_SECONDS', '300'))))
    # Stage 1 runs PP-DocLayoutV3 in a short-lived child inside the same process group
    # and exits before loading the 0.9B VLM so host peak RSS stays under ~2.5 GiB.
    boxes = validate_vl_boxes(run_paddle_stage('--layout-v3', input_path, Path(output_path).parent, deadline), width, height)
    fallback = not boxes
    if not boxes:
        boxes = [{'label': 'text', 'score': 0.0, 'coordinate': [0.0, 0.0, float(width), float(height)], 'order': 1}]

    import torch
    from PIL import Image
    from transformers import AutoConfig, AutoProcessor, PaddleOCRVLForConditionalGeneration

    vlm_dir = str(model_path(model_root('RT_PADDLE_VL_MODELS'), VL_REC_DIR))
    cfg = AutoConfig.from_pretrained(vlm_dir, trust_remote_code=False, local_files_only=True)
    proc = AutoProcessor.from_pretrained(vlm_dir, trust_remote_code=True, local_files_only=True)
    model = PaddleOCRVLForConditionalGeneration.from_pretrained(
        vlm_dir, config=cfg, local_files_only=True, dtype=torch.bfloat16,
    ).eval()

    blocks = []
    otsl_indices = []
    tokens_used = 0
    text_bytes = 0
    inputs = ids = None
    with Image.open(input_path) as raw_img:
        page_img = raw_img.convert('RGB')
        for box in boxes:
            if time.monotonic() >= deadline:
                raise ValueError('VL page time budget exceeded')
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
                if inputs['input_ids'].shape[1] > MAX_VL_INPUT_TOKENS:
                    raise ValueError('VL input token budget exceeded')
                available = min(MAX_VL_REGION_TOKENS, MAX_VL_PAGE_TOKENS - tokens_used)
                if available <= 0:
                    raise ValueError('VL page token budget exceeded')
                with torch.inference_mode():
                    ids = model.generate(**inputs, max_new_tokens=available, use_cache=True,
                                         max_time=max(.01, deadline - time.monotonic()))
                generated = ids.shape[1] - inputs['input_ids'].shape[1]
                tokens_used += generated
                if generated >= available:
                    raise ValueError('VL recognition token budget reached; output may be truncated')
                text = normalize_vl_text(proc.batch_decode(ids[:, inputs['input_ids'].shape[1]:], skip_special_tokens=True)[0], label)
                crop.close()
            text_bytes += len(text.encode('utf-8'))
            if text_bytes > MAX_RESULT_BYTES:
                raise ValueError('VL text exceeds result bounds')
            if kind == 'table' and OTSL_TAG.search(text):
                validate_otsl_budget(text)
                otsl_indices.append(len(blocks))
            meta = {
                'vl_label': label,
                'layout_score': float(box.get('score', 0.0)),
                'layout_fallback': fallback,
                'layout_parser_version': PINS['paddleocr'],
                'pipeline_version': 'v1.6',
                'dtype': 'bfloat16',
                'reconstruction': 'PaddleOCR-VL-1.6 structured output; verify against original region',
            }
            if text_level is not None:
                meta['text_level'] = text_level
            if text or kind == 'figure':
                blocks.append({'bbox': norm, 'type': kind, 'text': text, 'metadata': meta})
        page_img.close()
    # Release the VLM before importing Paddle in the conversion helper.
    del model, proc, inputs, ids
    import gc
    gc.collect()
    if otsl_indices:
        raw_tables = [blocks[i]['text'] for i in otsl_indices]
        converted = run_paddle_stage('--otsl-to-html', raw_tables, Path(output_path).parent, deadline)
        if not isinstance(converted, list) or len(converted) != len(otsl_indices) or any(not isinstance(t, str) or not t.strip() for t in converted):
            raise ValueError('VL table converter returned invalid content')
        for idx, html_table in zip(otsl_indices, converted, strict=True):
            blocks[idx]['text'] = html_table
    return {'engine': 'paddleocr_vl', **info, 'device': 'cpu', 'backend': 'bfloat16-transformers',
            'width': width, 'height': height, 'blocks': blocks, 'elapsed_seconds': time.monotonic() - started}


if __name__ == '__main__':
    from services.parsing.offline import disable_network
    disable_network()
    if len(sys.argv) == 2 and sys.argv[1] == '--check-layout-v3':
        with contextlib.redirect_stdout(sys.stderr):
            result = check_layout_runtime()
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    elif len(sys.argv) == 3 and sys.argv[1] == '--layout-v3':
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
