"""CSV -> validated PlotSpec -> fixed plotting template, without model code execution."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import store

FONT_CACHE = store.DATA / 'cache' / 'matplotlib'


class PlotSpec(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['line', 'bar', 'radar', '3d'] = 'line'
    x: str | None = Field(None, max_length=200)
    y: list[str] | None = Field(None, max_length=8)
    z: str | None = Field(None, max_length=200)
    title: str = Field('实验数据', max_length=200)
    x_unit: str = Field('', max_length=50)
    y_unit: str = Field('', max_length=50)
    aggregate: Literal['none', 'mean', 'sum'] = 'none'


# This fixed source is exported verbatim. User strings are JSON data, never code.
PLOT_SCRIPT = '''#!/usr/bin/env python3
"""Reproduce: python plot.py input.csv spec.json [output-directory]
Requires matplotlib; no application, keys or network access needed.
"""
import csv, hashlib, io, json, math, os, sys
from pathlib import Path
if os.environ.get("RT_PLOT_LIMITS") == "1":
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (30, 35))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

plt.rcParams["text.usetex"] = False
plt.rcParams["mathtext.default"] = "regular"
plt.rcParams["axes.formatter.use_mathtext"] = False
# Chinese titles and labels need a CJK-capable fallback. The container image ships
# Droid Sans Fallback; other hosts usually have Noto Sans CJK or WenQuanYi instead.
for font in map(Path, (
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
)):
    if font.exists():
        font_manager.fontManager.addfont(str(font))
        plt.rcParams["font.family"] = ["DejaVu Sans", font_manager.FontProperties(fname=str(font)).get_name()]
        break
plt.rcParams["axes.unicode_minus"] = False
csv_path = Path(sys.argv[1])
spec_path = Path(sys.argv[2])
out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(".")
out.mkdir(exist_ok=True, parents=True)
spec = json.loads(spec_path.read_text(encoding="utf-8"))
raw = csv_path.read_bytes()
if hashlib.sha256(raw).hexdigest() != spec["input_sha256"]:
    raise ValueError("CSV hash differs from exported PlotSpec")
rows = list(csv.DictReader(io.StringIO(raw.decode(spec["encoding"]))))
kind, xkey, ykeys = spec["kind"], spec["x"], spec["y"]
def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else float("nan")
    except (ValueError, TypeError):
        return float("nan")
if spec["aggregate"] != "none":
    grouped = {}
    for row in rows:
        grouped.setdefault(row[xkey], []).append(row)
    transformed = []
    for label, group in grouped.items():
        new = {xkey: label}
        for y in ykeys:
            values = [number(r[y]) for r in group if math.isfinite(number(r[y]))]
            new[y] = (sum(values) / len(values) if spec["aggregate"] == "mean" else sum(values)) if values else float("nan")
        transformed.append(new)
    rows = transformed
labels = [r[xkey] for r in rows]
colors = ["#087F8C", "#315EBD", "#AD6B12", "#8051A5", "#B45165", "#397D54", "#657489", "#AF4F26"]
fig = plt.figure(figsize=(9.4, 5.8))
fig.subplots_adjust(left=.12, right=.76, bottom=.22, top=.84)
fig.patch.set_facecolor("white")
if kind == "3d":
    ax = fig.add_subplot(111, projection="3d")
    ax.scatter([number(r[xkey]) for r in rows], [number(r[ykeys[0]]) for r in rows], [number(r[spec["z"]]) for r in rows], color=colors[0], s=40)
    ax.set_xlabel(xkey + (" / " + spec["x_unit"] if spec["x_unit"] else ""))
    ax.set_ylabel(ykeys[0] + (" / " + spec["y_unit"] if spec["y_unit"] else ""))
    ax.set_zlabel(spec["z"])
elif kind == "radar":
    ax = fig.add_subplot(111, projection="polar")
    angles = [2 * math.pi * i / len(ykeys) for i in range(len(ykeys))]
    scales = [max(abs(number(r[k])) for r in rows) or 1 for k in ykeys]
    for index, row in enumerate(rows):
        vals = [number(row[k]) / scale for k, scale in zip(ykeys, scales)]
        ax.plot(angles + angles[:1], vals + vals[:1], color=colors[index % len(colors)], label=str(row[xkey]))
        ax.fill(angles + angles[:1], vals + vals[:1], color=colors[index % len(colors)], alpha=.05)
    ax.set_xticks(angles, ykeys)
    ax.set_ylim(-1 if any(number(r[k]) < 0 for r in rows for k in ykeys) else 0, 1)
    ax.legend(loc="upper left", bbox_to_anchor=(1.12, 1), frameon=False)
else:
    ax = fig.add_subplot(111)
    numeric_axis = kind == "line" and all(math.isfinite(number(r[xkey])) for r in rows)
    xpos = [number(r[xkey]) for r in rows] if numeric_axis else list(range(len(rows)))
    for index, key in enumerate(ykeys):
        values = [number(r[key]) for r in rows]
        if kind == "bar":
            width = .8 / len(ykeys)
            ax.bar([x + (index - (len(ykeys)-1)/2) * width for x in xpos], values, width=width, color=colors[index], label=key)
        else:
            ax.plot(xpos, values, marker="o" if len(rows) < 50 else None, markersize=4, linewidth=1.8, color=colors[index], label=key)
    step = max(1, math.ceil(len(rows) / 18))
    ax.set_xticks(xpos[::step], labels[::step], rotation=30 if len(rows) > 6 else 0, ha="right" if len(rows) > 6 else "center")
    ax.set_xlabel(xkey + (" / " + spec["x_unit"] if spec["x_unit"] else ""))
    ax.set_ylabel(spec["y_unit"] or "value")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=.18)
    ax.set_axisbelow(True)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), frameon=False)
ax.set_title(spec["title"], loc="left", pad=20, fontsize=15)
fig.savefig(out / "chart.png", dpi=160, facecolor="white", bbox_inches="tight")
fig.savefig(out / "chart.svg", facecolor="white", bbox_inches="tight")
plt.close(fig)
# Both savefig calls have closed their output handles. Validate completed files
# before process success; let the OS reclaim this one-shot process directly
# instead of spending its bounded CPU budget on CPython/C-extension finalizers.
if not (out / "chart.png").read_bytes().startswith(bytes([137, 80, 78, 71, 13, 10, 26, 10])):
    raise ValueError("PNG output missing or invalid")
if "<svg" not in (out / "chart.svg").read_text(encoding="utf-8"):
    raise ValueError("SVG output missing or invalid")
os._exit(0)
'''


def _decode(content: bytes):
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            text = content.decode(encoding)
            if '\x00' in text:
                raise ValueError('CSV 含 NUL 字符，不是受支持文本')
            return text, encoding
        except UnicodeDecodeError:
            continue
    raise ValueError('CSV 编码无法识别；请使用 UTF-8 或 GB18030')


def _num(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def create_chart(workspace: str, filename: str, content: bytes, spec: dict) -> dict:
    if not content or len(content) > 5 * 1024 * 1024:
        raise ValueError('CSV 必须为 1 字节到 5 MiB')
    if '/' in filename or '\\' in filename or '\x00' in filename:
        raise ValueError('不安全文件名')
    if not filename.lower().endswith('.csv'):
        raise ValueError('仅允许 .csv 文件')
    spec_obj = PlotSpec.model_validate(spec)
    text, encoding = _decode(content)
    csv.field_size_limit(100000)
    try:
        reader = csv.DictReader(io.StringIO(text), strict=True)
        columns = reader.fieldnames
        if not columns or len(columns) > 64 or any(not x or len(x) > 200 for x in columns) or len(set(columns)) != len(columns):
            raise ValueError('CSV 列名为空、重复、过长或列数超过 64')
        records = []
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f'第 {len(records) + 2} 行列数与表头不一致')
            records.append(row)
            if len(records) > 20000:
                raise ValueError('单图最多 20000 行；请先按需聚合')
    except csv.Error as exc:
        raise ValueError('CSV 引号或结构无效') from exc
    if not records:
        raise ValueError('CSV 没有数据行')
    details, stats = [], {}
    for column in columns:
        values = [(_num(row[column]), i + 2) for i, row in enumerate(records)]
        valid = [(v, i) for v, i in values if v is not None]
        missing = [i + 2 for i, row in enumerate(records) if not row[column].strip()]
        invalid = [i + 2 for i, row in enumerate(records) if row[column].strip() and _num(row[column]) is None]
        numeric = bool(valid) and len(valid) >= len(records) / 2
        details.append({'name': column, 'type': 'number' if numeric else 'text', 'numeric_count': len(valid), 'missing_rows': missing[:50], 'invalid_numeric_rows': invalid[:50] if numeric else [], 'diagnostics_truncated': len(missing) > 50 or (numeric and len(invalid) > 50)})
        if valid:
            numbers = [v for v, _ in valid]
            stats[column] = {'count': len(numbers), 'min': min(numbers), 'max': max(numbers), 'mean': sum(numbers) / len(numbers), 'sum': sum(numbers), 'first': numbers[0], 'last': numbers[-1], 'delta': numbers[-1] - numbers[0], 'max_row': next(i for v, i in valid if v == max(numbers)), 'missing_count': len(missing), 'invalid_count': len(invalid)}
    numeric_columns = [x['name'] for x in details if x['type'] == 'number']
    xkey = spec_obj.x or columns[0]
    ykeys = spec_obj.y or [x for x in numeric_columns if x != xkey][:3]
    if xkey not in columns or not ykeys or any(y not in columns for y in ykeys) or len(set(ykeys)) != len(ykeys) or xkey in ykeys:
        raise ValueError('请选择存在且不重复的 x/y 列；y 至少包含一个数值列且不能与 x 相同')
    if any(y not in numeric_columns for y in ykeys):
        raise ValueError('y 必须是数值列；当前数据无法可靠判断为数值')
    if spec_obj.kind == 'bar' and len(records) > 100 and spec_obj.aggregate == 'none':
        raise ValueError('柱状图原始行数超过 100，请选择按 x 均值/求和聚合')
    warnings = []
    if spec_obj.kind == 'line' and not all(_num(r[xkey]) is not None for r in records):
        warnings.append('横轴含非数值，采用分类轴，保留原始行顺序；不能据此比较非等距数值间隔')
    for y in ykeys:
        if stats[y]['missing_count'] or stats[y]['invalid_count']:
            warnings.append(f'{y}：{stats[y]["missing_count"]} 个空值、{stats[y]["invalid_count"]} 个非有限/非数值；原始 CSV 保留，绘图显示缺口，统计只使用明确数值')
    if any(not row[xkey].strip() for row in records):
        warnings.append('x 列有空值，保留空标签；未删除对应记录')
    if spec_obj.aggregate != 'none':
        warnings.append(f'图采用按 x 的 {spec_obj.aggregate} 聚合；下方统计为原始数值，PlotSpec 明确记录聚合方式')
    if spec_obj.kind == 'radar':
        if len(ykeys) < 3 or len(records) > 12 or any(stats[y]['missing_count'] or stats[y]['invalid_count'] for y in ykeys):
            raise ValueError('雷达图要求至少 3 个完整数值指标、最多 12 组；缺失值请先处理')
        warnings.append('雷达图每个指标按当前数据最大绝对值归一化；原始数值见统计，不能据此推导显著性')
    if spec_obj.kind == '3d':
        if len(ykeys) != 1 or xkey not in numeric_columns or spec_obj.z not in numeric_columns or spec_obj.z in (xkey, ykeys[0]) or spec_obj.aggregate != 'none':
            raise ValueError('三维图需要三个不同数值列 x、一个 y 和 z，不支持聚合；分类/二维数据请使用折线或柱状图')
        if any(_num(r[k]) is None for r in records for k in (xkey, ykeys[0], spec_obj.z)):
            raise ValueError('三维图数据有空值/无效数值；请先处理后绘制')
    resolved = spec_obj.model_dump()
    resolved.update({'x': xkey, 'y': ykeys, 'encoding': encoding, 'input_sha256': hashlib.sha256(content).hexdigest(), 'row_count': len(records), 'plot_template_version': 2, 'plot_script_sha256': hashlib.sha256(PLOT_SCRIPT.encode()).hexdigest(), 'x_scale': 'numeric' if spec_obj.kind == 'line' and all(_num(r[xkey]) is not None for r in records) else 'categorical'})
    caption = f'{resolved["title"]}：输入 {len(records)} 行，图型 {resolved["kind"]}。' + '；'.join(f'{y} 有效 n={stats[y]["count"]}，最大值 {stats[y]["max"]:g}{(" " + spec_obj.y_unit) if spec_obj.y_unit else ""}（CSV 第 {stats[y]["max_row"]} 行），末个与首个有效值之差 {stats[y]["delta"]:g}' for y in ykeys) + '。统计来自程序计算，未进行统计显著性或因果检验。'
    aid = store.uid()
    directory = store.DATA / 'charts' / aid
    directory.mkdir(parents=True, mode=0o700)
    try:
        (directory / 'input.csv').write_bytes(content)
        (directory / 'spec.json').write_text(json.dumps(resolved, ensure_ascii=False, indent=2), encoding='utf-8')
        (directory / 'plot.py').write_text(PLOT_SCRIPT, encoding='utf-8')
        FONT_CACHE.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'MPLCONFIGDIR': str(FONT_CACHE), 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'PYTHONNOUSERSITE': '1', 'RT_PLOT_LIMITS': '1'}
        completed = subprocess.run([sys.executable, '-I', str(directory / 'plot.py'), str(directory / 'input.csv'), str(directory / 'spec.json'), str(directory)], cwd=directory, env=env, timeout=40, capture_output=True, text=True, check=False)
        if completed.returncode:
            # No upstream secrets passed into child environment or source. Keep diagnostics in artifact dir.
            (directory / 'render-error.txt').write_text(f'returncode={completed.returncode}\n' + completed.stderr[-12000:])
            raise ValueError('绘图进程失败；未生成完成产物（输入保留供检查）')
        files = {key: f'/api/v1/artifacts/{aid}/files/{name}' for key, name in {'png': 'chart.png', 'svg': 'chart.svg', 'script': 'plot.py', 'spec': 'spec.json', 'csv': 'input.csv'}.items()}
        result = {'artifact_id': aid, 'columns': columns, 'column_details': details, 'statistics': stats, 'warnings': warnings, 'caption': caption, 'files': files, 'spec': resolved, 'input_sha256': resolved['input_sha256'], 'encoding': encoding, 'row_count': len(records)}
        store.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)', (aid, workspace, None, 'chart', spec_obj.title, json.dumps(result, ensure_ascii=False), time.time()))
        return result
    except subprocess.TimeoutExpired as exc:
        raise ValueError('绘图超时，已终止子进程') from exc


def artifact_file(workspace: str, artifact_id: str, name: str) -> Path:
    if name not in {'chart.png', 'chart.svg', 'plot.py', 'spec.json', 'input.csv'}:
        raise ValueError('不支持的产物文件')
    row = store.one('SELECT * FROM artifacts WHERE id=? AND workspace=? AND kind=?', (artifact_id, workspace, 'chart'))
    if not row:
        raise ValueError('图表不存在或无权限')
    path = store.DATA / 'charts' / artifact_id / name
    if not path.is_file():
        raise ValueError('图表文件缺失')
    return path
