"""Read-only acceptance report and safe screenshot/evidence helpers for the admin dashboard."""
from collections import Counter
import json
from pathlib import Path
import re
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
ALLOWED_ROOTS = (ROOT / 'evidence', ROOT / 'apps' / 'web' / 'validation')
ALLOWED_EXTENSIONS = {'.png', '.svg', '.json', '.log'}
MEDIA_TYPES = {
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.json': 'application/json; charset=utf-8',
    '.log': 'text/plain; charset=utf-8',
}

_MODULE_SPECS = [
    {
        'id': 'foundation',
        'title': '零 · 系统底座、轻量并发与安全合规',
        'case_ids': ['A01', 'A02', 'A03', 'A04', 'A05', 'A06', 'F01', 'F02', 'F03', 'F04', 'F05', 'F06', 'F07', 'F08', 'F09', 'F10', 'F11', 'F12', 'F13', 'F14', 'F15'],
        'tests': [
            {
                'name': '全量自动化回归与契约构建',
                'case_refs': ['A05', 'F01–F15'],
                'status': 'PASS',
                'summary': 'pytest 单测/集成、ruff 静态检查、TypeScript / Vite 前端构建与 OpenAPI 导出全部通过。',
                'api_steps': [
                    'FastAPI TestClient 覆盖 /api/v1/*',
                    'scripts/export_contract.py -> packages/contracts/openapi.json',
                ],
                'result_files': ['evidence/ubuntu24/regression.log', 'evidence/backend-check.log', 'evidence/frontend-build.log'],
                'screenshots': [
                    {'label': '文献库 1440px 主视图', 'path': 'apps/web/validation/ubuntu24-browser/library-1440.png'},
                    {'label': '文献库 1280px 适配视图', 'path': 'apps/web/validation/ubuntu24-browser/library-1280.png'},
                ],
            },
            {
                'name': '无密钥隔离冷启动闭环（no-key-live）',
                'case_refs': ['A01', 'A02', 'F11', 'F15'],
                'status': 'PASS',
                'summary': '清空模型密钥后独立拉起 API 与 Worker，完成登录、能力探测、PDF 上传解析、搜索与 CSV 绘图。',
                'api_steps': [
                    'GET /healthz',
                    'POST /api/v1/auth/login',
                    'GET /api/v1/capabilities',
                    'POST /api/v1/documents?index_dense=false',
                    'GET /api/v1/runs/{id}',
                    'GET /api/v1/documents/{vid}/file',
                    'GET /api/v1/documents/{vid}/search',
                    'GET /api/v1/documents/{vid}/pages/0',
                    'POST /api/v1/charts',
                ],
                'result_files': ['evidence/ubuntu24/no-key-live.json', 'evidence/ubuntu24/no-key-live.log'],
                'screenshots': [],
            },
            {
                'name': '3 评审工作区并发上传与跨空间隔离（lite-live）',
                'case_refs': ['F10', 'F14'],
                'status': 'PASS',
                'summary': '在 API 512M / Worker 896M 限制下 3 并发会话同时导入（含 541 页长文档），跨空间访问返回 404。',
                'api_steps': [
                    '3x POST /api/v1/auth/login',
                    '3x POST /api/v1/documents?index_dense=false',
                    'GET /api/v1/runs/{id}',
                    'GET /api/v1/documents/{other_vid}/file (断言 404)',
                    'GET /api/v1/documents/{vid}/status',
                    'GET /api/v1/documents/{vid}/search?q=RTMARK0541',
                ],
                'result_files': ['evidence/ubuntu24/lite-live.json', 'evidence/ubuntu24/lite-live.log'],
                'screenshots': [],
            },
        ],
    },
    {
        'id': 'parsing',
        'title': '一 · 文档解析、多引擎 OCR/MinerU 与快照保护',
        'case_ids': ['B01', 'B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B08', 'B09', 'B10', 'B11', 'B12', 'B13'],
        'tests': [
            {
                'name': 'MinerU 两页真实取消/恢复与旧快照保护（2026-11-16）',
                'case_refs': ['B08', 'B11', 'F09'],
                'status': 'PASS',
                'summary': '第一页保存后取消第二页；资源尚未释放时恢复返回409。释放后从checkpoint续跑至两页，第一页6个块与旧快照哈希不变，供应商账本未增加。',
                'api_steps': ['POST /api/v1/documents?index_dense=false', 'POST /api/v1/documents/{vid}/parses', 'POST /api/v1/runs/{rid}/cancel', 'POST /api/v1/runs/{rid}/resume (409 then200)', 'GET /api/v1/documents/{vid}/search?parse_id=...'],
                'result_files': ['evidence/ubuntu24/parser-recovery-20261116.json', 'evidence/ubuntu24/task-ownership-20261116.log'],
                'screenshots': [],
            },

            {
                'name': 'MinerU 4.2.2 CPU 架构/表格/公式解析 + 浏览器高亮',
                'case_refs': ['B02'],
                'status': 'PASS',
                'summary': 'equation.pdf（14.29s）、table.pdf（含HTML BLEU表/15.82s）、formula-page4.pdf（含LaTeX公式/23.73s）、scan-bilingual.pdf（9.20s）均通过并保留旧快照与账本不变。',
                'api_steps': [
                    'POST /api/v1/documents?index_dense=false',
                    'POST /api/v1/documents/{vid}/parses (engine=mineru, device=cpu)',
                    'UDS http://parser/parse (MinerU 4.2.2 CPU, effort=medium)',
                    'GET /api/v1/runs/{id}',
                    'GET /api/v1/documents/{vid}/blocks?limit=500',
                    'GET /api/v1/documents/{vid}/search',
                    'GET /api/v1/documents/{vid}/pages/{page_index}',
                ],
                'result_files': [
                    'evidence/ubuntu24/mineru-422-model-manifest.json',
                    'evidence/ubuntu24/mineru-cpu-equation.json',
                    'evidence/ubuntu24/mineru-cpu-table.json',
                    'evidence/ubuntu24/mineru-cpu-formula.json',
                    'evidence/ubuntu24/mineru-cpu-product.json',
                    'evidence/ubuntu24/mineru-graph-browser.json',
                ],
                'screenshots': [
                    {'label': 'MinerU 4.2.2 公式双语文本', 'path': 'evidence/ubuntu24/browser/mineru-formula-text.png'},
                    {'label': 'MinerU 4.2.2 公式 PDF 黄色高亮', 'path': 'evidence/ubuntu24/browser/mineru-formula-highlight.png'},
                    {'label': 'MinerU 4.2.2 表格文本重构', 'path': 'evidence/ubuntu24/browser/mineru-table-text.png'},
                    {'label': 'MinerU 4.2.2 表格 PDF 黄色高亮', 'path': 'evidence/ubuntu24/browser/mineru-table-highlight.png'},
                    {'label': 'MinerU 4.2.2 双语文本层', 'path': 'evidence/ubuntu24/browser/mineru-text-layer.png'},
                    {'label': 'MinerU 4.2.2 双语高亮定位', 'path': 'evidence/ubuntu24/browser/mineru-source-highlight.png'},
                ],
            },
            {
                'name': 'PaddleOCR-VL-1.6 CPU 文档大模型双语识别与高亮',
                'case_refs': ['B03(派生夹具)'],
                'status': 'PASS',
                'summary': '两阶段隔离（PP-DocLayoutV3 -> PyTorch bfloat16 PaddleOCR-VL-1.6-0.9B）离线 CPU 解析 scan-bilingual.pdf（132.67s），中英段落、表格、公式识别与 FTS 定位高亮全部通过；官方扫描原件暂缺故 B03 总项标 BLOCKED。',
                'api_steps': [
                    'POST /api/v1/documents?index_dense=false',
                    'POST /api/v1/documents/{vid}/parses (engine=paddleocr_vl, device=cpu)',
                    'UDS http://parser/readyz & parse (paddleocr_vl)',
                    'GET /api/v1/documents/{vid}/search?q=7189',
                    'GET /api/v1/documents/{vid}/pages/0',
                ],
                'result_files': [
                    'evidence/ubuntu24/paddle-vl-model-manifest.json',
                    'evidence/ubuntu24/paddleocr-vl-cpu-product.json',
                    'evidence/ubuntu24/browser/paddleocr_vl-reader.json',
                ],
                'screenshots': [
                    {'label': 'PaddleOCR-VL-1.6 双语文本层', 'path': 'evidence/ubuntu24/browser/paddleocr_vl-text-layer.png'},
                    {'label': 'PaddleOCR-VL-1.6 PDF 高亮定位', 'path': 'evidence/ubuntu24/browser/paddleocr_vl-source-highlight.png'},
                ],
            },
            {
                'name': 'PaddleOCR 3.7.0 CPU 双语识别与产品端到端高亮',
                'case_refs': ['B03(派生夹具)'],
                'status': 'PASS',
                'summary': '自编中英双语扫描页经 PaddleOCR CPU（8.69s）写入独立快照，中文 FTS 检索与 PDF bbox 高亮正常；官方扫描原件暂缺故 B03 总项标 BLOCKED。',
                'api_steps': [
                    'POST /api/v1/documents?index_dense=false',
                    'POST /api/v1/documents/{vid}/parses (engine=paddleocr, device=cpu)',
                    'UDS http://parser/readyz & parse',
                    'GET /api/v1/documents/{vid}/search?q=7189',
                    'GET /api/v1/documents/{vid}/pages/0',
                ],
                'result_files': ['evidence/ubuntu24/paddleocr-cpu-product.json', 'evidence/ubuntu24/browser/paddleocr-reader.json'],
                'screenshots': [
                    {'label': 'PaddleOCR 双语文本层', 'path': 'evidence/ubuntu24/browser/paddleocr-text-layer.png'},
                    {'label': 'PaddleOCR PDF 高亮定位', 'path': 'evidence/ubuntu24/browser/paddleocr-source-highlight.png'},
                ],
            },
            {
                'name': '不可变解析快照与 541 页断点中断恢复',
                'case_refs': ['B01', 'B04–B08', 'B10–B13'],
                'status': 'PASS',
                'summary': '重解析写入新 parse_id 并原子切换，127 个旧块 SHA256 完全不变；541 页在第 30 页强杀后恢复至末页可搜；损坏 PDF 返回 422。',
                'api_steps': [
                    'GET /api/v1/documents/{vid}/parses',
                    'POST /api/v1/documents/{vid}/parses',
                    'POST /api/v1/versions/compare',
                    'GET /api/v1/documents/{vid}/search?q=RTMARK0541',
                ],
                'result_files': ['evidence/ubuntu24/live-native-snapshots.json', 'evidence/ubuntu24/document-acceptance.json'],
                'screenshots': [],
            },
            {
                'name': 'MinerU GPU WSL2 显存保护（Fail-Closed 保守终止）',
                'case_refs': ['B02(GPU)'],
                'status': 'BLOCKED',
                'summary': '通过 /usr/lib/wsl/lib/nvidia-smi 选中 RTX 4060 Ti（余量 5921 MiB）；CUDA 启动后因 WSL2 NVML 进程显存恒为 [N/A]，监控仅终止本项目解析会话并返回 HTTP 503。',
                'api_steps': [
                    'POST /api/v1/documents/{vid}/parses (engine=mineru, device=gpu)',
                    'nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory',
                    'SIGTERM 项目解析会话 -> HTTP 503',
                ],
                'result_files': ['evidence/ubuntu24/mineru-gpu-product.json', 'evidence/ubuntu24/mineru-gpu-monitor.json'],
                'screenshots': [],
            },
        ],
    },
    {
        'id': 'qa',
        'title': '二 · 证据问答与混合检索',
        'case_ids': ['C01', 'C02', 'C03', 'C04', 'C05', 'C06', 'C07', 'C08', 'C09', 'C10'],
        'tests': [
            {
                'name': '浏览器点击真实模型引文并定位第 7 页（含旋转与缩放）',
                'case_refs': ['C03', 'D06'],
                'status': 'PASS',
                'summary': '打开已保存的 Hydrogen QA 结果点击 evidence chip，精准跳至 Transformer v7 第 7 页，旋转 90° 与缩放 110% 后高亮框坐标同步更新。',
                'api_steps': [
                    'GET /api/v1/runs?summary=true',
                    'GET /api/v1/runs/{id}',
                    'GET /api/v1/documents/{vid}/file',
                    'GET /api/v1/documents/{vid}/pages/6',
                ],
                'result_files': ['evidence/ubuntu24/browser/acceptance.json', 'evidence/live_qa_result.json'],
                'screenshots': [
                    {'label': 'QA 引文第 7 页高亮 (1440px)', 'path': 'evidence/ubuntu24/browser/citation-1440.png'},
                    {'label': '旋转 90° + 缩放 110% 高亮联动', 'path': 'evidence/ubuntu24/browser/citation-rotated-zoomed.png'},
                    {'label': '阅读器 1280px 视口', 'path': 'evidence/ubuntu24/browser/reader-1280.png'},
                ],
            },
            {
                'name': '历史 Hydrogen 真实问答 & Sparse/Dense/RRF 消融记录',
                'case_refs': ['C01', 'C02', 'C05', 'C06', 'C08', 'C09'],
                'status': 'BLOCKED',
                'summary': '迁移前已完成 Hydrogen 真实核心问答（带逐字引用与下标分离诚实说明）及 768 维 Dense/RRF 消融；Ubuntu 24 因 4 次 Hydrogen 冒烟预算已满不再重复扣费调用。',
                'api_steps': [
                    'POST /api/v1/qa/runs (历史 Hydrogen 实调)',
                    'GET /api/v1/runs/{id}/events (SSE)',
                    'services/api/retrieval.py (RRF)',
                ],
                'result_files': ['evidence/live_qa_result.json', 'evidence/live_unseen_qa_result.json', 'evidence/retrieval_ablation.json'],
                'screenshots': [],
            },
        ],
    },
    {
        'id': 'reader',
        'title': '三 · 双栏沉浸式阅读、对照翻译与 UI 异常矩阵',
        'case_ids': ['D01', 'D02', 'D03', 'D04', 'D05', 'D06', 'D07'],
        'tests': [
            {
                'name': '正文引用编号跳转参考文献并返回 + 快照选择',
                'case_refs': ['D01', 'D02'],
                'status': 'PASS',
                'summary': '点击正文引用编号 [12] 精准定位第 10 页参考文献条目，点击返回准确回到源块；切换解析快照同步作用域。',
                'api_steps': [
                    'GET /api/v1/documents/{vid}/parses',
                    'GET /api/v1/documents/{vid}/blocks?parse_id=...',
                    'GET /api/v1/documents/{vid}/references?parse_id=...',
                ],
                'result_files': ['apps/web/validation/reader-extra-20261115T143101401610Z.json', 'evidence/ubuntu24/reader-snapshots-browser.json'],
                'screenshots': [
                    {'label': 'D02 跳转第 10 页参考文献', 'path': 'apps/web/validation/reader-extra-20261115T143101401610Z-d02-bibliography.png'},
                    {'label': 'D02 返回源文精确位置', 'path': 'apps/web/validation/reader-extra-20261115T143101401610Z-d02-return.png'},
                ],
            },
            {
                'name': '双语段落逐块对齐与双向同步滚动',
                'case_refs': ['D03', 'D04(历史)'],
                'status': 'PASS',
                'summary': '基于已入库 BitNet 120/120 非空译文块在 Chromium 验证中英双栏滚动对齐与零抖动；新发起全量翻译受预算约束标 BLOCKED。',
                'api_steps': [
                    'GET /api/v1/translations/{vid}',
                    'GET /api/v1/documents/{vid}/blocks?parse_id=...',
                ],
                'result_files': ['apps/web/validation/reader-extra-20261115T143101401610Z.json', 'evidence/live_translation_result.json'],
                'screenshots': [
                    {'label': 'D03 双语段落对齐与同步滚动', 'path': 'apps/web/validation/reader-extra-20261115T143101401610Z-d03-aligned-scroll.png'},
                ],
            },
            {
                'name': '可见 UI 状态全矩阵（Loading/Partial/401/429/500/Empty/Parse-Failed）',
                'case_refs': ['D05'],
                'status': 'PASS',
                'summary': '9 项浏览器状态全部可见且无控制台报错，涵盖未登录 401、限流 429、服务端 500、加载恢复、空态与解析失败提示。',
                'api_steps': [
                    'GET /api/v1/auth/session (真实 401)',
                    '路由拦截验证 GET /api/v1/documents* & /api/v1/runs* (429 / 500 / partial / parse-failed)',
                ],
                'result_files': ['apps/web/validation/reader-extra-20261115T143101401610Z.json'],
                'screenshots': [
                    {'label': 'D05 Loading 加载态', 'path': 'apps/web/validation/reader-extra-20261115T143101401610Z-d05-loading-fixture.png'},
                    {'label': 'D05 Partial 部分结果', 'path': 'apps/web/validation/reader-extra-20261115T143101401610Z-d05-partial-fixture.png'},
                    {'label': 'D05 401 未登录拦截', 'path': 'apps/web/validation/reader-extra-20261115T143101401610Z-d05-noauth-live.png'},
                    {'label': 'D05 429 限流提示', 'path': 'apps/web/validation/reader-extra-20261115T143101401610Z-d05-429-fixture.png'},
                    {'label': 'D05 500 错误横幅', 'path': 'apps/web/validation/reader-extra-20261115T143101401610Z-d05-error-fixture.png'},
                    {'label': 'D05 Parse Failed 解析失败', 'path': 'apps/web/validation/reader-extra-20261115T143101401610Z-d05-parse-failed-fixture.png'},
                    {'label': 'D05 Empty 空态', 'path': 'apps/web/validation/reader-extra-20261115T143101401610Z-d05-empty-fixture.png'},
                ],
            },
        ],
    },
    {
        'id': 'search',
        'title': '四 · 学术检索、追踪与反馈推荐',
        'case_ids': ['E01', 'E02', 'E03', 'E04'],
        'tests': [
            {
                'name': '检索面板视口检查、外部失败降级与反馈调权单测',
                'case_refs': ['E02', 'E04'],
                'status': 'PASS',
                'summary': '追踪并发去重、崩溃恢复、取消与禁用保护已通过测试。2026-11-16 已尝试真实 HTTP 检查，但 arXiv/Crossref DNS 返回198.18.*非公网地址，被 SSRF 防护阻断；E01/E03 仍为 BLOCKED，未用历史结果替代。',
                'api_steps': [
                    'POST /api/v1/search',
                    'POST /api/v1/search/import',
                    'POST /api/v1/feedback',
                    'POST /api/v1/watch-queries & /{id}/check',
                ],
                'result_files': ['apps/web/validation/ubuntu24-browser/browser-check.json', 'evidence/live_watch.json', 'evidence/ubuntu24/discovery-20261116-verification.json', 'evidence/ubuntu24/discovery-20261116-20261115T164258011472Z/result.json', 'evidence/ubuntu24/discovery-20261116-tests.log'],
                'screenshots': [],
            },
        ],
    },
    {
        'id': 'graph_audit',
        'title': '五 · 20 篇级真实引用图谱与 Idea 后续核查',
        'case_ids': ['E05', 'E06', 'E07'],
        'tests': [
            {
                'name': '29 节点 / 72 边真实引用图谱重建与浏览器交互',
                'case_refs': ['E05', 'E06'],
                'status': 'PASS',
                'summary': '在浏览器点击“重建与重算”实时调用图谱构建，29 节点 PageRank 重算、节点详情检视与 1440/1280 视口检查全部通过。',
                'api_steps': [
                    'POST /api/v1/graphs (实际 200 OK 返回 29 nodes, 72 edges)',
                ],
                'result_files': ['evidence/ubuntu24/live-graph.json', 'evidence/ubuntu24/mineru-graph-browser.json'],
                'screenshots': [
                    {'label': '29 节点引用图谱浏览器交互 (1440px)', 'path': 'evidence/ubuntu24/browser/graph-20-nodes-1440.png'},
                ],
            },
            {
                'name': 'Transformer Future Work vs Longformer 后续核查（历史真实 Hydrogen）',
                'case_refs': ['E07'],
                'status': 'BLOCKED',
                'summary': '已保存历史真实核查：区分长文本部分覆盖与非文本模态/非自回归证据不足；新机器复跑因 Hydrogen 4 次预算耗尽标 BLOCKED。',
                'api_steps': [
                    'POST /api/v1/ideas/audits (历史 Hydrogen 实调)',
                ],
                'result_files': ['evidence/live_idea_result.json'],
                'screenshots': [],
            },
        ],
    },
    {
        'id': 'writing_charts',
        'title': '六 · 源约束写作导出、安全 Mermaid 结构图与数值绘图',
        'case_ids': ['E08', 'E09', 'E10', 'E11', 'E12', 'E13'],
        'tests': [
            {
                'name': '已保存研究笔记多格式导出（md / html / bib）',
                'case_refs': ['E08(确定性导出)'],
                'status': 'PASS',
                'summary': '在浏览器验证已验证研究笔记导出 Markdown（1624 B）、HTML（1848 B）、BibTeX（180 B），0 模型调用；新建写作生成因配额标 BLOCKED。',
                'api_steps': [
                    'GET /api/v1/artifacts',
                    'GET /api/v1/artifacts/{id}/export?format=md|html|bib',
                ],
                'result_files': ['evidence/ubuntu24/mineru-graph-browser.json'],
                'screenshots': [],
            },
            {
                'name': '可编辑 Mermaid 结构图 + 恶意脚本拦截 + SVG 导出',
                'case_refs': ['E09'],
                'status': 'PASS',
                'summary': '本地修改 Mermaid 源码实时重绘、导出 SVG，并验证拦截 click javascript:alert(1) 等 XSS 指令。',
                'api_steps': [
                    '本地 @mermaid-js/mermaid + DOMPurify 安全校验与 SVG 导出',
                ],
                'result_files': ['evidence/ubuntu24/browser/acceptance.json', 'apps/web/validation/ubuntu24-browser/browser-check.json'],
                'screenshots': [
                    {'label': '结构图编辑器 (1440px)', 'path': 'apps/web/validation/ubuntu24-browser/diagram-1440.png'},
                    {'label': '导出的安全 SVG 产物', 'path': 'evidence/ubuntu24/browser/edited-diagram.svg'},
                ],
            },
            {
                'name': 'CSV 真实数值统计计算、绘图与可复现脚本导出',
                'case_refs': ['E10', 'E11', 'E12'],
                'status': 'PASS',
                'summary': '上传 metrics_a.csv 后由服务端实际计算样本数 n=4、最大值 0.81 与差值 0.17，返回 PNG/SVG/Python 复现脚本/PlotSpec/原 CSV，不写未检验的“显著”。',
                'api_steps': [
                    'POST /api/v1/charts (multipart file + spec JSON)',
                    'GET /api/v1/artifacts/{id}/files/{png|svg|script|spec|csv}',
                ],
                'result_files': ['evidence/ubuntu24/browser/acceptance.json'],
                'screenshots': [
                    {'label': 'CSV 数据绘图与统计结果 (1280px)', 'path': 'evidence/ubuntu24/browser/csv-chart-1280.png'},
                ],
            },
        ],
    },
]


