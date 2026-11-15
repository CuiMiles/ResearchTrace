import { useEffect, useState } from 'react';
import { ApiError, errorMessage } from './api';
import { ArrowRight, FileText, RefreshCw } from './icons';
import './admin-workflow.css';

type Status = 'PASS' | 'FAIL' | 'BLOCKED' | 'NOT RUN';
interface Evidence { path: string; url: string; label?: string }
interface RunFile { name: string; sha256?: string; page_count?: number }
interface WorkflowRun {
  resolved_by?: string;
  id: string;
  label: string;
  status: Status;
  started?: string | number;
  finished?: string | number;
  duration_seconds?: number;
  summary: string;
  command?: string;
  files: RunFile[];
  counts?: Record<string, unknown>;
  evidence_files: Evidence[];
  screenshots: Evidence[];
  run_ids?: string[];
  results?: unknown;
}
interface WorkflowStep {
  id: string;
  number: number;
  title: string;
  description: string;
  input: unknown;
  actions: string[];
  outputs: string[];
  api_routes: string[];
  depends_on: string[];
  status: Status;
  runs: WorkflowRun[];
}
interface DatasetFile extends RunFile {
  id: string;
  relative_path: string;
  bytes: number;
  kind: string;
}
interface WorkflowReport {
  load_error?: string | null;
  dataset: {
    id: string;
    label: string;
    source_name: string;
    archive_sha256: string;
    extracted_root: string;
    file_count: number;
    files: DatasetFile[];
  } | null;
  steps: WorkflowStep[];
  updated_at?: string | number;
  test_execution_started: boolean;
  guard_notice?: unknown;
  budget_notice?: unknown;
  ledger?: unknown;
}

// Process guidance only. Execution states, files and results come from the API.
const guidance = [
  { id: 'inventory', title: '压缩包与文件清单', user: '查看压缩包来源、文件清单和 SHA256，确认本次材料。', backend: '安全解压并核对文件类型、大小、哈希与 PDF 页数。', verify: '对照原始压缩包哈希、清单与逐文件检查记录。' },
  { id: 'upload', title: '上传与版本识别', user: '导入文件，检查重复文件及同一论文的不同版本。', backend: '按内容哈希去重，保存不可变版本并记录版本关联依据。', verify: '核对 version / work ID、重复上传响应及原文件哈希。' },
  { id: 'parse', title: '原生 / OCR 结构解析', user: '检查文本层；扫描页进入 OCR，核对结构与原图。', backend: '按实际解析路径保存文字块、阅读顺序、页码、坐标与解析快照。', verify: '抽查双栏、公式、表格和扫描页；查看实际解析器与质量记录。' },
  { id: 'index', title: '检查点与全文索引', user: '查看逐页进度、恢复位置及已覆盖页数。', backend: '持久化检查点并建立索引，分别记录稀疏 / 密集索引覆盖率。', verify: '核对页数、分块数及末页检索结果；密集索引按实际覆盖判断。' },
  { id: 'read', title: '阅读与原文锚点', user: '打开论文，点击目录、正文引用和证据位置。', backend: '将块与物理页、坐标和具体版本关联，提供双向定位。', verify: '打开真实阅读截图和定位记录，核对页码、区域及版本。' },
  { id: 'analysis', title: '问答 / 比较 / 翻译', user: '提出新问题、比较版本或选择翻译范围。', backend: '检索真实证据，经预算与模型可用性检查后执行，保留模型和用量记录。', verify: '逐条对照回答引文、对比单元格与译文对齐；拦截原因以运行记录为准。' },
  { id: 'search', title: '检索与订阅追踪', user: '输入检索词，查看新论文及订阅变化。', backend: '查询已配置来源，保存检索结果、时间与订阅去重记录。', verify: '核对检索响应、文献来源链接及实际订阅记录。' },
  { id: 'graph', title: '引用图谱与综述', user: '点击论文与引用边，检查图谱依据及综述证据。', backend: '从真实参考文献构图，记录边来源并计算图谱指标。', verify: '逐边检查原文引用；核对节点、边数与保存的图谱结果。' },
  { id: 'export', title: 'CSV 绘图与导出', user: '上传 CSV、选列绘图，下载图表或文稿产物。', backend: '校验数值与绘图配置，生成可追溯的图表和导出文件。', verify: '对照 CSV 重算统计值，打开实际导出产物并检查来源。' },
  { id: 'recovery', title: '恢复与安全验证', user: '查看中断恢复、异常输入及权限检查结果。', backend: '验证持久化、幂等、取消与恢复，以及文件、网络和工作区边界。', verify: '查阅实际恢复日志、错误响应与权限测试，逐项保留失败和阻塞。' },
];

