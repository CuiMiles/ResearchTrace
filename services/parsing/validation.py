"""Bound files and geometry before any inference; never accept input URLs."""
import math
from pathlib import Path
import warnings

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_SIDE = 8192
MAX_RESULT_BYTES = 16 * 1024 * 1024
MAX_BLOCKS = 20000


def validate_result(result, engine, version, device):
    if (not isinstance(result, dict) or result.get('engine') != engine
            or result.get('version') != version or result.get('device') != device):
        raise ValueError('Parser provenance missing or inconsistent')
    entries = result.get('lines' if engine == 'paddleocr' else 'blocks')
    if not isinstance(entries, list) or len(entries) > MAX_BLOCKS:
        raise ValueError('Parser output exceeds block bounds or is invalid')
    size = result.get('page_info') if engine == 'mineru' else [result.get('width'), result.get('height')]
    if (not isinstance(size, (list, tuple)) or len(size) != 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in size)):
        raise ValueError('Parser page geometry invalid')
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('text'), str):
            raise ValueError('Parser output text invalid')
        box = entry.get('bbox')
        if normalized_box(box) != box:
            raise ValueError('Parser output geometry outside page')
        if engine == 'paddleocr':
            score = entry.get('confidence')
            if (isinstance(score, bool) or not isinstance(score, (int, float))
                    or not math.isfinite(score) or not 0 <= score <= 1):
                raise ValueError('Parser output confidence invalid')
        elif (entry.get('type') not in ('paragraph', 'heading', 'equation', 'table', 'figure')
                or not isinstance(entry.get('metadata'), dict)):
            raise ValueError('Parser output block schema invalid')


def validate_input(engine, path):
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError('Input must be a bounded local file (20 MiB maximum)')
    with path.open('rb') as stream:
        signature = stream.read(8)
    if engine in ('paddleocr', 'paddleocr_vl'):
        if signature != b'\x89PNG\r\n\x1a\n':
            raise ValueError(f'{engine} expects a single PNG page')
        from PIL import Image
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            try:
                with Image.open(path) as image:
                    width, height = image.size
                    if (image.format != 'PNG' or getattr(image, 'n_frames', 1) != 1
                            or min(width, height) <= 0 or max(width, height) > MAX_SIDE
                            or width * height > MAX_PIXELS):
                        raise ValueError('Image exceeds single-page pixel bounds')
                    image.verify()
            except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
                raise ValueError('Invalid or oversized PNG') from exc
        return [width, height]
    if engine != 'mineru' or not signature.startswith(b'%PDF-'):
        raise ValueError('MinerU expects a single PDF page')
    import pypdfium2 as pdfium
    try:
        with pdfium.PdfDocument(str(path)) as doc:
            if len(doc) != 1:
                raise ValueError('MinerU input must contain exactly one page')
            page = doc[0]
            try:
                size = page.get_size()
                if (any(not math.isfinite(x) or not 0 < x <= MAX_SIDE * 72 / 200 for x in size)
                        or size[0] * size[1] * (200 / 72) ** 2 > MAX_PIXELS):
                    raise ValueError('PDF page dimensions exceed bounds')
                return list(size)
            finally:
                page.close()
    except pdfium.PdfiumError as exc:
        raise ValueError('Invalid or encrypted PDF') from exc


def normalized_box(box, xscale=1, yscale=1):
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise ValueError('Missing source geometry')
    try:
        if any(isinstance(x, bool) for x in (*box, xscale, yscale)):
            raise ValueError
        scales = [float(xscale), float(yscale)]
        if any(not math.isfinite(s) or s <= 0 for s in scales):
            raise ValueError
        values = [float(x) / scale for x, scale in zip(box, scales * 2, strict=True)]
    except (ValueError, TypeError, OverflowError):
        raise ValueError('Invalid source geometry') from None
    if any(not math.isfinite(x) for x in values) or values[0] >= values[2] or values[1] >= values[3]:
        raise ValueError('Invalid source geometry')
    clipped = [max(0.0, min(1.0, x)) for x in values]
    if clipped[0] >= clipped[2] or clipped[1] >= clipped[3]:
        raise ValueError('Source geometry does not intersect page')
    return clipped
