import { useEffect, useState } from 'react';
import { CheckCircle2, Eye, FileText, Image, RefreshCw, ShieldCheck, X } from './icons';
import { api, errorMessage } from './api';
import { Badge, Busy, Empty, ErrorBox } from './ui';

interface EvidenceLink {
  path: string;
  url: string;
}

interface ScreenshotItem {
  label: string;
  path: string;
  url: string;
}

interface ModuleTest {
  name: string;
  case_refs: string[];
  status: 'PASS' | 'BLOCKED' | 'NOT RUN' | string;
  summary: string;
  api_steps: string[];
  result_files: EvidenceLink[];
  screenshots: ScreenshotItem[];
}

interface ModuleGroup {
  id: string;
  title: string;
  case_ids: string[];
  pass_count: number;
  blocked_count: number;
  total_count: number;
  tests: ModuleTest[];
}

interface AcceptanceCase {
  case_id: string;
  title: string;
  status: string;
  observed: string;
  command_or_browser_steps: string;
  remaining_risk: string;
  new_provider_calls: number;
  evidence_files: EvidenceLink[];
  evidence_paths: string[];
}

interface AcceptanceReport {
  environment: string;
  pytest_summary: string;
  summary: {
    total: number;
    pass: number;
    blocked: number;
    not_run: number;
    fail: number;
  };
  modules: ModuleGroup[];
  cases: AcceptanceCase[];
}

function statusBadgeKey(status: string): string {
  if (status === 'PASS') return 'completed';
  if (status === 'BLOCKED' || status === 'FAIL') return 'blocked';
  return 'partial';
}

