import { useEffect, useRef, useState } from 'react';
import { api, errorMessage, key } from '../api';
import { startPolling } from '../app/poll';
import type { Evidence, Run } from '../types';

interface Context { block_id: string; version_id: string; parse_id: string; page_index: number; bbox: number[]; quote: string; section: string; count: number; }
interface Entry { id: string; marker: string; text: string; citation_count: number; sections: Record<string, number>; contexts: Context[];
  classification: { status: string; label: string }; }
interface Analysis { id?: string; status: string; version_id: string; parse_id: string; active_snapshot?: boolean;
  reference_count?: number; scope?: string; ranking_rule?: string; references: Entry[]; }
interface Batch { id: string; status: string; items: { ref_id: string; status: string; parse_status: string | null;
  result: { reason?: string; fulltext_status?: string; version_id?: string } }[]; counts: Record<string, number>; notice: string; }
const labels: Record<string, string> = { method_dependency: '方法依赖', experimental_comparison: '实验对比', background: '背景', uncertain: '不确定' };
const statuses: Record<string, string> = { queued: '排队中', running: '执行中', waiting_children: '等待子任务', completed: '完成', partial: '部分完成', failed: '失败', cancelled: '已取消',
  pending: '待下载', resolving: '检索中', importing: '下载中', downloaded: 'PDF 已入库', metadata_only: '仅元数据', needs_selection: '需手动选择', unknown: '操作结果未知' };

