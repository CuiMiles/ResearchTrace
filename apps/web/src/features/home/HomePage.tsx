/** Home: ask the library, see what it holds, get back to work. */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, FilePenLine, GitCompareArrows, Network, Telescope, UploadCloud } from '../../icons';
import { date } from '../../api';
import { useWorkspace } from '../../app/workspace';
import { runTitle } from '../../RunPanel';
import { Badge } from '../../ui';

export function HomePage() {
  const ws = useWorkspace();
  const navigate = useNavigate();
  const [question, setQuestion] = useState('');
  const ready = ws.versions.filter((v) => v.status === 'ready');
  const pages = ws.versions.reduce((sum, v) => sum + (v.parsed_pages || 0), 0);
  const asked = ws.runs.filter((r) => ['qa', 'agent'].includes(r.kind));

  function ask() {
    if (!question.trim()) return;
    navigate('/chat', { state: { question: question.trim(), versionIds: ready.slice(0, 20).map((v) => v.id) } });
  }

  const actions = [
    { label: '导入', icon: UploadCloud, run: ws.openUpload },
    { label: '比较', icon: GitCompareArrows, run: () => navigate('/compare') },
    { label: '发现', icon: Telescope, run: () => navigate('/discover') },
    { label: '图谱', icon: Network, run: () => navigate('/insights') },
    { label: '写作', icon: FilePenLine, run: () => navigate('/studio') },
  ];

  return (
    <div className="page-content home">
      <form className="ask" onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <input aria-label="向文献库提问" value={question} placeholder="问你的文献库" onChange={(e) => setQuestion(e.target.value)} />
        <button aria-label="提问" disabled={!question.trim() || !ready.length}><ArrowRight size={20} /></button>
      </form>

      <div className="home-band">
        <dl className="stats">
          <div><dd>{ws.versions.length}</dd><dt>论文</dt></div>
          <div><dd>{pages.toLocaleString()}</dd><dt>页</dt></div>
          <div><dd>{asked.length}</dd><dt>问答</dt></div>
        </dl>
        <div className="quick" role="group" aria-label="快捷入口">
          {actions.map((a) => (
            <button key={a.label} onClick={a.run}><a.icon size={20} /><span>{a.label}</span></button>
          ))}
        </div>
      </div>

      <div className="home-lists">
        <section>
          <h2>最近文献</h2>
          {ws.versions.slice(0, 7).map((v) => (
            <button className="line-item" key={v.id} onClick={() => ws.openDocument(v.id)}>
              <strong>{v.title}</strong>
              <span>{v.parsed_pages < v.page_count ? `${v.parsed_pages}/${v.page_count}` : v.page_count} 页</span>
            </button>
          ))}
          {!ws.versions.length && <button className="line-item" onClick={ws.openUpload}><strong>导入第一篇论文</strong><span><UploadCloud size={16} /></span></button>}
        </section>
        <section>
          <h2>最近问答</h2>
          {asked.slice(0, 7).map((run) => (
            <button className="line-item" key={run.id} onClick={() => navigate(`/runs/${run.id}`)}>
              <strong>{runTitle(run)}</strong>
              {run.status === 'completed' ? <span>{date(run.created).slice(5, 10)}</span> : <Badge status={run.status} />}
            </button>
          ))}
          {!asked.length && <p className="quiet">暂无</p>}
        </section>
      </div>
    </div>
  );
}