const plannedSteps: WorkflowStep[] = guidance.map((guide, i) => ({
  id: guide.id, number: i + 1, title: guide.title, description: '', input: null,
  actions: [], outputs: [], api_routes: [], depends_on: [], status: 'NOT RUN', runs: [],
}));
const statuses: Status[] = ['PASS', 'FAIL', 'BLOCKED', 'NOT RUN'];
const isObject = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(x => typeof x === 'string');
const validStatus = (v: unknown): v is Status => statuses.includes(v as Status);
const evidenceArray = (v: unknown) => Array.isArray(v) && v.every(x => isObject(x) && typeof x.path === 'string' && typeof x.url === 'string');

function readReport(value: unknown): WorkflowReport {
  if (!isObject(value) || !Array.isArray(value.steps) || value.steps.length > 10 || typeof value.test_execution_started !== 'boolean') {
    throw new Error('流程接口结构不符合约定，等待后端提供有效数据。');
  }
  const ids = new Set<string>();
  for (const step of value.steps) {
    if (!isObject(step) || typeof step.id !== 'string' || ids.has(step.id) || typeof step.number !== 'number'
      || typeof step.title !== 'string' || typeof step.description !== 'string' || !validStatus(step.status)
      || !strings(step.actions) || !strings(step.outputs) || !strings(step.api_routes) || !strings(step.depends_on) || !Array.isArray(step.runs)) {
      throw new Error('流程步骤数据不完整，保留上次已读取的记录。');
    }
    ids.add(step.id);
    for (const run of step.runs) {
      if (!isObject(run) || typeof run.id !== 'string' || typeof run.label !== 'string' || typeof run.summary !== 'string'
        || !validStatus(run.status) || !Array.isArray(run.files) || !run.files.every(f => isObject(f) && typeof f.name === 'string')
        || !evidenceArray(run.evidence_files) || !evidenceArray(run.screenshots)
        || (run.run_ids !== undefined && !strings(run.run_ids))) {
        throw new Error('运行记录结构不完整，保留上次已读取的记录。');
      }
    }
  }
  const dataset = value.dataset;
  if (dataset !== null && (!isObject(dataset) || typeof dataset.id !== 'string' || typeof dataset.label !== 'string'
    || typeof dataset.source_name !== 'string' || typeof dataset.archive_sha256 !== 'string' || typeof dataset.extracted_root !== 'string'
    || typeof dataset.file_count !== 'number' || !Array.isArray(dataset.files) || !dataset.files.every(f => isObject(f)
      && typeof f.id === 'string' && typeof f.name === 'string' && typeof f.relative_path === 'string'
      && typeof f.sha256 === 'string' && typeof f.bytes === 'number' && typeof f.kind === 'string'))) {
    throw new Error('数据集清单结构不完整，等待后端提供有效数据。');
  }
  return value as unknown as WorkflowReport;
}

function safeEvidenceUrl(raw: string): string | undefined {
  try {
    const url = new URL(raw, window.location.origin);
    if (url.origin !== window.location.origin || url.username || url.password || !url.pathname.startsWith('/api/v1/admin/')) return undefined;
    return url.pathname + url.search + url.hash;
  } catch { return undefined; }
}

