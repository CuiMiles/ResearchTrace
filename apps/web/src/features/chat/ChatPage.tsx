/**
 * Evidence chat. A thread is a sequence of question runs sharing a thread_id;
 * the server reads earlier turns of the same thread so follow-ups such as
 * “其中 Adam 的 β1 是多少？” resolve. One paper uses the single-paper answer
 * path; several papers use the multi-paper analysis path with per-paper quotas.
 */
import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { FileText, MessagesSquare, Plus, Send, X } from '../../icons';
import { api, date, errorMessage, key } from '../../api';
import { useWorkspace } from '../../app/workspace';
import { useModelConfig } from '../../ModelConfig';
import { RunDetail } from '../../RunPanel';
import type { Run } from '../../types';
import { Busy, ErrorBox } from '../../ui';

interface Thread {
  thread_id: string;
  title: string;
  version_ids: string[];
  turns: number;
  updated: number;
}

const SUGGESTIONS = [
  ['作者与机构', '这篇论文的作者依次是谁？分别来自哪些机构？'],
  ['训练配置', '训练使用了什么硬件、多长时间，优化器的超参数是多少？'],
  ['主要结果', '主要实验结果是多少？与当时最好的方法相比提升了多少？'],
  ['架构对比', '比较所选论文的模型架构差异，并说明各自的出处。'],
];

function newThreadId() {
  return 'th-' + key().replace(/-/g, '').slice(0, 20);
}

