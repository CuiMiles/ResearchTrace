/**
 * A single persisted run (question, comparison, audit, translation…):
 * live execution timeline over SSE with polling as the source of truth,
 * cancel/resume at checkpoints, and the validated answer.
 */
import { useEffect, useState } from 'react';
import { CheckCircle2, Clock3, MessageSquare, Play, Square, X } from './icons';
import { api, date, endpoint, errorMessage, parseObject } from './api';
import type { Evidence, Result, Run, Step } from './types';
import { Badge, Busy, Disclosure, Empty, ErrorBox } from './ui';
import { AgentTimeline } from './components/AgentTimeline';
import { AnswerView } from './components/AnswerView';
import { startPolling } from './app/poll';

export const activeRun = (run: Run) =>
  ['queued', 'running', 'waiting_batch', 'waiting_children'].includes(run.status);

export function RunResult({ run, onEvidence }: { run: Run; onEvidence: (e: Evidence) => void }) {
  return <AnswerView run={run} onEvidence={onEvidence} />;
}

function RetrievalSummary({ result }: { result: Result | null }) {
  const retrieval = parseObject<Record<string, unknown>>(result?.retrieval, {});
  if (!result || !Object.keys(retrieval).length) return null;
  const blocks = Array.isArray(retrieval.blocks) ? retrieval.blocks.length : 0;
  const rewrites = Array.isArray(retrieval.rewritten_queries) ? (retrieval.rewritten_queries as string[]) : [];
  return (
    <Disclosure title="检索范围与证据来源">
      <div style={{ display: 'grid', gap: 6, fontSize: 13 }}>
        <span>
          方式：{retrieval.mode === 'hybrid' ? '关键词 + 语义混合检索' : '关键词检索'} · 送入模型的原文段落 {blocks} 段
        </span>
        {rewrites.length > 0 && <span>英文改写查询：{rewrites.join(' · ')}</span>}
        
        <pre className="code-block">
          {JSON.stringify({ retrieval: { ...retrieval, blocks: undefined }, status: result.status }, null, 2)}
        </pre>
      </div>
    </Disclosure>
  );
}

