"""Admin-only processing map backed by durable, real dataset test records."""
import json
from datetime import datetime, timezone

from .acceptance_report import _evidence_url, resolve_evidence_file
from .store import ROOT

REPORT_PATH = ROOT / 'evidence/competition-dataset/workflow.json'
STATUSES = {'PASS', 'FAIL', 'BLOCKED', 'NOT RUN'}

STEPS = [
    ('inventory', '解压与核对输入', '先确定输入是什么，保留原包与文件指纹。', '用户提供的科研小助手.rar',
     ['保留原包；检查目录穿越、链接、加密和体积', '隔离解压；登记每个文件的 SHA256、大小与页数'],
     ['完整文件清单', '来源说明、哈希和解压日志'], [], []),
    ('upload', '上传与版本识别', '在文档库上传 PDF，系统按内容和字节识别论文及版本。', '清单中的原始 PDF；测试时改名上传',
     ['验证 PDF 格式与权限，关闭批量测试的付费密集索引', '计算字节指纹；相同字节去重；同论文不同版本关联'],
     ['不可变文档版本 ID', '持久化解析任务 ID'], ['POST /api/v1/documents?index_dense=false', 'GET /api/v1/documents'], ['inventory']),
    ('parse', '逐页解析与 OCR', '有文字层先原生提取，扫描页 OCR；需要结构时选择新解析快照。', '已上传的指定 PDF 版本',
     ['原生解析逐页持久化；缺文字页使用 Tesseract', 'PaddleOCR 识字、MinerU 表格公式、PaddleOCR-VL 布局识别分别真实执行', 'CPU 可运行；GPU 按实时显存与进程预算保护'],
     ['文字、表格、公式、阅读顺序', '页码、bbox、质量和实际模型/设备来源'], ['GET /api/v1/documents/{vid}/status', 'POST /api/v1/documents/{vid}/parses'], ['upload']),
    ('snapshots', '快照保护与索引', '解析完成后发布新快照；旧引用继续指向原来的文字和坐标。', '逐页输出、原有快照和任务检查点',
     ['逐页写入 FTS5 索引，核对整本页数与末页', '切换解析器创建新 parse_id；不覆盖旧块', '核对新旧文字、坐标和历史查询；本轮不调用 embedding'],
     ['可按 parse_id 查询的索引', '旧快照内容哈希对照'], ['GET /api/v1/documents/{vid}/parses', 'GET /api/v1/documents/{vid}/search?q=…&parse_id=…'], ['parse']),
    ('reader', '阅读与原文定位', '打开文档，搜索实际词句，点证据回到该版本、该页和该位置。', '已解析正文和可定位的证据块',
     ['按需加载 PDF；区分物理页与印刷页', '核对中后部、末页搜索和原文 bbox 高亮', '浏览器检查缩放、布局和实际阅读截图'],
     ['版本/页码/片段/坐标定位证据', '真实浏览器截图'], ['GET /api/v1/documents/{vid}/file', 'GET /api/v1/documents/{vid}/pages/{page}?parse_id=…'], ['snapshots']),
    ('analysis', '问答、比较与翻译', '选择文档后提出问题；回答与译文必须绑定证据快照。', '问题、选定文档和 parse_id',
     ['先检索原文，再执行受预算约束的模型任务', '比较两个原始版本的差异；译文与段落对齐', '缺证据明确说明；预算用尽显示 BLOCKED'],
     ['带引用回答/版本差异/对齐译文', '真实调用账本或明确阻塞原因'], ['POST /api/v1/qa/runs', 'POST /api/v1/versions/compare', 'GET /api/v1/translations/{vid}/export?parse_id=…'], ['reader']),
    ('discovery', '检索、追踪与推荐', '输入研究问题后查公开学术来源，选择候选导入，再设置追踪。', '研究查询和已读论文反馈',
     ['对公开来源实时请求，验证 URL 与下载安全', '区分元数据候选和已取得全文', '记录追踪时间、来源失败与用户反馈'],
     ['可复查来源候选', '持久化追踪记录'], ['POST /api/v1/search', 'POST /api/v1/search/import', 'POST /api/v1/watch-queries'], ['reader']),
    ('graph', '引用图谱与综述', '查看导入论文之间的真实引用关系，再按证据生成综述。', '已解析的引用条目和论文标识',
     ['仅从实际参考文献生成边，展示边的来源', '重算 NetworkX 图与统计', '综述与研究建议核查仍受核心模型预算约束'],
     ['可点的引用图与边证据', '有证据的综述或模型预算阻塞'], ['POST /api/v1/graphs', 'POST /api/v1/agent/runs'], ['snapshots']),
    ('export', '写作、绘图与导出', '从已核对证据写作；上传 CSV 后选列与图型，预览并导出。', '原文证据、CSV 或结构图草稿',
     ['引用绑定版本；受控统计和绘图模板', '检查缺失值、编码与数值列', '导出图、脚本、数据、Markdown/HTML/BibTeX'],
     ['可下载的实际产物', '统计明细和输入文件哈希'], ['POST /api/v1/charts', 'GET /api/v1/artifacts/{aid}/files/{name}', 'GET /api/v1/artifacts/{aid}/export'], ['reader']),
    ('recovery', '取消恢复与安全验收', '长任务可取消、从检查点恢复；检查权限与异常输入。', '运行中的任务、另一个工作区与异常输入',
     ['取消仅停止本项目任务；资源释放后恢复', '核对已提交页面不变且不重复执行', '检查未登录/跨工作区/目录逃逸与账本增量'],
     ['真实任务事件与恢复检查点', '安全响应、资源记录和调用账本差异'], ['POST /api/v1/runs/{rid}/cancel', 'POST /api/v1/runs/{rid}/resume', 'GET /api/v1/runs/{rid}/events'], ['upload']),
]