function timestamp(value?: string | number) {
  if (value === undefined || value === null || value === '') return '未提供';
  const date = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false });
}
function display(value: unknown): string {
  if (value === undefined || value === null || value === '') return '尚未提供';
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}
function bytes(value: number) {
  return value < 1024 ? `${value} B` : value < 1048576 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1048576).toFixed(2)} MB`;
}
function StatusBadge({ status }: { status: Status }) {
  return <span className={`aw-status aw-status-${status.toLowerCase().replace(' ', '-')}`}>{status}</span>;
}
function EvidenceLink({ file }: { file: Evidence }) {
  const url = safeEvidenceUrl(file.url);
  return url ? <a className="aw-evidence-link" href={url} target="_blank" rel="noopener noreferrer"><FileText size={13} />{file.label || file.path}<span aria-hidden="true">↗</span></a>
    : <span className="aw-link-unavailable">{file.path}（证据链接不可用）</span>;
}

export function AdminWorkflow({ role }: { role: string }) {
  const [report, setReport] = useState<WorkflowReport | null>(null);
  const [selectedNumber, setSelectedNumber] = useState(1);
  const [selectedId, setSelectedId] = useState('');
  const [runStatus, setRunStatus] = useState<Status | 'ALL'>('ALL');
  const [query, setQuery] = useState('');
  const [fileQuery, setFileQuery] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [syncedAt, setSyncedAt] = useState('');

  useEffect(() => {
    if (role !== 'admin') return;
    let disposed = false;
    let active: AbortController | null = null;
    async function refresh() {
      if (active) return;
      const controller = new AbortController();
      active = controller;
      setRefreshing(true);
      try {
        const response = await fetch('/api/v1/admin/workflow', { credentials: 'same-origin', cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new ApiError(response.status, response.status === 404
          ? '流程接口尚未就绪；当前仅展示操作路线，尚未读取测试结果。'
          : response.status === 401 || response.status === 403 ? '管理员会话已失效或无权读取流程，请重新登录。' : `流程数据读取失败（${response.status}）。`);
        const next = readReport(await response.json());
        if (!disposed) {
          setReport(next);
          setError('');
          setSyncedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
        }
      } catch (e) {
        if (!disposed && !controller.signal.aborted) setError(errorMessage(e));
      } finally {
        if (!disposed) setRefreshing(false);
        active = null;
      }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => { disposed = true; window.clearInterval(timer); active?.abort(); };
  }, [role, refreshKey]);

  if (role !== 'admin') return null;
  const steps = report?.steps.length ? [...report.steps].sort((a, b) => a.number - b.number) : plannedSteps;
  const selected = steps.find(step => step.id === selectedId) ?? steps.find(step => step.number === selectedNumber) ?? steps[0];
  const guide = guidance[selected.number - 1];
  const dataset = report?.dataset;
  const filteredFiles = (dataset?.files ?? []).filter(file => `${file.name} ${file.relative_path} ${file.sha256} ${file.kind}`.toLowerCase().includes(fileQuery.trim().toLowerCase()));
  const filteredRuns = selected.runs.filter(run => (runStatus === 'ALL' || run.status === runStatus)
    && `${run.label} ${run.id} ${run.summary} ${run.command ?? ''} ${run.files.map(f => f.name).join(' ')}`.toLowerCase().includes(query.trim().toLowerCase()));
  const runCount = steps.reduce((sum, step) => sum + step.runs.length, 0);
  const dependsOn = selected.depends_on.map(id => steps.find(step => step.id === id)?.title ?? id);

  return (
    <section className="admin-workflow" aria-labelledby="admin-workflow-title">
      <header className="aw-header">
        <div>
          <span className="aw-eyebrow">从原始文件到可核验结果</span>
          <h2 id="admin-workflow-title">文件处理全流程</h2>
          <p>点击编号节点查看操作、后台处理与该步骤的真实测试记录。</p>
        </div>
        <div className="aw-sync">
          <button type="button" className="small-button" disabled={refreshing} onClick={() => setRefreshKey(key => key + 1)}><RefreshCw size={14} className={refreshing ? 'aw-spinning' : ''} />刷新流程</button>
          <small>每 5 秒自动更新 · {syncedAt ? `最近读取 ${syncedAt}` : refreshing ? '正在读取…' : '尚未同步'}</small>
        </div>
      </header>

      <div className="aw-overview">
        <div><span>本次数据集</span><strong>{dataset?.label || '等待登记数据集'}</strong><small>{dataset?.source_name || '文件清单以后台登记为准'}</small></div>
        <div><span>文件清单</span><strong>{dataset ? `${dataset.file_count} 个文件` : '尚未读取'}</strong><small>原始文件与哈希逐一对应</small></div>
        <div><span>流程运行记录</span><strong>{report ? `${runCount} 条记录` : '尚未读取'}</strong><small>{report ? report.test_execution_started ? '测试已开始，按节点核验结果' : '测试尚未开始' : '尚未确认测试状态'}</small></div>
      </div>

      {error && <div className="aw-notice aw-error" role="alert">{error}{report && <span> 当前保留上次成功读取的数据，等待下次刷新。</span>}</div>}
      {report?.load_error && <div className="aw-notice aw-error" role="alert">{report.load_error}</div>}
      {report && <div className="aw-source-note">数据更新时间：{timestamp(report.updated_at)} · 状态与证据来自后台运行记录。点击节点查看结果；节点选择不会触发测试。</div>}
      {report && (['guard_notice', 'budget_notice', 'ledger'] as const).map(field => report[field] !== undefined && report[field] !== null && <details key={field} className="aw-backend-notice"><summary>{field === 'ledger' ? '后台用量账本' : field === 'budget_notice' ? '后台预算说明' : '后台执行保护说明'}</summary><pre>{display(report[field])}</pre></details>)}

      <ol className="aw-nodes" aria-label="文件处理步骤">
        {steps.map((step, index) => <li key={step.id}>
          <button type="button" className={`aw-node${selected.id === step.id ? ' aw-node-selected' : ''}`} aria-pressed={selected.id === step.id} aria-controls="aw-step-panel" onClick={() => { setSelectedId(step.id); setSelectedNumber(step.number); }}>
            <span className="aw-node-top"><span className="aw-number">{String(step.number).padStart(2, '0')}</span><StatusBadge status={step.status} /></span>
            <strong>{step.title}</strong>
            {step.number === 3 && <span className="aw-node-branches">原生文本 ↗　扫描 OCR ↘</span>}
            <small>{step.runs.length ? `${step.runs.length} 条运行记录` : '尚无运行记录'}</small>
          </button>
          {index < steps.length - 1 && <ArrowRight className="aw-node-arrow" size={17} aria-hidden="true" />}
        </li>)}
      </ol>

      <section id="aw-step-panel" className="aw-panel" aria-labelledby="aw-step-title">
        <header className="aw-panel-header"><div><span className="aw-eyebrow">当前步骤 {String(selected.number).padStart(2, '0')}</span><h3 id="aw-step-title">{selected.title}</h3></div><StatusBadge status={selected.status} /></header>
        {selected.description && <p className="aw-description">{selected.description}</p>}
        <div className="aw-explainer">
          <div><h4>你要做什么</h4><p>{guide?.user || selected.description || '选择本步骤，检查输入与输出。'}</p></div>
          <div><h4>后台做什么</h4>{selected.actions.length ? <ul>{selected.actions.map((action, i) => <li key={i}>{action}</li>)}</ul> : <p>{guide?.backend || '等待后台提供处理步骤。'}</p>}</div>
          <div><h4>怎么核验</h4><p>{guide?.verify || '打开该步骤的运行记录与原始证据文件逐项核对。'}</p></div>
        </div>
        {selected.number === 3 && <div className="aw-parse-branches" aria-label="结构解析分支"><div><strong>有可靠文本层 → 原生解析</strong><span>文字、阅读顺序、坐标、公式 / 表格来源</span></div><div><strong>扫描页 / 文本层不足 → OCR</strong><span>页面图、识别文字、位置与质量标记</span></div></div>}
        <div className="aw-step-io">
          <div><h4>输入</h4><pre>{report ? display(selected.input) : '等待流程接口提供实际输入'}</pre></div>
          <div><h4>输出</h4>{selected.outputs.length ? <ul>{selected.outputs.map((output, i) => <li key={i}>{output}</li>)}</ul> : <p>尚未登记输出</p>}</div>
        </div>
        {dependsOn.length > 0 && <p className="aw-dependencies">前置步骤：{dependsOn.join(' → ')}</p>}
        {selected.api_routes.length > 0 && <details className="aw-api"><summary>查看本步骤 API 路径（{selected.api_routes.length}）</summary><ul>{selected.api_routes.map((route, i) => <li key={i}><code>{route}</code></li>)}</ul></details>}

        <div className="aw-runs-heading"><h4>本步骤真实运行记录 <span>（{selected.runs.length}）</span></h4><span>仅显示当前选中步骤</span></div>
        <div className="aw-run-filters">
          <label>记录状态<select value={runStatus} onChange={e => setRunStatus(e.target.value as Status | 'ALL')}><option value="ALL">全部状态</option>{statuses.map(status => <option value={status} key={status}>{status}</option>)}</select></label>
          <label className="aw-run-search">搜索本步骤记录<input value={query} onChange={e => setQuery(e.target.value)} placeholder="运行名称、文件名、摘要或运行 ID" /></label>
          {(runStatus !== 'ALL' || query) && <button type="button" className="small-button" onClick={() => { setRunStatus('ALL'); setQuery(''); }}>清除筛选</button>}
        </div>
        {selected.runs.length === 0 ? <div className="aw-empty"><strong>{selected.status} · 尚无本步骤运行记录</strong><p>后续执行产生的结果会在这里自动出现；当前没有可核验的测试产物。</p></div>
          : filteredRuns.length === 0 ? <div className="aw-empty">当前筛选无匹配记录。请清除筛选查看本步骤的 {selected.runs.length} 条记录。</div>
            : <div className="aw-runs">{filteredRuns.map(run => <article className="aw-run" key={run.id}>
              <header><h5>{run.label}</h5><StatusBadge status={run.status} /></header>
              <p className="aw-run-summary">{run.summary}</p>
              {run.resolved_by && <p className="aw-source-note">此记录保留初次失败事实。修复后复测记录：{run.resolved_by}。</p>}
              <dl className="aw-run-meta"><div><dt>运行 ID</dt><dd><code>{run.id}</code></dd></div><div><dt>开始</dt><dd>{timestamp(run.started)}</dd></div><div><dt>完成</dt><dd>{timestamp(run.finished)}</dd></div>{run.duration_seconds !== undefined && <div><dt>耗时</dt><dd>{run.duration_seconds} 秒</dd></div>}</dl>
              {run.run_ids && run.run_ids.length > 0 && <p className="aw-dependencies">关联任务：{run.run_ids.join(' · ')}</p>}
              {run.files.length > 0 && <details className="aw-run-details"><summary>本次使用文件（{run.files.length}）</summary><ul>{run.files.map((file, i) => <li key={`${file.name}-${i}`}><strong>{file.name}</strong>{file.page_count !== undefined && <span> · {file.page_count} 页</span>}{file.sha256 && <code>SHA256 {file.sha256}</code>}</li>)}</ul></details>}
              {run.counts && Object.keys(run.counts).length > 0 && <details className="aw-run-details" open><summary>实际处理统计</summary><pre>{display(run.counts)}</pre></details>}
              {run.results !== undefined && run.results !== null && <details className="aw-run-details" open><summary>实际结果</summary><pre>{display(run.results)}</pre></details>}
              {run.command && <details className="aw-run-details"><summary>实际执行命令 / 测试步骤</summary><pre>{run.command}</pre></details>}
              {run.evidence_files.length > 0 && <div className="aw-evidence"><h6>原始证据文件</h6>{run.evidence_files.map((file, i) => <EvidenceLink key={`${file.path}-${i}`} file={file} />)}</div>}
              {run.screenshots.length > 0 && <div className="aw-run-screenshots"><h6>浏览器实拍截图</h6><div>{run.screenshots.map((shot, i) => {
                const url = safeEvidenceUrl(shot.url);
                return url ? <a href={url} target="_blank" rel="noopener noreferrer" key={`${shot.path}-${i}`}><img src={url} alt={shot.label || shot.path} loading="lazy" /><span>{shot.label || shot.path} ↗</span></a> : <span key={`${shot.path}-${i}`}>{shot.path}（截图链接不可用）</span>;
              })}</div></div>}
              {run.evidence_files.length === 0 && run.screenshots.length === 0 && <p className="aw-source-note">后台尚未附加证据文件或截图，请结合已返回结果核验。</p>}
            </article>)}</div>}
      </section>

      <details className="aw-inventory">
        <summary><FileText size={16} />数据集文件清单{dataset ? `（${dataset.file_count}）` : '（等待登记）'}<span>展开核对原始文件与哈希</span></summary>
        {dataset ? <div className="aw-inventory-body">
          <dl className="aw-dataset-meta"><div><dt>来源</dt><dd>{dataset.source_name}</dd></div><div><dt>数据集 ID</dt><dd>{dataset.id}</dd></div><div><dt>压缩包 SHA256</dt><dd><code>{dataset.archive_sha256 || '尚未提供'}</code></dd></div><div><dt>解压目录</dt><dd><code>{dataset.extracted_root || '尚未解压'}</code></dd></div></dl>
          <label>筛选数据集文件<input value={fileQuery} onChange={e => setFileQuery(e.target.value)} placeholder="文件名、相对路径、类型或 SHA256" /></label>
          <p className="aw-source-note">当前显示 {filteredFiles.length} / {dataset.files.length} 条清单记录</p>
          <div className="aw-file-table"><table><thead><tr><th>文件 / 相对路径</th><th>类型</th><th>大小</th><th>页数</th><th>SHA256</th></tr></thead><tbody>{filteredFiles.map(file => <tr key={file.id}><td><strong>{file.name}</strong><small>{file.relative_path}</small></td><td>{file.kind}</td><td>{bytes(file.bytes)}</td><td>{file.page_count ?? '未提供'}</td><td><code>{file.sha256 || '未提供'}</code></td></tr>)}</tbody></table></div>
          {filteredFiles.length === 0 && <p className="aw-empty">{dataset.files.length ? '没有匹配的文件。' : '后台尚未登记文件条目。'}</p>}
        </div> : <p className="aw-empty">尚未从后台取得数据集清单。登记后的文件、哈希与页数会在这里展示。</p>}
      </details>
    </section>
  );
}
