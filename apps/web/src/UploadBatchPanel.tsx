import { useEffect, useRef, useState } from 'react';
import { endpoint, errorMessage } from './api';
import './upload-batch.css';

type BatchItem = {
  id: string;
  filename: string;
  status: string;
  run_id: string | null;
  owns_run: boolean;
  duplicate: boolean;
  error: string | null;
};

type UploadBatch = {
  batch_id: string;
  status: string;
  items: BatchItem[];
  counts: Record<string, number>;
  errors: { item_id: string; filename: string; error: string }[];
};

const labels: Record<string, string> = {
  uploading: '正在接收', active: '正在处理', waiting_batch: '等待放行',
  queued: '已入队', running: '正在解析', completed: '已完成',
  failed: '失败', partial: '部分完成', cancelled: '已取消',
};
const pendingStates = new Set(['uploading', 'waiting_batch', 'queued', 'running']);
const cancelStates = new Set([...pendingStates, 'failed', 'partial']);
const resumeStates = new Set(['failed', 'partial', 'cancelled']);
const canResume = (item: BatchItem) => resumeStates.has(item.status) && Boolean(item.run_id) && (item.owns_run || item.duplicate);

async function requestBatch(path: string, signal: AbortSignal, itemIds?: string[]) {
  const response = await fetch(endpoint(path), {
    method: itemIds === undefined ? 'GET' : 'POST',
    credentials: 'same-origin', signal,
    headers: itemIds === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: itemIds === undefined ? undefined : JSON.stringify({ item_ids: itemIds }),
  });
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') message = body.detail;
    } catch { /* Retain the HTTP status when no JSON error is available. */ }
    throw new Error(message);
  }
  const batch = await response.json() as UploadBatch;
  if (!batch.batch_id || !Array.isArray(batch.items)) throw new Error('批次状态格式无效，请稍后重试');
  return batch;
}

export function UploadBatchPanel({ batchId }: { batchId: string | null }) {
  const [batch, setBatch] = useState<UploadBatch | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pollError, setPollError] = useState('');
  const [actionError, setActionError] = useState('');
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const sequence = useRef(0);
  const actionController = useRef<AbortController | null>(null);
  const acting = useRef(false);

  useEffect(() => {
    const current = ++generation.current;
    let live = true;
    let fetching = false;
    let pollController: AbortController | null = null;
    acting.current = false;
    setBatch(null);
    setSelected(new Set());
    setPollError('');
    setActionError('');
    setBusy(false);
    if (!batchId) return;
    const refresh = async () => {
      if (fetching || acting.current) return;
      fetching = true;
      const request = ++sequence.current;
      pollController = new AbortController();
      try {
        const next = await requestBatch(`/batches/${encodeURIComponent(batchId)}`, pollController.signal);
        if (live && current === generation.current && request === sequence.current) {
          setBatch(next);
          setPollError('');
          setSelected(previous => new Set([...previous].filter(id => next.items.some(item => item.id === id))));
        }
      } catch (error) {
        if (live && !pollController.signal.aborted && request === sequence.current) setPollError(errorMessage(error));
      } finally {
        fetching = false;
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => {
      live = false;
      window.clearInterval(timer);
      pollController?.abort();
      actionController.current?.abort();
    };
  }, [batchId]);

  const visible = batch?.batch_id === batchId ? batch : null;
  const selectedItems = visible?.items.filter(item => selected.has(item.id)) ?? [];
  const cancellable = selectedItems.filter(item => cancelStates.has(item.status));
  const resumable = selectedItems.filter(canResume);
  const selectable = visible?.items.filter(item => cancelStates.has(item.status) || canResume(item)) ?? [];
  const counts = visible?.counts ?? {};
  const remaining = [...pendingStates].reduce((sum, state) => sum + (counts[state] ?? 0), 0);
  const holding = counts.waiting_batch ?? 0;
  const allSelected = selectable.length > 0 && selectable.every(item => selected.has(item.id));

  async function change(action: 'cancel' | 'resume') {
    const items = action === 'cancel' ? cancellable : resumable;
    if (!batchId || acting.current || !items.length) return;
    const current = generation.current;
    acting.current = true;
    ++sequence.current; // A poll started before this action cannot replace its result.
    setBusy(true);
    setActionError('');
    const controller = new AbortController();
    actionController.current = controller;
    try {
      const next = await requestBatch(`/batches/${encodeURIComponent(batchId)}/${action}`, controller.signal, items.map(item => item.id));
      if (current === generation.current && !controller.signal.aborted) {
        setBatch(next);
        setSelected(new Set());
        setPollError('');
      }
    } catch (error) {
      if (current === generation.current && !controller.signal.aborted) setActionError(errorMessage(error));
    } finally {
      if (current === generation.current) {
        acting.current = false;
        setBusy(false);
      }
    }
  }

  function toggle(id: string) {
    setSelected(previous => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  if (!batchId) return null;
  return <section className="upload-batch-panel" aria-label="批量导入进度">
    <div className="upload-batch-heading">
      <h3>导入</h3>
      <span className={`upload-batch-status state-${visible?.status ?? 'loading'}`}>
        {visible ? labels[visible.status] ?? visible.status : '载入状态'}
      </span>
    </div>
    <p className="upload-batch-summary" role="status">
      {visible ? `${visible.items.length} 份 · 完成 ${counts.completed ?? 0} · 处理中 ${remaining} · 等待 ${holding}` : '载入中'}
    </p>
    {visible && <>
      <p className="upload-batch-outcomes">失败 {counts.failed ?? 0} · 部分完成 {counts.partial ?? 0} · 已取消 {counts.cancelled ?? 0}</p>
      
    </>}
    {pollError && <p className="upload-batch-error" role="alert">更新失败：{pollError}</p>}
    {actionError && <p className="upload-batch-error" role="alert">操作失败：{actionError}</p>}
    {visible && <>
      <div className="upload-batch-actions">
        <label><input type="checkbox" aria-label="选择所有可操作文件" checked={allSelected} disabled={busy || !selectable.length}
          onChange={() => setSelected(allSelected ? new Set() : new Set(selectable.map(item => item.id)))}/>全选</label>
        <span>已选 {selectedItems.length}</span>
        <button type="button" disabled={busy || !cancellable.length} onClick={() => void change('cancel')}>取消 ({cancellable.length})</button>
        <button type="button" disabled={busy || !resumable.length} onClick={() => void change('resume')}>恢复 ({resumable.length})</button>
        {selectedItems.length > 0 && <button type="button" disabled={busy} onClick={() => setSelected(new Set())}>清除</button>}
      </div>
      <ul className="upload-batch-files" aria-label="每文件导入状态" aria-busy={busy}>
        {visible.items.map(item => <li key={item.id} className="upload-batch-file">
          <input type="checkbox" aria-label={`选择 ${item.filename}`} checked={selected.has(item.id)}
            disabled={busy || !(cancelStates.has(item.status) || canResume(item))} onChange={() => toggle(item.id)}/>
          <div className="upload-batch-filename"><span title={item.filename}>{item.filename}</span>
            {item.duplicate && <small>已存在</small>}
          </div>
          <span className={`upload-batch-status state-${item.status}`}>{labels[item.status] ?? item.status}</span>
          {item.error && <p className="upload-batch-file-error">{item.error}</p>}
          {item.status === 'failed' && !item.run_id && <p className="upload-batch-note upload-batch-file-note">校验未通过</p>}
          {item.status === 'partial' && <p className="upload-batch-note upload-batch-file-note">可恢复</p>}
        </li>)}
      </ul>
    </>}
  </section>;
}

export default UploadBatchPanel;