def _links(items):
    result = []
    for item in items if isinstance(items, list) else []:
        path = item.get('path') if isinstance(item, dict) else item
        if isinstance(path, str) and resolve_evidence_file(path):
            result.append({'path': path, 'url': _evidence_url(path),
                           **({'label': item['label']} if isinstance(item, dict) and 'label' in item else {})})
    return result


def build_workflow_report():
    saved = {}
    load_error = None
    if REPORT_PATH.is_file():
        try:
            if REPORT_PATH.stat().st_size > 8 * 1024 * 1024:
                raise ValueError('workflow report exceeds size limit')
            saved = json.loads(REPORT_PATH.read_text(encoding='utf-8'))
            if not isinstance(saved, dict):
                raise ValueError('workflow report must be an object')
        except (ValueError, OSError) as exc:
            saved = {}
            load_error = f'测试记录暂不可读：{type(exc).__name__}；未将读取失败记为通过。'
    recorded = {s['id']: s for s in saved.get('steps', []) if isinstance(s, dict) and s.get('id')}
    steps = []
    for number, spec in enumerate(STEPS, 1):
        sid, title, description, inputs, actions, outputs, routes, depends = spec
        data = recorded.get(sid, {})
        runs = []
        for original in data.get('runs', []):
            if not isinstance(original, dict):
                continue
            run = dict(original)
            run['status'] = run.get('status') if run.get('status') in STATUSES else 'NOT RUN'
            run['evidence_files'] = _links(run.get('evidence_files', []))
            run['screenshots'] = _links(run.get('screenshots', []))
            runs.append(run)
        passed = {r['id']: r for r in runs if r['status']=='PASS' and r.get('id')}
        def resolved(run):
            replacement = passed.get(run.get('resolved_by'))
            if not replacement or replacement['id']==run.get('id'):
                return False
            hashes = {f.get('sha256') for f in run.get('files', []) if f.get('sha256')}
            return bool(hashes & {f.get('sha256') for f in replacement.get('files', [])})
        statuses = {r['status'] for r in runs if not resolved(r)}
        status = next((s for s in ('FAIL', 'BLOCKED', 'NOT RUN', 'PASS') if s in statuses), 'NOT RUN')
        steps.append(dict(id=sid, number=number, title=title, description=description,
                          input=inputs, actions=actions, outputs=outputs, api_routes=routes,
                          depends_on=depends, status=status, runs=runs))
    return {
        'dataset': saved.get('dataset'),
        'steps': steps,
        'updated_at': saved.get('updated_at'),
        'test_execution_started': bool(saved.get('test_execution_started', False)),
        'published_at': saved.get('published_at'),
        'load_error': load_error,
        'guard_notice': 'Hydrogen 原冒烟 4 次已用尽；本批默认不调用供应商，密集索引关闭。GPU 必须保留 2 GiB 且能核算本项目进程显存。',
        'ledger': saved.get('ledger'),
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }
