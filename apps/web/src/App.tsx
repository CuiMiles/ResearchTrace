/**
 * Application root: session gate, routes and the workbench shell.
 * Pages own their data; shared workspace state lives in app/workspace.tsx.
 */
import { lazy, Suspense, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  BrandMark,
  Clock3,
  FilePenLine,
  GitCompareArrows,
  Home,
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
  Telescope,
  UploadCloud,
  X,
} from './icons';
import { api, errorMessage, shownVersion } from './api';
import type { Session } from './types';
import { Boundary, Busy, ErrorBox } from './ui';
import { ModelConfig } from './ModelConfig';
import { activeRun, RunDetail, RunsDrawer } from './RunPanel';
import { WorkspaceProvider, useWorkspace } from './app/workspace';
import { HomePage } from './features/home/HomePage';
import { DemoPlayer } from './features/home/DemoPlayer';
import { LibraryPage } from './features/library/LibraryPage';
import { ChatPage } from './features/chat/ChatPage';
import { Reader } from './Reader';
import { GuestBanner, GuestEntry } from './features/guest/GuestMode';

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
  name: string;
  icon: typeof Home;
}

const NAVIGATION: NavItem[] = [
  { to: '/', label: '首页', name: '工作台', icon: Home },
  { to: '/library', label: '文献', name: '文献库', icon: Library },
  { to: '/chat', label: '问答', name: '证据问答', icon: MessagesSquare },
  { to: '/compare', label: '比较', name: '版本与比较', icon: GitCompareArrows },
  { to: '/discover', label: '发现', name: '检索与推荐', icon: Telescope },
  { to: '/insights', label: '图谱', name: '图谱与核查', icon: Network },
  { to: '/studio', label: '写作', name: '写作工坊', icon: FilePenLine },
];

const TITLES: [RegExp, string][] = [
  [/^\/library/, '文献'],
  [/^\/read/, '阅读'],
  [/^\/chat/, '问答'],
  [/^\/compare/, '比较'],
  [/^\/discover/, '发现'],
  [/^\/insights/, '图谱'],
  [/^\/studio/, '写作'],
  [/^\/settings\/acceptance/, '验收'],
  [/^\/settings/, '资源'],
  [/^\/runs/, '任务'],
  [/^\/$/, '首页'],
];

const publicDemoEnabled = import.meta.env.VITE_PUBLIC_DEMO === '1';

export default function App() {
  const { pathname } = useLocation();
  const showDemo = publicDemoEnabled && pathname === '/';
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  useEffect(() => {
    let active = true;
    api<Session>('/auth/session')
      .then((existing) => { if (active) setSession((signedIn) => signedIn ?? existing); })
      .catch(() => { /* An anonymous visitor can still watch the demo. */ })
      .finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, []);
  if (publicDemoEnabled && pathname === '/demo') {
    return (
      <main className="public-demo-standalone">
        <NavLink to="/" className="public-demo-back"><ArrowLeft size={16} /> 返回首页</NavLink>
        <DemoPlayer />
      </main>
    );
  }
  if (checking && !showDemo) {
    return (
      <div className="app-loading">
        <BrandMark size={36} />
      </div>
    );
  }
  if (!session) return <Login onLogin={setSession} showDemo={showDemo} />;
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
  const readingId = location.pathname.startsWith('/read')
    ? decodeURIComponent(location.pathname.split('/')[2] ?? '') || lastRead
    : null;
  const readingVersion = readingId ? ws.versions.find((v) => v.id === readingId) : undefined;
  const [configNoticeHidden, setConfigNoticeHidden] = useState(() => {
    try {
      return sessionStorage.getItem('rt-hide-config-notice') === '1';
    } catch {
      return false;
    }
  });
  useEffect(() => setMobileNav(false), [location.pathname]);

  return (
    <ModelConfig.Provider value={ws.capability}>
      <div
        className={`app-shell ${reading ? 'reading' : ''}`}
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
          <NavLink className="brand" to="/" aria-label="研证">
            <BrandMark />
          </NavLink>
          <button className="rail-add" aria-label="导入论文" title="导入论文" disabled={ws.uploading} onClick={ws.openUpload}>
            {ws.uploading ? <Busy>{''}</Busy> : <Plus size={18} />}
          </button>
          <nav aria-label="主导航">
            {NAVIGATION.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.to === '/'} aria-label={item.name} title={item.name}>
                <item.icon size={20} />
                <span>{item.label}</span>
              </NavLink>
            ))}
            {lastRead && ws.versions.some((v) => v.id === lastRead) && (
              <NavLink to={`/read/${lastRead}`} aria-label="继续阅读" title="继续阅读">
                <BookOpen size={20} />
                <span>阅读</span>
              </NavLink>
            )}
          </nav>
          <div className="sidebar-bottom">
            <button className="task-button" aria-label="任务" title="任务" onClick={() => setDrawer(true)}>
              <Clock3 size={20} />
              <span>任务</span>
              {working > 0 && <b>{working}</b>}
            </button>
            {ws.session.role === 'admin' && (
              <NavLink to="/settings/acceptance" aria-label="验收与截图" title="验收与截图">
                <ListChecks size={20} />
                <span>验收</span>
              </NavLink>
            )}
            {ws.session.role !== 'guest' && (
              <NavLink to="/settings" end aria-label="资源与配额" title="资源与配额">
                <Settings2 size={20} />
                <span>资源</span>
              </NavLink>
            )}
            <button aria-label="退出工作区" title="退出工作区" onClick={() => void ws.logout()}>
              <LogOut size={20} />
              <span>退出</span>
            </button>
          </div>
        </aside>
        <div className="app-main">
          <header className={`topbar ${readingVersion || ws.session.role === 'guest' ? '' : 'plain'}`}>
            <div className="breadcrumbs">
              <button
                className="icon-button mobile-only"
                aria-label="展开主导航"
                onClick={() => setMobileNav(!mobileNav)}
              >
                <Menu size={18} />
              </button>
              {readingVersion ? (
                <>
                  <NavLink to="/library" className="breadcrumb-link" aria-label="文献库" title="文献库">
                    <ArrowLeft size={16} />
                  </NavLink>
                  <strong className="truncate paper-crumb" title={readingVersion.title}>
                    {readingVersion.title || readingVersion.filename}
                  </strong>
                  {versionTag(readingVersion.label) && <span className="crumb-chip">{versionTag(readingVersion.label)}</span>}
                  {readingVersion.page_count > 0 && <span className="crumb-meta">{readingVersion.page_count} 页</span>}
                </>
              ) : (
                <strong className="truncate">{title}</strong>
              )}
            </div>
            <GuestBanner
              role={ws.session.role}
              runs={ws.runs.filter((r) => !activeRun(r)).length}
              onSignIn={() => void ws.logout()}
            />
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
          {ws.capability && !ws.capability.model_configured && !configNoticeHidden && (
            <div className="notice missing-config" role="status">
              <span>AI 未配置</span>
              <button
                className="icon-button"
                aria-label="关闭提示"
                onClick={() => {
                  setConfigNoticeHidden(true);
                  try {
                    sessionStorage.setItem('rt-hide-config-notice', '1');
                  } catch {
                    /* per-tab convenience only */
                  }
                }}
              >
                <X size={15} />
              </button>
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
            <h2>导入 PDF</h2>
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
            引用图谱
          </button>
          <button className={tab === 'audit' ? 'active' : ''} onClick={() => setTab('audit')}>
            <ShieldCheck size={16} />
            Future Work
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
      <RunDetail runId={runId} showQuestion onEvidence={(e) => void ws.openEvidence(e)} onUpdate={() => void ws.refresh()} />
    </div>
  );
}