/** Render next to Reader in App.tsx; parseId pins the selected historical snapshot. */
export function ReferenceTools({ versionId, parseId, onEvidence, onImported }: {
  versionId: string; parseId?: string; onEvidence?: (e: Evidence) => void; onImported?: () => void;
}) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [topN, setTopN] = useState(5);
  const [runId, setRunId] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState('');
  const [batch, setBatch] = useState<Batch | null>(null);
  const [runError, setRunError] = useState('');
  const actionKeys = useRef<Record<string, string>>({});
  const batchId = batch?.id;
  const query = parseId ? `?parse_id=${encodeURIComponent(parseId)}` : '';
  useEffect(() => {
    let active = true;
    setAnalysis(null); setBatch(null); setRunId(null); setRunStatus(''); setError(''); actionKeys.current = {};
    void api<Analysis>(`/documents/${encodeURIComponent(versionId)}/reference-analysis${query}`)
      .then((data) => { if (active) setAnalysis(data); }).catch((e) => { if (active) setError(errorMessage(e)); });
    return () => { active = false; };
  }, [versionId, query]);
  useEffect(() => {
    if (!runId && !batchId) return;
    let active = true;
    async function poll() {
      try {
        if (runId) {
          const run = await api<Run>(`/runs/${runId}`);
          if (!active) return;
          setRunStatus(run.status); setRunError(run.error || String(run.result?.reason || ''));
          if (!['queued', 'running', 'waiting_children'].includes(run.status)) {
            const data = await api<Analysis>(`/documents/${encodeURIComponent(versionId)}/reference-analysis${query}`);
            if (!active) return;
            setAnalysis(data); setRunId(null);
          }
        }
        if (batchId) {
          const data = await api<Batch>(`/reference-downloads/${batchId}`);
          if (!active) return;
          setBatch(data);
          if (['completed', 'partial'].includes(data.status)) onImported?.();
        }
      } catch (e) { if (active) setError(errorMessage(e)); }
    }
    const stop = startPolling(async () => { await poll(); return 3000; });
    return () => { active = false; stop(); };
  }, [runId, batchId, versionId, query, onImported]);
  async function perform(action: string) {
    setBusy(true); setError('');
    try {
      if (action === 'analyze') {
        setAnalysis(await api(`/documents/${encodeURIComponent(versionId)}/reference-analysis`, parseId ? { parse_id: parseId } : {}));
      } else if (action === 'classify' && analysis?.id) {
        const idempotency = actionKeys.current.classify ??= key();
        const run = await api<{ id: string; status: string }>(`/reference-analyses/${analysis.id}/classify`, { idempotency_key: idempotency });
        setRunId(run.id); setRunStatus(run.status); setRunError('');
      } else if ((action === 'all' || action === 'top') && analysis?.id) {
        const name = `${action}:${topN}`;
        const idempotency = actionKeys.current[name] ??= key();
        const run = await api<{ id: string; status: string }>(`/reference-analyses/${analysis.id}/downloads`,
          { mode: action, top_n: topN, max_items: 20, index_dense: false, idempotency_key: idempotency });
        setBatch({ id: run.id, status: run.status, items: [], counts: {}, notice: '批次已保存，按顺序核验来源并下载。' });
      } else if ((action === 'cancel' || action === 'resume') && batch) {
        setBatch(await api(`/reference-downloads/${batch.id}/${action}`, {}));
      }
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  const downloading = batch && ['queued', 'running', 'waiting_children'].includes(batch.status);
  return <details className="reference-tools" style={{ margin: 16, padding: 16, border: '1px solid #d5dfeb', borderRadius: 10 }}>
    <summary>参考文献重要性与批量下载</summary>
    <p>统计正文实际引用次数及所在章节。按次数与章节覆盖排序，不能代表论文质量；分类由 Lite 辅助判断。</p>
    {error && <p role="alert">{error}</p>}
    {analysis?.active_snapshot === false && <p role="status">当前展示历史解析快照 {analysis.parse_id}，未混用最新解析。</p>}
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBlock: 12 }}>
      <button disabled={busy} onClick={() => void perform('analyze')}>{busy ? '处理中…' : analysis?.id ? '查看已保存统计' : '分析正文引用'}</button>
      <button disabled={busy || !analysis?.id || !analysis.references.length || !!runId} onClick={() => void perform('classify')}>Lite 分类（消耗轻量调用）</button>
      <label>前 N 篇 <input type="number" min={1} max={20} value={topN} style={{ width: 70 }}
        onChange={(e) => setTopN(Math.max(1, Math.min(20, Number(e.target.value) || 1)))} /></label>
      <button disabled={busy || !analysis?.id || !analysis.references.length || !!downloading} onClick={() => void perform('top')}>下载最常引用的 {topN} 篇</button>
      <button disabled={busy || !analysis?.id || !analysis.references.length || !!downloading} onClick={() => void perform('all')}>下载全部（每批最多 20 篇）</button>
    </div>
    {runStatus && <p role="status">分类任务：{statuses[runStatus] || runStatus} {runError}</p>}
    {batch && <section aria-label="参考文献下载状态">
      <p role="status">下载任务：{statuses[batch.status] || batch.status} · {batch.id}</p><p>{batch.notice}</p>
      {downloading && <button disabled={busy} onClick={() => void perform('cancel')}>取消下载</button>}
      {['cancelled', 'partial', 'failed'].includes(batch.status) && <button disabled={busy} onClick={() => void perform('resume')}>恢复尚未发送的项目</button>}
      <ul>{batch.items.map((item) => <li key={item.ref_id}>{statuses[item.status] || item.status}
        {item.parse_status && ` · 解析：${statuses[item.parse_status] || item.parse_status}`}
        {item.result?.reason || item.result?.fulltext_status ? ` · ${item.result.reason || item.result.fulltext_status}` : ''}
      </li>)}</ul>
    </section>}
    {analysis?.status === 'not_run' && <p>此解析快照尚未分析。</p>}
    {analysis?.id && <><p>快照 {analysis.parse_id} · 共 {analysis.reference_count} 条参考文献</p><p>{analysis.scope}</p><p>{analysis.ranking_rule}</p>
      <div style={{ maxHeight: 480, overflow: 'auto' }}>
        {analysis.references.map((entry) => <details key={entry.id} style={{ marginBlock: 8, overflowWrap: 'anywhere' }}>
          <summary>[{entry.marker || '?'}] 正文引用 {entry.citation_count} 次 · {Object.keys(entry.sections).length} 个章节 · {labels[entry.classification.label]}{entry.classification.status === 'model_assisted' ? '（模型辅助，待核验）' : '（未分类）'}<br />{entry.text}</summary>
          <p>{Object.entries(entry.sections).map(([section, count]) => `${section}：${count} 次`).join('；') || '未找到正文数字引用，不代表不重要。'}</p>
          {entry.contexts.map((context) => <div key={context.block_id}><p>{context.section} · 第 {context.page_index + 1} 页 · {context.count} 次</p>
            <blockquote>{context.quote}</blockquote>
            {onEvidence && <button onClick={() => onEvidence({ ...context, status: 'located' })}>查看正文原文</button>}
          </div>)}
        </details>)}
      </div>
    </>}
  </details>;
}
