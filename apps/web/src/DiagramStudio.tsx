import { useEffect, useRef, useState } from 'react';
import DOMPurify from 'dompurify';
import Diagram from './Diagram';
import { api, errorMessage, key, parseObject } from './api';
import { Busy, ErrorBox } from './ui';
import { RunDetail } from './RunPanel';
import type { Evidence, Run, Version } from './types';
import './writing-workflows.css';

type Sources = { mermaid: string; dot: string; tikz: string; matplotlib: string };
type Language = keyof Sources;
const labels: Record<Language, string> = { mermaid: 'Mermaid', dot: 'Graphviz DOT', tikz: 'TikZ', matplotlib: 'Matplotlib' };
const extensions: Record<Language, string> = { mermaid: 'mmd', dot: 'dot', tikz: 'tex', matplotlib: 'py' };
function save(text: string, name: string, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement('a'); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export default function DiagramStudio({ versions, onEvidence, onQueued }: {
  versions: Version[]; onEvidence: (e: Evidence) => void; onQueued: () => void;
}) {
  const [question, setQuestion] = useState('');
  const [selected, setSelected] = useState('');
  const [runId, setRunId] = useState<string | null>(null);
  const [sources, setSources] = useState<Sources | null>(null);
  const [language, setLanguage] = useState<Language>('mermaid');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function generate() {
    setBusy(true); setError(''); setSources(null);
    try {
      const run = await api<{ id: string }>('/writing/diagrams', { question, version_ids: selected ? [selected] : [], idempotency_key: key(), context_budget: 24000 });
      setRunId(run.id); onQueued();
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  }
  async function finished() {
    if (!runId) return;
    try {
      const run = await api<Run>(`/runs/${runId}`);
      const result = parseObject<Record<string, unknown>>(run.result, {});
      const next = result.sources as Sources | undefined;
      if (next && Object.values(next).every(value => typeof value === 'string')) setSources(next);
    } catch (reason) { setError(errorMessage(reason)); }
  }
  return <section className="writing-workflow" aria-label="结构图生成工作流">
    <h2>结构图</h2>
    <label>设想<textarea rows={4} maxLength={3000} value={question} onChange={e => setQuestion(e.target.value)} placeholder="模块 / 信息流 / 输入输出" /></label>
    <label>论文<select value={selected} onChange={e => setSelected(e.target.value)}><option value="">不使用论文</option>{versions.map(v => <option key={v.id} value={v.id}>{v.title} · {v.label}</option>)}</select></label>
    
    <button type="button" className="primary-button" disabled={busy || !question.trim()} onClick={() => void generate()}>{busy ? <Busy /> : '生成'}</button>
    {error && <ErrorBox error={error} />}
    {runId && <RunDetail runId={runId} onEvidence={onEvidence} onUpdate={() => void finished()} />}
    {sources ? <>
      <div className="diagram-sources" role="group" aria-label="结构图源码格式">{(Object.keys(labels) as Language[]).map(lang => <button key={lang} type="button" className="small-button" aria-pressed={language === lang} onClick={() => setLanguage(lang)}>{labels[lang]}</button>)}</div>
      {language === 'mermaid' ? <Diagram key={runId ?? "manual"} initialSource={sources.mermaid} onSourceChange={source => setSources(previous => previous ? { ...previous, mermaid: source } : null)} /> : <>
        <label>{labels[language]} 可编辑源码<textarea aria-label={`${labels[language]} 源码`} className="diagram-source-code" spellCheck={false} rows={16} value={sources[language]} onChange={e => setSources({ ...sources, [language]: e.target.value })} /></label>
        {language === 'dot' ? <DotPreview source={sources.dot} /> : <p className="muted">仅下载</p>}
      </>}
      <div className="export-row">{(Object.keys(labels) as Language[]).map(lang => <button type="button" key={lang} className="small-button" onClick={() => save(sources[lang], `research-structure.${extensions[lang]}`)}>下载 {labels[lang]}</button>)}</div>
    </> : !runId && <details><summary>手动编辑 Mermaid</summary><Diagram /></details>}
  </section>;
}

export function DotPreview({ source }: { source: string }) {
  const [svg, setSvg] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const worker = useRef<Worker | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  function stop() { worker.current?.terminate(); worker.current = null; clearTimeout(timer.current); }
  useEffect(() => { setSvg(''); setBusy(false); return stop; }, [source]);
  function render() {
    stop(); setSvg(''); setError('');
    if (source.length > 30000 || /(?:<|\b(?:image|shapefile|href|url|stylesheet|imagepath|fontpath)\s*=|javascript:|https?:\/\/)/i.test(source)) {
      setError('DOT 无效'); return;
    }
    setBusy(true);
    const next = new Worker(new URL('./diagram-dot-worker.ts', import.meta.url), { type: 'module' });
    worker.current = next;
    next.onmessage = event => {
      const data = event.data as { svg?: string; error?: string };
      if (data.error) setError(data.error);
      if (data.svg) setSvg(DOMPurify.sanitize(data.svg, { USE_PROFILES: { svg: true }, FORBID_TAGS: ['script', 'foreignObject', 'a', 'image', 'use'], FORBID_ATTR: ['href', 'xlink:href', 'onload', 'onclick'] }));
      setBusy(false); stop();
    };
    next.onerror = () => { setError('Graphviz 渲染失败'); setBusy(false); stop(); };
    timer.current = setTimeout(() => { setError('DOT 渲染超时'); setBusy(false); stop(); }, 25000);
    next.postMessage(source);
  }
  return <section aria-label="Graphviz 预览"><div className="export-row"><button type="button" className="secondary-button" disabled={busy} onClick={render}>{busy ? '浏览器本地计算中…' : '更新 DOT 预览'}</button><button type="button" className="small-button" disabled={!svg} onClick={() => save(svg, 'research-structure-dot.svg', 'image/svg+xml')}>导出 SVG</button></div>{error && <ErrorBox error={error} />}<div className="diagram-preview" dangerouslySetInnerHTML={{ __html: svg }} /></section>;
}
