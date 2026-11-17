/**
 * Application root: session gate, routes and the workbench shell.
 * Pages own their data; shared workspace state lives in app/workspace.tsx.
 */
import { lazy, Suspense, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import {
  ArrowRight,
  BookOpen,
  CircleHelp,
  Clock3,
  FileChartColumn,
  FileText,
  FlaskConical,
  GitCompareArrows,
  Home,
  Layers3,
  Library,
  ListChecks,
  LogOut,
  Menu,
  MessagesSquare,
  Network,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  UploadCloud,
  X,
} from './icons';
import { api, errorMessage } from './api';
import type { Session } from './types';
import { Boundary, Busy, ErrorBox } from './ui';
import { ModelConfig } from './ModelConfig';
import { activeRun, RunDetail, RunsDrawer } from './RunPanel';
import { WorkspaceProvider, useWorkspace } from './app/workspace';
import { HomePage } from './features/home/HomePage';
import { LibraryPage } from './features/library/LibraryPage';
import { ChatPage } from './features/chat/ChatPage';
import { Reader } from './Reader';
import { ReferenceTools } from './components/ReferenceTools';

const ComparePage = lazy(() => import('./Research').then((m) => ({ default: m.ComparePage })));
const SearchPage = lazy(() => import('./Research').then((m) => ({ default: m.SearchPage })));
const GraphPage = lazy(() => import('./Research').then((m) => ({ default: m.GraphPage })));
const AuditPage = lazy(() => import('./Research').then((m) => ({ default: m.AuditPage })));
const WritingPage = lazy(() => import('./Writing').then((m) => ({ default: m.WritingPage })));
const ResourcesPage = lazy(() => import('./Writing').then((m) => ({ default: m.ResourcesPage })));
const AdminAcceptancePage = lazy(() =>
  import('./AdminAcceptance').then((m) => ({ default: m.AdminAcceptancePage })),
);

interface NavItem {
  to: string;
  label: string;
  icon: typeof Home;
}

const NAVIGATION: NavItem[] = [
  { to: '/', label: '工作台', icon: Home },
  { to: '/library', label: '文献库', icon: Library },
  { to: '/chat', label: '证据问答', icon: MessagesSquare },
  { to: '/compare', label: '版本与比较', icon: GitCompareArrows },
  { to: '/discover', label: '检索与推荐', icon: Search },
  { to: '/insights', label: '图谱与核查', icon: Network },
  { to: '/studio', label: '写作工坊', icon: FileChartColumn },
];

const TITLES: [RegExp, string][] = [
  [/^\/library/, '文献库'],
  [/^\/read/, '阅读'],
  [/^\/chat/, '证据问答'],
  [/^\/compare/, '版本与比较'],
  [/^\/discover/, '检索与推荐'],
  [/^\/insights/, '图谱与核查'],
  [/^\/studio/, '写作工坊'],
  [/^\/settings\/acceptance/, '验收与截图'],
  [/^\/settings/, '资源与配额'],
  [/^\/runs/, '任务详情'],
  [/^\/$/, '工作台'],
];

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  useEffect(() => {
    api<Session>('/auth/session')
      .then(setSession)
      .catch(() => setSession(null))
      .finally(() => setChecking(false));
  }, []);
  if (checking) {
    return (
      <div className="app-loading">
        <div className="brand-mark">
          <Layers3 size={22} />
        </div>
        <Busy>正在打开研证工作台</Busy>
      </div>
    );
  }
  if (!session) return <Login onLogin={setSession} />;
  return (
    <WorkspaceProvider session={session} onLogout={() => setSession(null)}>
      <Shell />
    </WorkspaceProvider>
  );
}