export function RunDetail({
  runId,
  onEvidence,
  onUpdate,
  versionLabel,
}: {
  runId: string;
  onEvidence: (e: Evidence) => void;
  onUpdate?: () => void;
  versionLabel?: (versionId: string) => string;
}) {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState('');
  const [steps, setSteps] = useState<Step[]>([]);

  useEffect(() => {
    let live = true;
    let source: EventSource | null = null;
    let stopPolling: (() => void) | undefined;
    const refresh = async (): Promise<boolean> => {
      try {
        const next = await api<Run>(`/runs/${runId}`);
        if (!live) return false;
        setRun({ ...next, result: parseObject(next.result, null), payload: parseObject(next.payload, {}) });
        setSteps((next.steps ?? []).slice(-200));
        if (!activeRun(next)) {
          source?.close();
          stopPolling?.();
          onUpdate?.();
          return false;
        }
        return true;
      } catch (e) {
        if (live) setError(errorMessage(e));
        return live;
      }
    };
    stopPolling = startPolling(async () => ((await refresh()) ? 2500 : null));
    source = new EventSource(endpoint(`/runs/${runId}/events`), { withCredentials: true });
    const receive = (event: MessageEvent) => {
      try {
        const step = JSON.parse(event.data) as Step;
        if (step.id && live) {
          setSteps((previous) =>
            previous.some((s) => s.id === step.id) ? previous : [...previous, step].slice(-200),
          );
        }
      } catch {
        /* the next status poll restores server truth */
      }
    };
    source.onmessage = receive;
    source.addEventListener('step', receive as EventListener);
    source.addEventListener('done', () => void refresh());
    return () => {
      live = false;
      source?.close();
      stopPolling?.();
    };
  }, [runId]);

  async function change(action: 'cancel' | 'resume') {
    try {
      await api(`/runs/${runId}/${action}`, {});
      const next = await api<Run>(`/runs/${runId}`);
      setRun({ ...next, result: parseObject(next.result, null), payload: parseObject(next.payload, {}) });
      onUpdate?.();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  if (!run) return error ? <ErrorBox error={error} /> : <Busy>载入任务</Busy>;
  const running = activeRun(run);
  return (
    <div className="run-detail">
      {error && <ErrorBox error={error} />}
      <div className="run-actions">
        <Badge status={run.status} />
        {running && (
          <button className="small-button" onClick={() => void change('cancel')}>
            <Square size={12} />
            取消
          </button>
        )}
        {['failed', 'cancelled', 'partial', 'waiting_for_user'].includes(run.status) && (
          <button className="small-button" onClick={() => void change('resume')}>
            <Play size={12} />
            恢复
          </button>
        )}
        {running && <Busy>{run.status === 'queued' ? '排队中' : '运行中'}</Busy>}
      </div>
      <AgentTimeline steps={steps} live={running} />
      {!running && <AnswerView run={run} onEvidence={onEvidence} versionLabel={versionLabel} />}
      {!running && Array.isArray(run.result?.coverage_matrix) && <section className="data-table-wrap" aria-label="后续工作条件对照">
        <h3>后续工作与条件对照</h3>
        <table><thead><tr><th>后续论文</th><th>时间与覆盖</th><th>条件、范围与全文证据</th></tr></thead><tbody>
          {(run.result.coverage_matrix as {version_id:string;title:string;category:string;time_comparison?:{status:string};statements:string[];evidence:Evidence[];notice:string}[]).map(row=><tr key={row.version_id}>
            <td>{row.title}</td><td>{{direct:'直接相关证据',partial:'部分覆盖',insufficient:'当前证据不足'}[row.category]??row.category}<br/><small>{row.time_comparison?.status==='later'?'发表区间晚于来源':'发表先后尚不确定'}</small></td>
            <td>{row.statements.map((text,i)=><p key={i}>{text}</p>)}{row.evidence.map((e,i)=><button key={i} className="text-button" onClick={()=>onEvidence(e)}>查看原文 · 第 {e.page_index+1} 页</button>)}<p className="muted">{row.notice}</p></td>
          </tr>)}
        </tbody></table>
      </section>}
      {!running && <RetrievalSummary result={run.result} />}
    </div>
  );
}

const KIND_LABEL: Record<string, string> = {
  qa: '问答',
  agent: '多篇分析',
  parse: '导入与解析',
  parse_document: '导入与解析',
  reparse: '重新解析',
  translate: '翻译',
  audit: '研究建议核查',
  index: '语义索引',
  card: '文献卡片',
  writing: '写作',
  watch: '追踪检查',
  text_translation:'选段翻译',
  recommendation:'文献推荐',
  reference_classify:'引用功能分类',
  reference_download:'参考文献下载',
  reference_import:'参考文献获取',
};

export function runTitle(run: Run) {
  const payload = parseObject<Record<string, unknown>>(run.payload, {});
  return String(payload.question ?? KIND_LABEL[run.kind] ?? run.kind);
}

export function RunsDrawer({
  runs,
  onClose,
  onSelect,
}: {
  runs: Run[];
  onClose: () => void;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="runs-drawer" onClick={(e) => e.stopPropagation()} aria-label="任务与历史">
        <div className="section-heading">
          <h2>任务</h2>
          <button className="icon-button" aria-label="关闭任务列表" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        
        {!runs.length && <Empty title="暂无任务" />}
        {runs.map((run) => (
          <button className="run-row" key={run.id} onClick={() => onSelect(run.id)}>
            {activeRun(run) ? (
              <Clock3 size={17} />
            ) : run.status === 'completed' ? (
              <CheckCircle2 size={17} />
            ) : (
              <MessageSquare size={17} />
            )}
            <div>
              <strong>{runTitle(run)}</strong>
              <small>
                {KIND_LABEL[run.kind] ?? run.kind} · {date(run.created)}
              </small>
            </div>
            <Badge status={run.status} />
          </button>
        ))}
      </aside>
    </div>
  );
}