function Login({ onLogin, showDemo }: { onLogin: (s: Session) => void; showDemo: boolean }) {
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
    <div className={showDemo ? 'login-page has-demo' : 'login-page'}>
      {showDemo ? <DemoPlayer /> : <LoginScene />}
      <main className="login-panel">
        <div className="login-mark">
          <BrandMark size={40} />
          <span>ResearchTrace</span>
        </div>
        <h1>研证</h1>
        <ul className="login-keywords" aria-label="核心能力">
          <li><ScanLine />溯源</li>
          <li><GitCompareArrows size={16} />版本</li>
          <li><Network size={16} />图谱</li>
          <li><ShieldCheck size={16} />核验</li>
        </ul>
        <form className="login-form" onSubmit={(e) => void submit(e)}>
          <label className="sr-only" htmlFor="access-code">访问码</label>
          <input
            id="access-code"
            type="password"
            autoFocus={!showDemo}
            autoComplete="current-password"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
            placeholder={showDemo ? '评审访问码' : '访问码'}
          />
          <button className="primary-button" aria-label="进入工作台" disabled={loading || !code}>
            {loading ? <Busy>{''}</Busy> : <ArrowRight size={18} />}
          </button>
        </form>
        {error && <ErrorBox error={error} />}
        <GuestEntry onLogin={onLogin} />
      </main>
    </div>
  );
}

function ScanLine() {
  return <Search size={16} />;
}

/** A page, one highlighted line, and the answer that cites it. Drawn, not imported. */
function LoginScene() {
  const lines = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
  return (
    <svg className="login-scene" viewBox="0 0 760 760" preserveAspectRatio="xMidYMid slice" aria-hidden>
      <g className="scene-page back" transform="translate(250 60) rotate(5)">
        <rect width="360" height="470" rx="6" />
      </g>
      <g className="scene-page" transform="translate(130 110)">
        <rect width="380" height="500" rx="6" />
        <rect className="bar strong" x="36" y="40" width="220" height="12" />
        <rect className="bar" x="36" y="62" width="130" height="7" />
        {lines.map((i) => (
          <rect key={i} className={i === 5 ? 'bar mark' : 'bar'} x="36" y={104 + i * 28} width={i === 5 ? 308 : i % 4 === 3 ? 214 : 308} height={i === 5 ? 14 : 7} />
        ))}
      </g>
      <path className="scene-link" d="M474 359 C 560 359, 540 520, 600 520" />
      <circle className="scene-dot" cx="474" cy="359" r="5" />
      <g className="scene-card" transform="translate(420 490)">
        <rect width="290" height="140" rx="8" />
        <rect className="chip" x="22" y="22" width="34" height="20" rx="3" />
        <text x="39" y="36.5" textAnchor="middle">1</text>
        <rect className="bar light" x="68" y="28" width="150" height="8" />
        <rect className="bar" x="22" y="62" width="246" height="7" />
        <rect className="bar" x="22" y="82" width="246" height="7" />
        <rect className="bar" x="22" y="102" width="150" height="7" />
      </g>
      <g className="scene-graph">
        <path d="M600 130 L680 200 L610 280 M680 200 L730 120 M600 130 L730 120" />
        <circle cx="600" cy="130" r="9" /><circle className="on" cx="680" cy="200" r="13" />
        <circle cx="610" cy="280" r="7" /><circle cx="730" cy="120" r="6" />
      </g>
    </svg>
  );
}

function versionTag(label?: string | null) {
  const shown = shownVersion(label);
  return shown.length <= 12 ? shown : '';
}