export function ChatPage() {
  const ws = useWorkspace();
  const model = useModelConfig();
  const navigate = useNavigate();
  const location = useLocation();
  const { threadId } = useParams();
  const [threads, setThreads] = useState<Thread[]>([]);
  const [turns, setTurns] = useState<Run[]>([]);
  const [scope, setScope] = useState<string[]>([]);
  const [question, setQuestion] = useState('');
  const [sending, setSending] = useState(false);
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState('');
  const scroller = useRef<HTMLDivElement>(null);
  const handoff = useRef(false);

  const labelOf = (id: string) => {
    const v = ws.versions.find((x) => x.id === id);
    return v ? `${v.title.slice(0, 40)}${v.title.length > 40 ? '…' : ''} · ${v.label}` : '已删除的版本';
  };

  async function loadThreads() {
    try {
      setThreads(await api<Thread[]>('/chat/threads'));
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  useEffect(() => {
    void loadThreads();
  }, []);

  useEffect(() => {
    if (!threadId) {
      setTurns([]);
      return;
    }
    let live = true;
    api<{ runs: Run[] }>(`/chat/threads/${threadId}`)
      .then((data) => {
        if (!live) return;
        setTurns(data.runs);
        const payload = data.runs[0]?.payload as { version_ids?: string[] } | undefined;
        if (payload?.version_ids) setScope(payload.version_ids);
      })
      .catch((e) => live && setError(errorMessage(e)));
    return () => {
      live = false;
    };
  }, [threadId]);

  // A question handed over from the home page or the library starts a new thread.
  useEffect(() => {
    const state = location.state as { question?: string; versionIds?: string[] } | null;
    if (!state || handoff.current) return;
    handoff.current = true;
    if (state.versionIds?.length) setScope(state.versionIds);
    if (state.question) setQuestion(state.question);
    navigate(location.pathname, { replace: true, state: null });
  }, [location.state]);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' });
  }, [turns.length]);

  async function send(text = question) {
    const content = text.trim();
    if (!content || !scope.length || sending) return;
    setSending(true);
    setError('');
    const thread = threadId ?? newThreadId();
    try {
      const path = scope.length > 1 ? '/agent/runs' : '/qa/runs';
      const run = await api<{ id: string }>(path, {
        question: content,
        version_ids: scope,
        thread_id: thread,
        idempotency_key: key(),
      });
      setQuestion('');
      const created = await api<Run>(`/runs/${run.id}`);
      setTurns((previous) => [...previous, created]);
      if (!threadId) navigate(`/chat/${thread}`);
      void loadThreads();
      void ws.refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSending(false);
    }
  }

  const unavailable = model?.model_configured === false;
  const ready = ws.versions.filter((v) => v.status === 'ready');

  return (
    <div className="chat-layout">
      <aside className="thread-list" aria-label="对话列表">
        <button
          className="primary-button"
          onClick={() => {
            setTurns([]);
            navigate('/chat');
          }}
        >
          <Plus size={15} />
          新对话
        </button>
        {threads.map((t) => (
          <button
            key={t.thread_id}
            className={`thread-item ${t.thread_id === threadId ? 'active' : ''}`}
            onClick={() => navigate(`/chat/${t.thread_id}`)}
          >
            <strong>{t.title}</strong>
            <small>
              {t.turns} 轮 · {t.version_ids.length} 篇 · {date(t.updated)}
            </small>
          </button>
        ))}
        
      </aside>

      <section className="chat-main">
        <div className="chat-scroll" ref={scroller}>
          <div className="chat-column">
            {error && <ErrorBox error={error} onClose={() => setError('')} />}
            {!turns.length && (
              <div className="chat-empty">
                <h1>问答</h1>
                <div className="suggestions">
                  {SUGGESTIONS.map(([label, text]) => (
                    <button key={label} className="suggestion" title={text} onClick={() => setQuestion(text)}>
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {turns.map((run) => (
              <div key={run.id} style={{ display: 'grid', gap: 10 }}>
                <div className="turn-question">{String((run.payload as { question?: string }).question ?? '')}</div>
                <div className="card turn-answer">
                  <RunDetail
                    runId={run.id}
                    onEvidence={(e) => void ws.openEvidence(e)}
                    onUpdate={() => void loadThreads()}
                    versionLabel={labelOf}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        <form
          className="chat-composer"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <div className="scope-chips" aria-label="提问范围">
            {scope.map((id) => (
              <span className="scope-chip" key={id} title={labelOf(id)}>
                <FileText size={12} />
                <span>{labelOf(id)}</span>
                <button
                  type="button"
                  aria-label={`移除 ${labelOf(id)}`}
                  onClick={() => setScope((s) => s.filter((x) => x !== id))}
                >
                  <X size={11} />
                </button>
              </span>
            ))}
            <button type="button" className="scope-chip add" onClick={() => setPicking(true)}>
              <Plus size={12} />
              {scope.length ? '添加论文' : '选择论文'}
            </button>
          </div>
          <textarea
            aria-label="输入问题"
            value={question}
            rows={2}
            placeholder={threadId ? '继续追问' : '提问'}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <div className="composer-row">
            <MessagesSquare size={13} />
            <span>{unavailable ? 'AI 未配置' : scope.length ? `${scope.length} 篇` : ''}</span>
            <button className="primary-button" disabled={unavailable || !scope.length || !question.trim() || sending}>
              {sending ? <Busy /> : <Send size={15} />}
              发送
            </button>
          </div>
        </form>
      </section>

      {picking && (
        <div className="drawer-backdrop" onClick={() => setPicking(false)}>
          <aside className="side-drawer" onClick={(e) => e.stopPropagation()} aria-label="选择论文">
            <div className="section-heading">
              <h2>选择论文</h2>
              <button className="icon-button" aria-label="关闭" onClick={() => setPicking(false)}>
                <X size={17} />
              </button>
            </div>
            
            <div className="picker-list">
              {ready.map((v) => (
                <label key={v.id} className={scope.includes(v.id) ? 'selected' : ''}>
                  <input
                    type="checkbox"
                    checked={scope.includes(v.id)}
                    onChange={() =>
                      setScope((s) => (s.includes(v.id) ? s.filter((x) => x !== v.id) : [...s, v.id].slice(0, 20)))
                    }
                  />
                  <span>
                    {v.title}
                    <small>
                      {v.label} · {v.page_count} 页
                    </small>
                  </span>
                </label>
              ))}
            </div>
            <button className="primary-button" onClick={() => setPicking(false)}>
              完成 {scope.length}
            </button>
          </aside>
        </div>
      )}
    </div>
  );
}
