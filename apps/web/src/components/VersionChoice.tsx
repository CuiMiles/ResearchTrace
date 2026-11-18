import { useEffect, useRef, useState } from 'react';
import { api, errorMessage, key, parseObject } from '../api';
import { startPolling } from '../app/poll';
import type { Change, Version } from '../types';
import { Busy } from '../ui';
import { ArrowLeft, ChevronDown, FileText, Sparkles, X } from '../icons';
import '../styles/version-choice.css';

type ChoiceVersion = Pick<Version, 'id' | 'title' | 'label' | 'filename' | 'status' | 'page_count'> & {
  version_number: number | null; is_current: boolean; retrieval_excluded: boolean;
};
interface Choices {
  incoming: ChoiceVersion; versions: ChoiceVersion[]; work_id: string;
  newer_version_id: string | null; requires_choice: boolean; notice: string; version_notice: string; basis?: string;
}
interface Props {
  pendingIds: string[];
  versions: Version[];
  onDismiss: (id: string) => void;
  onResolved: () => Promise<void>;
}
interface SummaryRef { id: string; kind: string; old_page?: number; new_page?: number }
interface Summary {
  overall: string; points: { title: string; detail: string; refs: SummaryRef[] }[];
  labels: { older: string; newer: string }; order_known: boolean; considered_changes: number; total_changes: number;
  model?: string; status?: string; reason?: string;
}
type SummaryState = { state: 'idle' } | { state: 'running'; runId: string } | { state: 'done'; summary: Summary; runId: string; finished?: number }
  | { state: 'failed'; message: string; attempt: number };

const KIND: Record<string, string> = { modified: '修改', added: '新增', deleted: '删除', unchanged: '未变' };