function Shell() {
  const ws = useWorkspace();
  const location = useLocation();
  const navigate = useNavigate();
  const [drawer, setDrawer] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [dragging, setDragging] = useState(false);
  const working = ws.runs.filter(activeRun).length;
  const title = TITLES.find(([pattern]) => pattern.test(location.pathname))?.[1] ?? '';
  const reading = location.pathname.startsWith('/read') || location.pathname.startsWith('/chat');
  const lastRead = localStorage.getItem('rt-version');
  useEffect(() => setMobileNav(false), [location.pathname]);

  return (
    <ModelConfig.Provider value={ws.capability}>
      <div
        className={`app-shell ${location.pathname.startsWith('/read') ? 'compact' : ''}`}
        onDragOver={(e) => {
          if (e.dataTransfer.types.includes('Files')) {
            e.preventDefault();
            setDragging(true);
          }
        }}
        onDragLeave={(e) => {
          if (!e.relatedTarget) setDragging(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void ws.upload(e.dataTransfer.files).then((r) => {
            if (r?.documents.length === 1 && !r.batch_id) ws.openDocument(r.documents[0].id);
            else if (r) navigate('/library');
          });
        }}
      >
        <aside className={`main-sidebar ${mobileNav ? 'mobile-open' : ''}`}>
          <NavLink className="brand" to="/">
            <div className="brand-mark">
              <Layers3 size={20} />
            </div>
            <span>
              <strong>研证</strong>
              <small>ResearchTrace</small>
            </span>
          </NavLink>
          <button className="primary-button import-button" disabled={ws.uploading} onClick={ws.openUpload}>
            {ws.uploading ? <Busy /> : <Plus size={16} />}
            <span className="label">导入论文</span>
          </button>
          <nav aria-label="主导航">
            {NAVIGATION.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.to === '/'} title={item.label}>
                <item.icon size={17} />
                <span>{item.label}</span>
                {item.to === '/library' && <small>{ws.versions.length}</small>}
              </NavLink>
            ))}
            {lastRead && ws.versions.some((v) => v.id === lastRead) && (
              <NavLink to={`/read/${lastRead}`} title="继续阅读">
                <BookOpen size={17} />
                <span>继续阅读</span>
              </NavLink>
            )}
          </nav>
          <div className="sidebar-bottom">
            <div className="evidence-principle">
              <ShieldCheck size={15} />
              <span>每个结论，都能回到原文</span>
            </div>
            {ws.session.role === 'admin' && (
              <NavLink to="/settings/acceptance">
                <ListChecks size={17} />
                <span>验收与截图</span>
              </NavLink>
            )}
            <NavLink to="/settings" end>
              <Settings2 size={17} />
              <span>资源与配额</span>
            </NavLink>
            <button onClick={() => void ws.logout()}>
              <LogOut size={17} />
              <span>退出工作区</span>
            </button>
          </div>
        </aside>
        <div className="app-main">
          <header className="topbar">
            <div className="breadcrumbs">
              <button
                className="icon-button mobile-only"
                aria-label="展开主导航"
                onClick={() => setMobileNav(!mobileNav)}
              >
                <Menu size={18} />
              </button>
              <span>研究工作区</span>
              <span className="breadcrumb-slash">/</span>
              <strong className="truncate">{title}</strong>
            </div>
            <div className="topbar-actions">
              {ws.capability && (
                <span className="model-pill" title="核心分析模型（服务器配置）">
                  <FlaskConical size={13} />
                  {ws.capability.model_configured ? ws.capability.core_model : '模型未配置'}
                </span>
              )}
              <span className="connected">
                <span />
                数据持久化
              </span>
              <button className="task-button" onClick={() => setDrawer(true)}>
                <Clock3 size={16} />
                <span>任务</span>
                {working > 0 && <b>{working}</b>}
              </button>
              <span className="user-avatar" title={ws.session.role === 'admin' ? '管理员' : '评审'}>
                {ws.session.role === 'admin' ? '管' : '评'}
              </span>
            </div>
          </header>
          {ws.error && (
            <div className="global-message">
              <ErrorBox error={ws.error} onClose={() => ws.setError('')} />
            </div>
          )}
          {ws.notice && (
            <div className="notice" role="status">
              <span>{ws.notice}</span>
              <button className="icon-button" aria-label="关闭通知" onClick={() => ws.setNotice('')}>
                <X size={15} />
              </button>
            </div>
          )}
          {ws.capability && !ws.capability.model_configured && (
            <div className="notice missing-config" role="status">
              服务器尚未配置模型密钥：导入、解析、阅读、检索和绘图可用；问答与翻译暂不可用。
            </div>
          )}
          <main className={`main-content ${reading ? 'reader-content' : ''}`}>
            <Boundary>
              <Suspense fallback={<div className="page-content"><Busy>载入页面</Busy></div>}>
                <Routes>
                  <Route path="/" element={<HomePage />} />
                  <Route path="/library" element={<LibraryPage />} />
                  <Route path="/read/:versionId" element={<ReaderRoute />} />
                  <Route path="/read" element={<ReaderRoute />} />
                  <Route path="/chat" element={<ChatPage />} />
                  <Route path="/chat/:threadId" element={<ChatPage />} />
                  <Route path="/compare" element={<CompareRoute />} />
                  <Route
                    path="/discover"
                    element={<SearchPage refresh={() => void ws.refresh()} onImport={() => void ws.refresh()} />}
                  />
                  <Route path="/insights" element={<InsightsRoute />} />
                  <Route path="/studio" element={<WritingPage versions={ws.versions} onEvidence={(e) => void ws.openEvidence(e)} refresh={() => void ws.refresh()} />} />
                  <Route path="/settings" element={<ResourcesPage role={ws.session.role} onOpenAcceptance={() => navigate('/settings/acceptance')} />} />
                  <Route path="/settings/acceptance" element={<AdminAcceptancePage role={ws.session.role} />} />
                  <Route path="/runs/:runId" element={<RunRoute />} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </Suspense>
            </Boundary>
          </main>
        </div>
        {drawer && (
          <RunsDrawer
            runs={ws.runs}
            onClose={() => setDrawer(false)}
            onSelect={(id) => {
              setDrawer(false);
              navigate(`/runs/${id}`);
            }}
          />
        )}
        {dragging && (
          <div className="drop-overlay">
            <UploadCloud size={54} />
            <h2>松开以导入 PDF</h2>
            <p>文件进入当前独立工作区，逐页解析并保留版本</p>
          </div>
        )}
      </div>
    </ModelConfig.Provider>
  );
}

