import { useEffect, useRef, useState } from 'react';
import { api, errorMessage, key } from '../api';
import type { Change, Version } from '../types';

type ChoiceVersion = Pick<Version, 'id' | 'title' | 'label' | 'filename' | 'status'> & {
  version_number: number | null; is_current: boolean; retrieval_excluded: boolean;
};
interface Choices {
  incoming: ChoiceVersion; versions: ChoiceVersion[]; work_id: string;
  newer_version_id: string | null; requires_choice: boolean; notice: string; version_notice: string;
}
interface Props {
  pendingIds: string[];
  versions: Version[];
  onDismiss: (id: string) => void;
  onResolved: () => Promise<void>;
}

/** Polls only uploaded versions: identity matching completes asynchronously. */
export function VersionChoice({ pendingIds, versions, onDismiss, onResolved }: Props) {
  const [choices, setChoices] = useState<Choices | null>(null);
  const [peerId, setPeerId] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const [diff, setDiff] = useState<{ counts: Record<string, number>; changes: Change[]; notice: string } | null>(null);
  const [loadingDiff, setLoadingDiff] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const requestKeys = useRef<Record<string, string>>({});
  const incomingId = pendingIds.find((id) => versions.some((v) => v.id === id && ['ready', 'partial'].includes(v.status)));
  useEffect(() => {
    let disposed = false;
    setChoices(null); setDiff(null); setError('');
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
  if (!choices) return error ? <div role="alert">版本选择未载入：{error} <button onClick={() => setRetry((n) => n + 1)}>重试版本识别</button></div> : null;
  const newer = choices.versions.find((v) => v.id === choices.newer_version_id);
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
  return <dialog ref={dialog} aria-labelledby="version-choice-title" onCancel={(e) => e.preventDefault()}
    style={{ width: 'min(760px, calc(100vw - 32px))', maxHeight: '85vh', overflow: 'auto', padding: 24,
      border: '1px solid #b8c6d6', borderRadius: 14, color: '#172b4d', background: 'white' }}>
    <h2 id="version-choice-title">检测到同一论文的不同版本</h2>
    <p>本次上传：{choices.incoming.title} · {choices.incoming.label}（{choices.incoming.filename}）</p>
    <label>库中版本 <select value={peerId} disabled={busy} onChange={(e) => { setPeerId(e.target.value); setDiff(null); }}>
      {choices.versions.filter((v) => v.id !== choices.incoming.id).map((v) =>
        <option key={v.id} value={v.id}>{v.label} · {v.filename}{v.is_current ? ' · 当前版本' : ''}</option>)}
    </select></label>
    <p>{choices.version_notice || choices.notice}</p>
    <p>“保留较新”或“用本次替换”会将其他版本排除出新检索；原 PDF 和历史引用仍可阅读。“两个都保留”恢复此作品所有版本参与检索。</p>
    {!newer && <p role="status">版本先后尚无可靠依据，不按上传时间或文件名猜测。</p>}
    {error && <p role="alert">{error}</p>}
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBlock: 16 }}>
      <button disabled={busy || !newer} onClick={() => void resolve('keep_newer')}>
        保留较新版本{newer ? ` ${newer.label}（推荐）` : '（顺序未知）'}
      </button>
      <button disabled={busy} onClick={() => void resolve('both')}>两个都保留</button>
      <button disabled={busy} onClick={() => void resolve('replace')}>用本次版本替换</button>
      <button disabled={busy || loadingDiff} onClick={() => void compare()}>{loadingDiff ? '正在比较…' : '查看差异'}</button>
      <button disabled={busy} onClick={() => { dialog.current?.close(); onDismiss(choices.incoming.id); }}>稍后选择</button>
    </div>
    {diff && <section aria-label="真实版本差异"><p>{diff.notice}</p>
      <p>{Object.entries(diff.counts).map(([name, count]) => `${name}: ${count}`).join(' · ')}</p>
      {diff.changes.slice(0, 50).map((change, i) => <details key={i}>
        <summary>{change.kind} · {change.before ? `原版本第 ${change.before.page_index + 1} 页` : ''} → {change.after ? `本次第 ${change.after.page_index + 1} 页` : ''}</summary>
        {change.before && <blockquote style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{change.before.text}</blockquote>}
        {change.after && <blockquote style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{change.after.text}</blockquote>}
      </details>)}
      {diff.changes.length > 50 && <p>共 {diff.changes.length} 项，弹窗展示前 50 项；完整比较请进入“版本与比较”。</p>}
    </section>}
  </dialog>;
}