export function AdminAcceptancePage({ role }: { role: string }) {
  const [report, setReport] = useState<AcceptanceReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'PASS' | 'BLOCKED'>('ALL');
  const [query, setQuery] = useState('');
  const [previewImage, setPreviewImage] = useState<ScreenshotItem | null>(null);
  const [previewDoc, setPreviewDoc] = useState<{ path: string; content: string } | null>(null);
  const [docLoading, setDocLoading] = useState(false);

  async function load() {
    setLoading(true);
    setError('');
    try {
      setReport(await api<AcceptanceReport>('/admin/acceptance'));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (role === 'admin') {
      void load();
    }
  }, [role]);

  async function openEvidenceFile(file: EvidenceLink) {
    setDocLoading(true);
    setError('');
    try {
      const resp = await fetch(file.url, { credentials: 'same-origin' });
      if (!resp.ok) {
        throw new Error(`无法读取证据文件 (${resp.status})`);
      }
      const text = await resp.text();
      setPreviewDoc({ path: file.path, content: text.slice(0, 60000) });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setDocLoading(false);
    }
  }

  if (role !== 'admin') {
    return (
      <div className="page-content">
        <Empty title="测试验收看板仅管理员可见" icon={<ShieldCheck size={36} />}>
          <p>请使用管理员访问码（RT_ADMIN_CODE）登录后查看各模块 API 调用链、保存结果与实拍截图。</p>
        </Empty>
      </div>
    );
  }

  const normalizedQuery = query.trim().toLowerCase();
  const filteredModules = (report?.modules ?? []).map(mod => ({
    ...mod,
    tests: mod.tests.filter(t => {
      if (statusFilter !== 'ALL' && t.status !== statusFilter) return false;
      if (!normalizedQuery) return true;
      return [mod.title, t.name, t.summary, t.case_refs.join(' '), t.api_steps.join(' ')]
        .join(' ')
        .toLowerCase()
        .includes(normalizedQuery);
    }),
  })).filter(mod => mod.tests.length > 0);

  const filteredCases = (report?.cases ?? []).filter(c => {
    if (statusFilter !== 'ALL' && c.status !== statusFilter) return false;
    if (!normalizedQuery) return true;
    return [c.case_id, c.title, c.observed, c.command_or_browser_steps, c.evidence_paths.join(' ')]
      .join(' ')
      .toLowerCase()
      .includes(normalizedQuery);
  });

  const screenshotCount = (report?.modules ?? []).reduce(
    (acc, m) => acc + m.tests.reduce((sub, t) => sub + t.screenshots.length, 0),
    0,
  );

  return (
    <div className="page-content acceptance-page">
      <div className="page-heading">
        <div>
          <h1>测试验收与截图看板</h1>
          <p>按题目六大类功能与 ACCEPTANCE.md 展示已执行测试、每步 API 调用链、原始结果文件与实机截图；BLOCKED 项均诚实保留。</p>
        </div>
        <button className="secondary-button" disabled={loading} onClick={() => void load()}>
          <RefreshCw size={15} />
          刷新验收数据
        </button>
      </div>

      {error && <ErrorBox error={error} onClose={() => setError('')} />}

      {loading && !report ? (
        <Busy>正在加载验收报告与截图索引…</Busy>
      ) : (
        report && (
          <>
            <div className="provider-overview acceptance-kpis">
              <div>
                <span>64 项总体验收进度</span>
                <strong>
                  {report.summary.pass} PASS / {report.summary.blocked} BLOCKED
                </strong>
                <small>FAIL: {report.summary.fail} · NOT RUN: {report.summary.not_run}</small>
              </div>
              <div>
                <span>自动化回归与构建</span>
                <strong>{report.pytest_summary}</strong>
                <small>pytest + ruff + tsc + Vite + OpenAPI</small>
              </div>
              <div>
                <span>环境与可视化证据</span>
                <strong>{screenshotCount} 张实测截图</strong>
                <small>{report.environment}</small>
              </div>
            </div>

            <div className="acceptance-toolbar">
              <div className="segmented" role="group" aria-label="按状态筛选">
                {(['ALL', 'PASS', 'BLOCKED'] as const).map(st => (
                  <button
                    key={st}
                    className={statusFilter === st ? 'active' : ''}
                    onClick={() => setStatusFilter(st)}
                  >
                    {st === 'ALL'
                      ? `全部 (${report.summary.total})`
                      : st === 'PASS'
                        ? `PASS (${report.summary.pass})`
                        : `BLOCKED (${report.summary.blocked})`}
                  </button>
                ))}
              </div>
              <input
                className="acceptance-filter-input"
                aria-label="搜索测试、API 或验收编号"
                placeholder="筛选模块、API 路径或编号（如 /parses、B02、E06、MinerU）"
                value={query}
                onChange={e => setQuery(e.target.value)}
              />
            </div>

            <section className="acceptance-modules">
              <h2>
                <CheckCircle2 size={18} /> 六大类功能实测追踪（API 调用链 + 保存文件 + 截图）
              </h2>
              {filteredModules.map(mod => (
                <article key={mod.id} className="acceptance-module-card">
                  <header className="acceptance-module-head">
                    <div>
                      <h3>{mod.title}</h3>
                      <small className="muted">
                        覆盖编号：{mod.case_ids.join(', ')}
                      </small>
                    </div>
                    <div className="acceptance-module-badges">
                      <Badge status="completed">{mod.pass_count} PASS</Badge>
                      {mod.blocked_count > 0 && <Badge status="blocked">{mod.blocked_count} BLOCKED</Badge>}
                    </div>
                  </header>

                  <div className="acceptance-tests-list">
                    {mod.tests.map(test => (
                      <div key={test.name} className="acceptance-test-row">
                        <div className="acceptance-test-top">
                          <div className="acceptance-test-title">
                            <Badge status={statusBadgeKey(test.status)}>{test.status}</Badge>
                            <strong>{test.name}</strong>
                            {test.case_refs.map(ref => (
                              <Badge key={ref}>{ref}</Badge>
                            ))}
                          </div>
                          <p className="acceptance-test-summary">{test.summary}</p>
                        </div>

                        <div className="acceptance-detail-block">
                          <span className="acceptance-label">调用 API / 执行步骤</span>
                          <ol className="api-chain">
                            {test.api_steps.map((step, idx) => (
                              <li key={idx} className="api-chip">
                                <code>{step}</code>
                              </li>
                            ))}
                          </ol>
                        </div>

                        {test.result_files.length > 0 && (
                          <div className="acceptance-detail-block">
                            <span className="acceptance-label">已保存结果文件</span>
                            <div className="evidence-links-row">
                              {test.result_files.map(file => (
                                <button
                                  key={file.path}
                                  className="small-button"
                                  disabled={docLoading}
                                  onClick={() => void openEvidenceFile(file)}
                                >
                                  <FileText size={13} />
                                  {file.path}
                                </button>
                              ))}
                            </div>
                          </div>
                        )}

                        {test.screenshots.length > 0 && (
                          <div className="acceptance-detail-block">
                            <span className="acceptance-label">
                              <Image size={13} /> 浏览器实拍截图（点击放大）
                            </span>
                            <div className="screenshot-grid">
                              {test.screenshots.map(shot => (
                                <button
                                  key={shot.path}
                                  type="button"
                                  className="screenshot-thumb"
                                  onClick={() => setPreviewImage(shot)}
                                >
                                  <img src={shot.url} alt={shot.label} />
                                  <span>
                                    <Eye size={12} /> {shot.label}
                                  </span>
                                </button>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </article>
              ))}
            </section>

            <section className="acceptance-matrix-section">
              <h2>ACCEPTANCE.md 全量 64 项验收明细（{filteredCases.length} 项）</h2>
              <div className="data-table-wrap">
                <table className="acceptance-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>验收项</th>
                      <th>状态</th>
                      <th>新增模型请求</th>
                      <th>实测结论 / 受阻原因</th>
                      <th>证据文件（点击查看）</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredCases.map(c => (
                      <tr key={c.case_id}>
                        <td>
                          <strong>{c.case_id}</strong>
                        </td>
                        <td>{c.title}</td>
                        <td>
                          <Badge status={statusBadgeKey(c.status)}>{c.status}</Badge>
                        </td>
                        <td>{c.new_provider_calls}</td>
                        <td className="acceptance-observed-cell">
                          <div>{c.observed}</div>
                          {c.command_or_browser_steps && (
                            <small className="muted">执行路径：{c.command_or_browser_steps}</small>
                          )}
                        </td>
                        <td>
                          <div className="evidence-links-row compact">
                            {c.evidence_files.map(f => (
                              <button
                                key={f.path}
                                className="text-button"
                                onClick={() => void openEvidenceFile(f)}
                              >
                                {f.path}
                              </button>
                            ))}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )
      )}

      {previewImage && (
        <div
          className="lightbox-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label={previewImage.label}
          onClick={() => setPreviewImage(null)}
        >
          <div className="lightbox-dialog" onClick={e => e.stopPropagation()}>
            <header className="lightbox-head">
              <div>
                <strong>{previewImage.label}</strong>
                <small className="muted">{previewImage.path}</small>
              </div>
              <button
                className="icon-button"
                aria-label="关闭截图预览"
                onClick={() => setPreviewImage(null)}
              >
                <X size={17} />
              </button>
            </header>
            <div className="lightbox-body">
              <img src={previewImage.url} alt={previewImage.label} />
            </div>
          </div>
        </div>
      )}

      {previewDoc && (
        <div
          className="lightbox-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label={previewDoc.path}
          onClick={() => setPreviewDoc(null)}
        >
          <div className="lightbox-dialog doc-viewer" onClick={e => e.stopPropagation()}>
            <header className="lightbox-head">
              <div>
                <strong>{previewDoc.path}</strong>
                <small className="muted">仅展示安全目录中的已保存测试证据</small>
              </div>
              <button
                className="icon-button"
                aria-label="关闭结果文件"
                onClick={() => setPreviewDoc(null)}
              >
                <X size={17} />
              </button>
            </header>
            <div className="lightbox-body">
              <pre className="code-block log-viewer">{previewDoc.content}</pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