function ReaderRoute() {
  const ws = useWorkspace();
  const { versionId } = useParams();
  const navigate = useNavigate();
  const [runId, setRunId] = useState<string | null>(null);
  const fallback = versionId ?? localStorage.getItem('rt-version') ?? ws.versions[0]?.id ?? null;
  const version = ws.versions.find((v) => v.id === fallback) ?? null;
  useEffect(() => {
    if (version) localStorage.setItem('rt-version', version.id);
  }, [version?.id]);
  if (!ws.loaded) return <div className="page-content"><Busy>载入文献</Busy></div>;
  return (
    <>
    {version && <ReferenceTools key={version.id} versionId={version.id}
      onEvidence={(e) => void ws.openEvidence(e)} />}
    <Reader
      key={version?.id ?? 'empty'}
      versions={ws.versions}
      version={version}
      setVersion={(id) => navigate(`/read/${id}`)}
      highlight={ws.highlight}
      onEvidence={(e) => void ws.openEvidence(e)}
      runId={runId}
      setRunId={setRunId}
      refresh={() => void ws.refresh()}
      startUpload={ws.openUpload}
    />
    </>
  );
}

function CompareRoute() {
  const ws = useWorkspace();
  const [runId, setRunId] = useState<string | null>(null);
  return (
    <ComparePage versions={ws.versions} onEvidence={(e) => void ws.openEvidence(e)} onRun={setRunId} runId={runId} />
  );
}

function InsightsRoute() {
  const ws = useWorkspace();
  const [tab, setTab] = useState<'graph' | 'audit'>('graph');
  const [auditRun, setAuditRun] = useState<string | null>(null);
  return (
    <>
      <div className="insights-tabs">
        <div className="tab-row">
          <button className={tab === 'graph' ? 'active' : ''} onClick={() => setTab('graph')}>
            <Network size={16} />
            引用图谱与核心文献
          </button>
          <button className={tab === 'audit' ? 'active' : ''} onClick={() => setTab('audit')}>
            <ShieldCheck size={16} />
            Future Work 核查
          </button>
        </div>
      </div>
      {tab === 'graph' ? (
        <GraphPage versions={ws.versions} onEvidence={(e) => void ws.openEvidence(e)} onVersion={ws.openDocument} />
      ) : (
        <AuditPage
          versions={ws.versions}
          onEvidence={(e) => void ws.openEvidence(e)}
          onRun={setAuditRun}
          runId={auditRun}
        />
      )}
    </>
  );
}

function RunRoute() {
  const ws = useWorkspace();
  const { runId } = useParams();
  if (!runId) return <Navigate to="/" replace />;
  return (
    <div className="page-content" style={{ maxWidth: 900 }}>
      <RunDetail runId={runId} onEvidence={(e) => void ws.openEvidence(e)} onUpdate={() => void ws.refresh()} />
    </div>
  );
}

function Login({ onLogin }: { onLogin: (s: Session) => void }) {
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      onLogin(await api<Session>('/auth/login', { code }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }
  return (
    <div className="login-page">
      <div className="login-story">
        <div className="brand light">
          <div className="brand-mark">
            <Layers3 size={24} />
          </div>
          <span>
            <strong>研证</strong>
            <small>ResearchTrace</small>
          </span>
        </div>
        <div>
          <h1>每个结论，都能回到原文的科研智能体。</h1>
          <p>导入论文，提出问题；回答逐句标出处、逐句经过核对，换了版本也知道哪些结论需要重审。</p>
          <div className="login-evidence">
            <div>
              <FileText size={18} />
              <span>具体论文版本与原文位置</span>
            </div>
            <span className="evidence-connector" />
            <div>
              <Search size={18} />
              <span>检索、比对与独立复核</span>
            </div>
            <span className="evidence-connector" />
            <div>
              <ShieldCheck size={18} />
              <span>可点击核验的研究结论</span>
            </div>
          </div>
        </div>
        <small>不编造来源；查不到就说证据不足，不把“没找到”写成“首次”。</small>
      </div>
      <form className="login-form" onSubmit={(e) => void submit(e)}>
        <FlaskConical size={30} strokeWidth={1.4} />
        <h2>进入研究工作区</h2>
        <p>使用评审或管理员访问码。模型密钥只保存在服务器。</p>
        <label htmlFor="access-code">
          访问码
          <input
            id="access-code"
            type="password"
            autoFocus
            autoComplete="current-password"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
            placeholder="输入访问码"
          />
        </label>
        {error && <ErrorBox error={error} />}
        <button className="primary-button" disabled={loading || !code}>
          {loading ? <Busy /> : '进入工作台'}
          <ArrowRight size={16} />
        </button>
        <div className="login-help">
          <CircleHelp size={14} />
          <span>访问码由部署方提供；评审账号进入各自独立的工作区。</span>
        </div>
      </form>
    </div>
  );
}