def resolve_evidence_file(rel_path: str) -> Path | None:
    """Resolve an evidence file path strictly within allowlisted evidence/validation dirs."""
    if not rel_path or Path(rel_path).is_absolute():
        return None
    candidate = (ROOT / rel_path).resolve()
    if not candidate.is_file():
        return None
    if candidate.suffix.lower() not in ALLOWED_EXTENSIONS:
        return None
    if not candidate.is_relative_to(ROOT.resolve()):
        return None
    if 'private' in candidate.relative_to(ROOT.resolve()).parts:
        return None
    for base in ALLOWED_ROOTS:
        resolved_base = base.resolve()
        if resolved_base in candidate.parents:
            return candidate
    return None


def _evidence_url(rel_path: str) -> str:
    return f'/api/v1/admin/evidence-file?path={quote(rel_path, safe="/")}'


def _parse_regression_summary() -> str:
    log = ROOT / 'evidence/ubuntu24/regression.log'
    if not log.is_file():
        return '尚未记录回归日志'
    text = log.read_text(encoding='utf-8', errors='replace')
    match = re.findall(r'(\d+\s+passed[^\n]*)', text)
    return match[-1].strip() if match else '已执行（详见 regression.log）'


def _load_cases() -> list[dict]:
    path = ROOT / 'evidence/ubuntu24/acceptance.json'
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def build_acceptance_report() -> dict:
    """Assemble live-verified acceptance status, per-module API chains, logs, and screenshots."""
    cases = _load_cases()
    counts = Counter(str(item.get('status') or 'NOT RUN') for item in cases)
    modules = []
    for spec in _MODULE_SPECS:
        tests_out = []
        for test in spec['tests']:
            result_files = [
                {'path': p, 'url': _evidence_url(p)}
                for p in test['result_files']
                if resolve_evidence_file(p) is not None
            ]
            screenshots = [
                {'label': s['label'], 'path': s['path'], 'url': _evidence_url(s['path'])}
                for s in test['screenshots']
                if resolve_evidence_file(s['path']) is not None
            ]
            tests_out.append({
                'name': test['name'],
                'case_refs': test['case_refs'],
                'status': test['status'],
                'summary': test['summary'],
                'api_steps': test['api_steps'],
                'result_files': result_files,
                'screenshots': screenshots,
            })
        case_statuses = [c.get('status') for c in cases if c.get('case_id') in spec['case_ids']]
        modules.append({
            'id': spec['id'],
            'title': spec['title'],
            'case_ids': spec['case_ids'],
            'pass_count': sum(1 for s in case_statuses if s == 'PASS'),
            'blocked_count': sum(1 for s in case_statuses if s == 'BLOCKED'),
            'total_count': len(case_statuses),
            'tests': tests_out,
        })
    cases_out = []
    for item in cases:
        ev_files = [
            {'path': p, 'url': _evidence_url(p)}
            for p in (item.get('evidence_paths') or [])
            if isinstance(p, str) and resolve_evidence_file(p) is not None
        ]
        cases_out.append({
            'case_id': item.get('case_id'),
            'title': item.get('title'),
            'status': item.get('status'),
            'observed': item.get('observed'),
            'command_or_browser_steps': item.get('command_or_browser_steps'),
            'remaining_risk': item.get('remaining_risk'),
            'new_provider_calls': (item.get('api_calls_and_usage') or {}).get('new_provider_calls', 0),
            'evidence_files': ev_files,
            'evidence_paths': item.get('evidence_paths') or [],
        })
    return {
        'environment': 'Ubuntu 24.04.5 WSL2 · http://127.0.0.1:18980',
        'pytest_summary': _parse_regression_summary(),
        'summary': {
            'total': len(cases),
            'pass': counts.get('PASS', 0),
            'blocked': counts.get('BLOCKED', 0),
            'not_run': counts.get('NOT RUN', 0),
            'fail': counts.get('FAIL', 0),
        },
        'modules': modules,
        'cases': cases_out,
    }
