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
    <h2>由 idea 或论文生成可编辑结构图</h2>
    <label>架构设想<textarea rows={4} maxLength={3000} value={question} onChange={e => setQuestion(e.target.value)} placeholder="说明模块、信息流、输入输出和你希望展示的研究逻辑" /></label>
    <label>可选论文摘录<select value={selected} onChange={e => setSelected(e.target.value)}><option value="">仅根据 idea 生成建议结构</option>{versions.map(v => <option key={v.id} value={v.id}>{v.title} · {v.label}</option>)}</select></label>
    <p className="muted">Flash 回答路由生成严格 graph JSON，程序生成四种源码。Mermaid / DOT 在浏览器预览；Python / TikZ 只提供可编辑下载。</p>
    <button type="button" className="primary-button" disabled={busy || !question.trim()} onClick={() => void generate()}>{busy ? <Busy /> : '生成结构图与四种源码'}</button>
    {error && <ErrorBox error={error} />}
    {runId && <RunDetail runId={runId} onEvidence={onEvidence} onUpdate={() => void finished()} />}
    {sources ? <>
      <div className="diagram-sources" role="group" aria-label="结构图源码格式">{(Object.keys(labels) as Language[]).map(lang => <button key={lang} type="button" className="small-button" aria-pressed={language === lang} onClick={() => setLanguage(lang)}>{labels[lang]}</button>)}</div>
      {language === 'mermaid' ? <Diagram key={sources.mermaid} initialSource={sources.mermaid} /> : <>
        <label>{labels[language]} 可编辑源码<textarea aria-label={`${labels[language]} 源码`} className="diagram-source-code" spellCheck={false} rows={16} value={sources[language]} onChange={e => setSources({ ...sources, [language]: e.target.value })} /></label>
        {language === 'dot' ? <DotPreview source={sources.dot} /> : <p className="info-note">源码仅下载；本平台不执行此 {labels[language]} 代码。生成图中的节点与边来自本次建议结构，不代表已运行的实验。</p>}
      </>}
      <div className="export-row">{(Object.keys(labels) as Language[]).map(lang => <button type="button" key={lang} className="small-button" onClick={() => save(sources[lang], `research-structure.${extensions[lang]}`)}>下载 {labels[lang]}</button>)}</div>
    </> : !runId && <details><summary>手动编辑 Mermaid 示例（无需模型调用）</summary><Diagram /></details>}
  </section>;
}

export function DotPreview({ source }: { source: string }) {
  const [svg, setSvg] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const worker = useRef<Worker | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  function stop() { worker.current?.terminate(); worker.current = null; clearTimeout(timer.current); }
  useEffect(() => { setSvg(''); return stop; }, [source]);
  function render() {
    stop(); setSvg(''); setError('');
    if (source.length > 30000 || /(?:<|\b(?:image|shapefile|href|url|stylesheet|imagepath|fontpath)\s*=|javascript:|https?:\/\/)/i.test(source)) {
      setError('DOT 超过大小限制或包含外部资源、HTML、链接属性。'); return;
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
    next.onerror = () => { setError('本地 Graphviz WASM 载入或渲染失败。'); setBusy(false); stop(); };
    timer.current = setTimeout(() => { setError('DOT 渲染超过25秒，已停止本次浏览器渲染。'); setBusy(false); stop(); }, 25000);
    next.postMessage(source);
  }
  return <section aria-label="Graphviz WASM 预览"><div className="export-row"><button type="button" className="secondary-button" disabled={busy} onClick={render}>{busy ? '浏览器本地计算中…' : '更新 DOT 预览'}</button><button type="button" className="small-button" disabled={!svg} onClick={() => save(svg, 'research-structure-dot.svg', 'image/svg+xml')}>导出 SVG</button></div>{error && <ErrorBox error={error} />}<div className="diagram-preview" dangerouslySetInnerHTML={{ __html: svg }} /></section>;
}