/** Shown when an upload turns out to be another version of a paper already in the library. */
export function VersionChoice({ pendingIds, versions, onDismiss, onResolved }: Props) {
  const [choices, setChoices] = useState<Choices | null>(null);
  const [peerId, setPeerId] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const [diff, setDiff] = useState<{ counts: Record<string, number>; changes: Change[] } | null>(null);
  const [loadingDiff, setLoadingDiff] = useState(false);
  const [summary, setSummary] = useState<SummaryState>({ state: 'idle' });
  const [attempt, setAttempt] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const requestKeys = useRef<Record<string, string>>({});
  const incomingId = pendingIds.find((id) => versions.some((v) => v.id === id && ['ready', 'partial'].includes(v.status)));

  useEffect(() => {
    let disposed = false;
    setChoices(null); setDiff(null); setError(''); setSummary({ state: 'idle' });
    if (!incomingId) return;
    void api<Choices>(`/versions/${encodeURIComponent(incomingId)}/choices`).then((result) => {
      if (disposed) return;
      if (!result.requires_choice) { onDismiss(incomingId); return; }
      setPeerId(result.versions.find((v) => v.id !== incomingId && v.is_current)?.id
        ?? result.versions.find((v) => v.id !== incomingId)?.id ?? '');
      setChoices(result);
    }).catch((e) => { if (!disposed) setError(errorMessage(e)); });
    return () => { disposed = true; };
  }, [incomingId, onDismiss, retry]);
  useEffect(() => {
    if (choices && !dialog.current?.open) dialog.current?.showModal();
  }, [choices]);
  // Follow a queued summary until the worker saves it.
  const runningId = summary.state === 'running' ? summary.runId : '';
  useEffect(() => {
    if (!runningId) return;
    let live = true;
    const stop = startPolling(async () => {
      const run = await api<{ status: string; error?: string | null; result?: unknown; updated?: number }>(`/runs/${runningId}`);
      if (!live) return null;
      if (['queued', 'running', 'waiting_children', 'waiting_batch'].includes(run.status)) return 1500;
      const result = parseObject<Summary | null>(run.result, null);
      if (run.status === 'completed' || (run.status === 'partial' && result)) setSummary({ state: 'done', summary: result!, runId: runningId, finished: run.updated });
      else setSummary({ state: 'failed', message: run.error || '总结失败', attempt });
      return null;
    }, 800);
    return () => { live = false; stop(); };
  }, [runningId, attempt]);

  if (!choices) return error ? <div role="alert" className="vc-load-error">版本识别结果没有载入：{error} <button className="text-button" onClick={() => setRetry((n) => n + 1)}>重试</button></div> : null;
  const newer = choices.versions.find((v) => v.id === choices.newer_version_id);
  const peer = choices.versions.find((v) => v.id === peerId);
  const others = choices.versions.filter((v) => v.id !== choices.incoming.id);

  async function resolve(action: 'keep_newer' | 'both' | 'replace') {
    if (!choices) return;
    setBusy(true); setError('');
    const operation = `${choices.incoming.id}:${peerId}:${action}`;
    const idempotency = requestKeys.current[operation] ??= key();
    try {
      await api('/versions/resolve', { incoming_version_id: choices.incoming.id, existing_version_id: peerId,
        work_id: choices.work_id, action, idempotency_key: idempotency });
      dialog.current?.close(); onDismiss(choices.incoming.id); setChoices(null);
      await onResolved();
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  async function compare() {
    if (!choices) return;
    setLoadingDiff(true); setError('');
    try { setDiff(await api('/versions/compare', { left: peerId, right: choices.incoming.id })); }
    catch (e) { setError(errorMessage(e)); }
    finally { setLoadingDiff(false); }
  }
  async function summarize(next = attempt) {
    if (!choices) return;
    setError('');
    try {
      const run = await api<{ id: string }>('/versions/summary', { left: peerId, right: choices.incoming.id, retry: next });
      setAttempt(next);
      setSummary({ state: 'running', runId: run.id });
      if (!diff) void compare();
    } catch (e) { setSummary({ state: 'failed', message: errorMessage(e), attempt: next }); }
  }
  const later = () => { dialog.current?.close(); onDismiss(choices.incoming.id); };

  return <dialog ref={dialog} className="vc-dialog" aria-labelledby="version-choice-title" onCancel={(e) => { e.preventDefault(); later(); }}>
    <header className="vc-head">
      <span className="vc-eyebrow"><Sparkles size={13} />版本</span>
      <h2 id="version-choice-title">发现同一论文的其他版本</h2>
      {choices.basis && <p className="vc-basis">{shortBasis(choices.basis)}</p>}
      <button className="icon-button vc-close" aria-label="稍后决定" onClick={later}><X size={16} /></button>
    </header>

    <div className="vc-pair">
      <VersionCard tag="刚刚上传" version={choices.incoming} newer={newer?.id === choices.incoming.id} />
      <span className="vc-vs" aria-hidden="true"><ArrowLeft size={15} /></span>
      {others.length > 1
        ? <label className="vc-card vc-select"><span className="vc-tag">库中版本</span>
          <select value={peerId} disabled={busy} onChange={(e) => { setPeerId(e.target.value); setDiff(null); setSummary({ state: 'idle' }); }}>
            {others.map((v) => <option key={v.id} value={v.id}>{v.label} · {v.filename}{v.is_current ? ' · 当前' : ''}</option>)}
          </select></label>
        : peer && <VersionCard tag="库中已有" version={peer} newer={newer?.id === peer.id} />}
    </div>

    {newer
      ? <p className="vc-recommend">{newer.id === choices.incoming.id
        ? `建议使用 ${newer.label}`
        : `建议保留 ${newer.label}`}</p>
      : <p className="vc-recommend neutral">无法判断新旧</p>}

    {error && <p role="alert" className="vc-error">{error}</p>}
    <div className="vc-actions">
      <button className="primary-button" disabled={busy || !newer} onClick={() => void resolve('keep_newer')}>
        {newer ? `保留较新的 ${newer.label}（推荐）` : '保留较新版本'}
      </button>
      <button className="small-button" disabled={busy} onClick={() => void resolve('both')}>两个都保留</button>
      <button className="small-button" disabled={busy} onClick={() => void resolve('replace')}>用本次上传替换</button>
      <button className="text-button" disabled={busy} onClick={later}>稍后决定</button>
    </div>
    

    <section className="vc-diff" aria-label="两个版本的差异">
      <div className="vc-diff-head">
        <h3>修订</h3>
        <div className="vc-diff-actions">
          {!diff && <button className="text-button" disabled={loadingDiff} onClick={() => void compare()}>{loadingDiff ? '正在比较…' : '逐段比较'}</button>}
          {summary.state === 'idle' && <button className="small-button vc-ai" onClick={() => void summarize()}><Sparkles size={13} />AI 总结主要修订</button>}
        </div>
      </div>
      {diff && <p className="vc-counts">{(['modified', 'added', 'deleted', 'unchanged'] as const).filter((k) => diff.counts[k] !== undefined)
        .map((k) => <span key={k} className={`vc-chip ${k}`}>{KIND[k]} {diff.counts[k]} 段</span>)}</p>}

      {summary.state === 'running' && <div className="vc-summary pending"><Busy>总结中</Busy></div>}
      {summary.state === 'failed' && <div className="vc-summary failed"><p>{summary.message}</p>
        <button className="text-button" onClick={() => void summarize(summary.attempt + 1)}>重试</button></div>}
      {summary.state === 'done' && <SummaryView summary={summary.summary} finished={summary.finished} />}

      {diff && <details className="vc-changes">
        <summary><ChevronDown size={14} />逐段差异 {diff.changes.length}</summary>
        {diff.changes.slice(0, 50).map((change, i) => <div key={i} className={`vc-change ${change.kind}`}>
          <p className="vc-change-head"><span className={`vc-chip ${change.kind}`}>{KIND[change.kind] ?? change.kind}</span>
            {change.before && <span>库中版本第 {change.before.page_index + 1} 页</span>}
            {change.before && change.after && <span aria-hidden="true">→</span>}
            {change.after && <span>本次上传第 {change.after.page_index + 1} 页</span>}</p>
          {change.before && <blockquote className="before">{change.before.text}</blockquote>}
          {change.after && <blockquote className="after">{change.after.text}</blockquote>}
        </div>)}
        
      </details>}
    </section>
  </dialog>;
}

function shortBasis(basis: string) {
  const match = basis.match(/(首页正文|PDF 元数据)中的 (arXiv|DOI)(?: 编号)? ?都是 ([^（\s]+)/);
  return match ? `${match[2]} ${match[3]} · ${match[1]}` : basis;
}

function VersionCard({ tag, version, newer }: { tag: string; version: ChoiceVersion; newer: boolean }) {
  return <article className={`vc-card ${newer ? 'newer' : ''}`}>
    <span className="vc-tag">{tag}{newer && <b>较新</b>}</span>
    <strong className="vc-label">{version.label}</strong>
    <span className="vc-file"><FileText size={13} />{version.filename}</span>
    <span className="vc-meta">{version.page_count ? `${version.page_count} 页` : ''}{version.is_current ? ' · 当前检索版本' : ''}</span>
  </article>;
}

function SummaryView({ summary, finished }: { summary: Summary; finished?: number }) {
  const { older, newer } = summary.labels;
  const page = (ref: SummaryRef) => [ref.old_page && `${older} 第 ${ref.old_page} 页`, ref.new_page && `${newer} 第 ${ref.new_page} 页`]
    .filter(Boolean).join(' → ');
  if (!summary.points.length) return <div className="vc-summary"><p>{summary.reason || '无实质修订'}</p></div>;
  return <div className="vc-summary">
    <p className="vc-summary-title"><Sparkles size={14} />{summary.order_known ? `从 ${older} 到 ${newer} 的主要修订` : `${older} 与 ${newer} 的主要差异`}</p>
    {summary.overall && <p className="vc-overall">{summary.overall}</p>}
    <ol>{summary.points.map((point, i) => <li key={i}>
      <strong>{point.title}</strong><span>{point.detail}</span>
      <span className="vc-refs">{point.refs.map((ref) => <em key={ref.id} className={`vc-chip ${ref.kind}`}>{KIND[ref.kind] ?? ref.kind} · {page(ref)}</em>)}</span>
    </li>)}</ol>
    <p className="vc-footnote">{finished ? `生成于 ${new Date(finished * 1000).toLocaleString('zh-CN', { hour12: false })}；` : ''}由模型（{summary.model ?? '未知模型'}）只依据两版之间真实的段落差异撰写，每条都标出了对应页码，可在下方逐段差异中核对；共比较 {summary.total_changes} 处差异，其中 {summary.considered_changes} 处实质改动用于总结。</p>
  </div>;
}
