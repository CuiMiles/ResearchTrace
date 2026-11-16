/**
 * Workbench home: one command bar to ask across the library or start from a
 * file, the main entry paths, and the real recent documents and questions.
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  BookOpen,
  FileChartColumn,
  FileText,
  GitCompareArrows,
  MessagesSquare,
  Network,
  Send,
  UploadCloud,
} from '../../icons';
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
  const questions = ws.runs.filter((r) => ['qa', 'agent'].includes(r.kind)).slice(0, 6);

  function ask() {
    if (!question.trim()) return;
    navigate('/chat', { state: { question: question.trim(), versionIds: ready.slice(0, 20).map((v) => v.id) } });
  }

  return (
    <div className="page-content">
      <section className="home-hero">
        <span className="eyebrow">研证 · 证据优先的科研智能体</span>
        <h1>提出研究问题，得到逐句可核验的回答。</h1>
        <p>
          回答中的每一句都绑定具体论文版本、页码与原文片段，并经过数值、版本与语义复核；
          查不到就明确写“证据不足”。
        </p>
        <div className="command-bar">
          <MessagesSquare size={18} color="var(--faint)" />
          <textarea
            aria-label="向文献库提问"
            rows={1}
            value={question}
            placeholder={
              ready.length
                ? `向文献库中的 ${ready.length} 篇论文提问，例如：这些论文的训练配置有什么不同？`
                : '先导入论文，再在这里提问'
            }
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                ask();
              }
            }}
          />
          <button className="primary-button" disabled={!question.trim() || !ready.length} onClick={ask}>
            <Send size={15} />
            提问
          </button>
        </div>
        <div className="stat-strip">
          <span>
            <b>{ws.versions.length}</b> 篇文献
          </span>
          <span>
            <b>{pages}</b> 页已解析
          </span>
          <span>
            <b>{questions.length}</b> 次近期提问
          </span>
        </div>
      </section>

      <div className="start-paths" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))' }}>
        <button className="start-path" onClick={ws.openUpload}>
          <div className="path-icon blue">
            <UploadCloud size={20} />
          </div>
          <div>
            <h3>导入并阅读论文</h3>
            <p>批量上传、版本识别、逐页解析</p>
          </div>
          <ArrowRight size={16} />
        </button>
        <button className="start-path" onClick={() => navigate('/compare')}>
          <div className="path-icon teal">
            <GitCompareArrows size={20} />
          </div>
          <div>
            <h3>比较论文与版本</h3>
            <p>逐项对照，事实各有出处</p>
          </div>
          <ArrowRight size={16} />
        </button>
        <button className="start-path" onClick={() => navigate('/insights')}>
          <div className="path-icon purple">
            <Network size={20} />
          </div>
          <div>
            <h3>引用图谱与 Future Work</h3>
            <p>核心文献与后续进展核查</p>
          </div>
          <ArrowRight size={16} />
        </button>
        <button className="start-path" onClick={() => navigate('/studio')}>
          <div className="path-icon amber">
            <FileChartColumn size={20} />
          </div>
          <div>
            <h3>写作与绘图</h3>
            <p>CSV 成图、结构图、研究笔记</p>
          </div>
          <ArrowRight size={16} />
        </button>
      </div>

      <div className="home-grid">
        <section className="card home-panel">
          <h2>
            <BookOpen size={16} />
            最近的文献
          </h2>
          {ws.versions.length ? (
            ws.versions.slice(0, 6).map((v) => (
              <button className="list-link" key={v.id} onClick={() => ws.openDocument(v.id)}>
                <FileText size={18} color="var(--brand)" />
                <span>
                  <strong style={{ fontFamily: 'var(--font-paper)' }}>{v.title}</strong>
                  <small>
                    {v.label} · {v.parsed_pages}/{v.page_count || '?'} 页 · {date(v.created)}
                  </small>
                </span>
                <Badge status={v.status} />
              </button>
            ))
          ) : (
            <button className="upload-empty" style={{ width: '100%' }} onClick={ws.openUpload}>
              <UploadCloud size={30} strokeWidth={1.3} />
              <h3>把第一篇论文放进来</h3>
              <p>拖放 PDF 到页面任意位置，或点击选择文件</p>
            </button>
          )}
        </section>
        <section className="card home-panel">
          <h2>
            <MessagesSquare size={16} />
            最近的提问
          </h2>
          {questions.length ? (
            questions.map((run) => (
              <button className="list-link" key={run.id} onClick={() => navigate(`/runs/${run.id}`)}>
                <span>
                  <strong>{runTitle(run)}</strong>
                  <small>{date(run.created)}</small>
                </span>
                <Badge status={run.status} />
              </button>
            ))
          ) : (
            <p className="muted">问题和回答会连同出处、执行记录一起保存在这里。</p>
          )}
        </section>
      </div>
    </div>
  );
}
