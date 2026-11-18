import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import cytoscape, { type Core, type ElementDefinition, type StylesheetStyle } from 'cytoscape';
import { BookOpen, Download, Network, RefreshCw } from './icons';
import { Busy, Empty, ErrorBox } from './ui';
import type { Evidence, Graph, GraphEdge, GraphNode, Version } from './types';
import './graph-view.css';
import { WritingWorkflowForm } from './Writing';

type Props = {
  graph: Graph | null;
  versions: Version[];
  loading: boolean;
  error: string;
  onReload: () => void;
  onEvidence: (e: Evidence) => void;
  onVersion: (id: string) => void;
};
type Selection = { kind: 'node' | 'edge'; id: string } | null;
type Citation = { id: string; edge: GraphEdge };
type Publication = { year: number | null; label: string; source: string };
type ViewNode = { node: GraphNode; publication: Publication; versions: Version[] };
type CitationPath = { nodes: string[]; edges: string[] };
type Scope = 'neighborhood' | 'all' | 'path';

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

function yearValue(value: unknown): number | null {
  if (typeof value !== 'number' && typeof value !== 'string') return null;
  if (!/^\d{4}$/.test(String(value))) return null;
  const year = Number(value);
  return year >= 1000 && year <= 9999 ? year : null;
}

// Only publication fields are eligible. Upload/creation dates, titles and IDs
// never supply a publication year. Conflicting version metadata stays uncertain.
function metadataYear(metadata: Record<string, unknown>): number | null {
  const explicit = yearValue(metadata.year) ?? yearValue(metadata.publication_year);
  if (explicit !== null) return explicit;
  for (const field of ['published', 'issued', 'published-print', 'published-online']) {
    const value = metadata[field];
    if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}(?:T|$)/.test(value)) {
      return yearValue(value.slice(0, 4));
    }
    const parts = record(value)['date-parts'];
    if (Array.isArray(parts) && Array.isArray(parts[0])) {
      const year = yearValue(parts[0][0]);
      if (year !== null) return year;
    }
  }
  return null;
}

function publication(node: GraphNode, versions: Version[]): Publication {
  const fields = record(node);
  const nodeYear = metadataYear(fields) ?? metadataYear(record(fields.metadata));
  if (nodeYear !== null) return { year: nodeYear, label: String(nodeYear), source: '图谱节点发表元数据' };
  const candidates = versions.flatMap(version => {
    const year = metadataYear(record(version.metadata));
    return year === null ? [] : [{ year, label: version.label }];
  });
  const years = [...new Set(candidates.map(item => item.year))].sort();
  if (years.length === 1) return {
    year: years[0], label: String(years[0]),
    source: `版本元数据：${candidates.map(item => item.label).join('、')}`,
  };
  return years.length > 1
    ? { year: null, label: `年份待核对（${years.join(' / ')}）`, source: '版本间冲突' }
    : { year: null, label: '年份未知', source: '无元数据' };
}

function sourceUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined;
  } catch { return undefined; }
}

// Unweighted BFS over all available real directed citations, including parallel
// provenance records. Never reverse an edge or infer one from topic similarity.
function shortestPath(source: string, target: string, citations: Citation[]): CitationPath | null {
  if (source === target) return { nodes: [source], edges: [] };
  const outgoing = new Map<string, Citation[]>();
  for (const citation of citations) {
    const list = outgoing.get(citation.edge.source) ?? [];
    list.push(citation);
    outgoing.set(citation.edge.source, list);
  }
  const queue = [source];
  const seen = new Set(queue);
  const previous = new Map<string, Citation>();
  for (let cursor = 0; cursor < queue.length; cursor++) {
    for (const citation of outgoing.get(queue[cursor]) ?? []) {
      const next = citation.edge.target;
      if (seen.has(next)) continue;
      seen.add(next);
      previous.set(next, citation);
      if (next === target) {
        const nodes = [target], edges: string[] = [];
        for (let id = target; id !== source;) {
          const step = previous.get(id)!;
          edges.unshift(step.id);
          id = step.edge.source;
          nodes.unshift(id);
        }
        return { nodes, edges };
      }
      queue.push(next);
    }
  }
  return null;
}

function rank(value: number): string {
  return Number.isFinite(value) ? value.toFixed(5) : '未知';
}

export function GraphView({ graph, versions, loading, error, onReload, onEvidence, onVersion }: Props) {
  const id = useId();
  const [showSurvey, setShowSurvey] = useState(false);
  const [coreId, setCoreId] = useState('');
  const [selection, setSelection] = useState<Selection>(null);
  const [query, setQuery] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [includeUnknown, setIncludeUnknown] = useState(true);
  const [scope, setScope] = useState<Scope>('neighborhood');
  const [pathSource, setPathSource] = useState('');
  const [pathTarget, setPathTarget] = useState('');
  const [pathQuery, setPathQuery] = useState<{ source: string; target: string } | null>(null);
  const nodes = useMemo<ViewNode[]>(() => (graph?.nodes ?? []).map(node => {
    const localVersions = versions.filter(version => version.work_id === node.id);
    return { node, versions: localVersions, publication: publication(node, localVersions) };
  }).sort((a, b) => (b.node.rank - a.node.rank) || (b.node.indegree - a.node.indegree)
    || a.node.id.localeCompare(b.node.id)), [graph, versions]);
  const nodeById = useMemo(() => new Map(nodes.map(item => [item.node.id, item])), [nodes]);
  const citations = useMemo<Citation[]>(() => {
    const duplicates = new Map<string, number>();
    return (graph?.edges ?? []).filter(edge => nodeById.has(edge.source) && nodeById.has(edge.target)).map(edge => {
      const key = JSON.stringify([edge.source, edge.target, edge.ref_id, edge.version_id, edge.page_index, edge.block_id]);
      const occurrence = duplicates.get(key) ?? 0;
      duplicates.set(key, occurrence + 1);
      return { id: `citation:${key}:${occurrence}`, edge };
    });
  }, [graph, nodeById]);
  const citationById = useMemo(() => new Map(citations.map(item => [item.id, item])), [citations]);
  const core = nodeById.get(coreId) ?? nodes[0];
  const selectedEdge = selection?.kind === 'edge' ? citationById.get(selection.id) : undefined;
  const selectedNode = selection?.kind === 'node' ? nodeById.get(selection.id) ?? core : selectedEdge ? undefined : core;
  const selected: Selection = selectedEdge ? { kind: 'edge', id: selectedEdge.id }
    : selectedNode ? { kind: 'node', id: selectedNode.node.id } : null;
  const unknownCount = nodes.filter(item => item.publication.year === null).length;
  const years = nodes.flatMap(item => item.publication.year === null ? [] : [item.publication.year]);
  const invalidRange = (from !== '' && yearValue(from) === null) || (to !== '' && yearValue(to) === null)
    || (from !== '' && to !== '' && Number(from) > Number(to));
  const source = nodeById.has(pathSource) ? pathSource : core?.node.id ?? '';
  const target = nodeById.has(pathTarget) ? pathTarget : nodes.find(item => item.node.id !== source)?.node.id ?? source;
  const path = useMemo(() => pathQuery && nodeById.has(pathQuery.source) && nodeById.has(pathQuery.target)
    ? shortestPath(pathQuery.source, pathQuery.target, citations) : null, [pathQuery, citations, nodeById]);
  const visible = useMemo(() => {
    if (scope === 'path') {
      const ids = new Set(path?.nodes ?? []);
      const edges = new Set(path?.edges ?? []);
      return { nodes: nodes.filter(item => ids.has(item.node.id)), citations: citations.filter(item => edges.has(item.id)) };
    }
    const neighborhood = new Set(core ? [core.node.id] : []);
    if (core) for (const { edge } of citations) {
      if (edge.source === core.node.id) neighborhood.add(edge.target);
      if (edge.target === core.node.id) neighborhood.add(edge.source);
    }
    const filtered = invalidRange ? [] : nodes.filter(item => {
      const year = item.publication.year;
      return (scope === 'all' || neighborhood.has(item.node.id))
        && item.node.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
        && (year === null ? includeUnknown : (!from || year >= Number(from)) && (!to || year <= Number(to)));
    });
    const ids = new Set(filtered.map(item => item.node.id));
    return { nodes: filtered, citations: citations.filter(({ edge }) => ids.has(edge.source) && ids.has(edge.target)) };
  }, [scope, path, core, nodes, citations, query, from, to, includeUnknown, invalidRange]);

  function chooseCore(value: string) {
    setCoreId(value);
    setSelection({ kind: 'node', id: value });
    setScope('neighborhood');
  }
  function resetFilters() {
    setQuery(''); setFrom(''); setTo(''); setIncludeUnknown(true); setScope('neighborhood');
  }
  const hiddenCore = core && !visible.nodes.some(item => item.node.id === core.node.id);

  return <div className="page-content rt-graph-page">
    <div className="page-heading rt-graph-heading">
      <div><h1>引用图谱</h1></div>
      <div className="run-actions">
        <button type="button" className="secondary-button" onClick={() => setShowSurvey(value => !value)} aria-expanded={showSurvey}>综述</button>
        <button type="button" className="secondary-button" disabled={loading} onClick={onReload}>
          <RefreshCw size={15} />{loading ? '计算中' : '重算'}
        </button>
      </div>
    </div>
    {showSurvey && <WritingWorkflowForm workflow="survey" versions={versions} onEvidence={onEvidence} />}
    {error && <ErrorBox error={error} />}
    
    {loading && <div role="status" className="rt-graph-loading"><Busy>计算中</Busy></div>}
    {graph && nodes.length > 0 && <>
      <section className="rt-graph-filters" aria-label="图谱筛选">
        <div className="rt-graph-filter-row">
          <label className="rt-graph-title-filter"><span className="sr-only">标题</span><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索标题" /></label>
          <label className="rt-graph-core-filter">核心<select aria-label="核心节点" value={core?.node.id ?? ''} onChange={event => chooseCore(event.target.value)}>
            {nodes.map(({ node }) => <option key={node.id} value={node.id}>{node.title}</option>)}
          </select></label>
          <div className="rt-graph-scope" role="group" aria-label="图谱范围">
            <button type="button" aria-pressed={scope === 'neighborhood'} onClick={() => setScope('neighborhood')}>一跳</button>
            <button type="button" aria-pressed={scope === 'all'} onClick={() => setScope('all')}>全部</button>
          </div>
        </div>
        <div className="rt-graph-time-row">
          <label>起<input type="number" min="1000" max="9999" step="1" value={from} placeholder={years.length ? String(Math.min(...years)) : '未知'} onChange={event => setFrom(event.target.value)} aria-invalid={invalidRange} /></label>
          <span aria-hidden="true">—</span>
          <label>止<input type="number" min="1000" max="9999" step="1" value={to} placeholder={years.length ? String(Math.max(...years)) : '未知'} onChange={event => setTo(event.target.value)} aria-invalid={invalidRange} /></label>
          <label className="rt-graph-check"><input type="checkbox" checked={includeUnknown} onChange={event => setIncludeUnknown(event.target.checked)} />含未知年份 {unknownCount}</label>
          <button type="button" className="text-button" onClick={resetFilters}>重置</button>
        </div>
        
        {invalidRange && <p role="alert" className="rt-graph-inline-error">年份无效</p>}
        <details className="rt-graph-path-controls">
          <summary>引用路径</summary>
          
          <form onSubmit={event => { event.preventDefault(); setPathQuery({ source, target }); setScope('path'); setSelection({ kind: 'node', id: source }); }}>
            <label>起点<select aria-label="路径起点" value={source} onChange={event => setPathSource(event.target.value)}>{nodes.map(({ node }) => <option key={node.id} value={node.id}>{node.title}</option>)}</select></label>
            <span aria-hidden="true">→</span>
            <label>终点<select aria-label="路径终点" value={target} onChange={event => setPathTarget(event.target.value)}>{nodes.map(({ node }) => <option key={node.id} value={node.id}>{node.title}</option>)}</select></label>
            <button type="submit" className="small-button">查找</button>
          </form>
          {pathQuery && <div className="rt-graph-path-result" role="status">
            {path ? <><p>{path.edges.length} 跳</p>
              <p>{path.nodes.map(nodeId => nodeById.get(nodeId)?.node.title ?? nodeId).join(' → ')}</p>
              {scope !== 'path' && <button type="button" className="text-button" onClick={() => setScope('path')}>显示</button>}
            </> : <p>无路径</p>}
          </div>}
        </details>
      </section>
      <div className="rt-graph-view-status" role="status" aria-live="polite">
        <strong>{scope === 'path' ? '路径' : scope === 'all' ? '全部' : '一跳'}</strong>
        <span>{visible.nodes.length} / {nodes.length} 篇 · {visible.citations.length} / {citations.length} 引用</span>
      </div>
      
      {scope === 'neighborhood' && hiddenCore && <p className="rt-graph-notice">核心已被筛选隐藏</p>}
      {(graph.edges.length - citations.length) > 0 && <p className="rt-graph-notice">{graph.edges.length - citations.length} 条引用无端点</p>}
      <div className="rt-graph-workspace">
        <section className="rt-graph-stage" aria-label="图谱与文献列表">
          <GraphCanvas nodes={visible.nodes} citations={visible.citations} coreId={core?.node.id ?? ''} selection={selected} isPath={scope === 'path'} onSelect={setSelection} />
          {!visible.nodes.length && <div className="rt-graph-empty" role="status">{scope === 'path' ? '无路径' : '无匹配'}<button type="button" className="text-button" onClick={resetFilters}>恢复核心一跳</button></div>}
          <details className="rt-graph-node-list">
            <summary>文献 {visible.nodes.length}</summary>
            <ul>{visible.nodes.map(({ node, publication: published }) => <li key={node.id}>
              <button type="button" aria-pressed={selected?.kind === 'node' && selected.id === node.id} onClick={() => setSelection({ kind: 'node', id: node.id })}>
                <span>{node.id === core?.node.id && <span className="rt-graph-core-tag">核心</span>}{node.title}</span><small>{published.label}</small>
              </button>
            </li>)}</ul>
          </details>
        </section>
        <aside className="rt-graph-inspector" aria-label="节点与引用详情">
          <h2>详情</h2>
          {selectedNode && <section aria-label="文献详情">
            <p className="rt-graph-eyebrow">{selectedNode.node.id === core?.node.id ? '核心' : '文献'}</p>
            <h3>{selectedNode.node.title}</h3>
            <div className="rt-graph-role"><strong title={String(record(selectedNode.node).role_reason ?? '')}>{String(record(selectedNode.node).role_label ?? '未计算')}</strong><small>出度 {String(record(selectedNode.node).outdegree ?? '未知')} · 总度 {String(record(selectedNode.node).degree ?? '未知')} · 有向介数 {rank(Number(record(selectedNode.node).betweenness))}</small></div>
            <dl className="rt-graph-facts"><div><dt>发表年份</dt><dd>{selectedNode.publication.label}</dd></div><div><dt>年份依据</dt><dd>{selectedNode.publication.source}</dd></div><div><dt>局部 PageRank</dt><dd>{rank(selectedNode.node.rank)}</dd></div><div><dt>局部入度</dt><dd>{selectedNode.node.indegree}</dd></div></dl>
            <button type="button" className="small-button" onClick={() => chooseCore(selectedNode.node.id)}>设为核心</button>
            <div className="rt-graph-versions">{selectedNode.versions.length ? selectedNode.versions.map(version => <button key={version.id} type="button" className="text-button" onClick={() => onVersion(version.id)}><BookOpen size={14} />阅读 {version.label}</button>) : <p className="rt-graph-help">无本地版本</p>}</div>
            <h3 className="rt-graph-subheading">关联引用</h3>
            <CitationList citations={citations.filter(({ edge }) => edge.source === selectedNode.node.id || edge.target === selectedNode.node.id)} nodeById={nodeById} selectedId={selectedEdge?.id} onSelect={citationId => setSelection({ kind: 'edge', id: citationId })} />
          </section>}
          {selectedEdge && <CitationDetail citation={selectedEdge} nodeById={nodeById} onEvidence={onEvidence} onVersion={onVersion} onNode={nodeId => setSelection({ kind: 'node', id: nodeId })} />}
          <details className="rt-graph-edge-list" open={scope === 'path' ? true : undefined}>
            <summary>引用 {visible.citations.length}</summary>
            <CitationList citations={visible.citations} nodeById={nodeById} selectedId={selectedEdge?.id} onSelect={citationId => setSelection({ kind: 'edge', id: citationId })} />
          </details>
          <details className="rt-graph-role-rules"><summary>角色规则</summary><pre>{JSON.stringify(record(graph).role_rules ?? { notice: '旧图谱结果，请重新计算' }, null, 2)}</pre></details>
          <details className="rt-graph-scope-details"><summary>语料范围</summary><pre>{typeof graph.scope === 'string' ? graph.scope : JSON.stringify(graph.scope, null, 2)}</pre></details>
        </aside>
      </div>
    </>}
    {graph && !nodes.length && !loading && <Empty title="暂无图谱" icon={<Network size={38} />} />}
    {!graph && !loading && !error && <p id={`${id}-empty`}>暂无数据</p>}
  </div>;
}

function CitationList({ citations, nodeById, selectedId, onSelect }: {
  citations: Citation[]; nodeById: Map<string, ViewNode>; selectedId?: string; onSelect: (id: string) => void;
}) {
  return citations.length ? <ul className="rt-graph-citation-list">{citations.map(({ id, edge }) => <li key={id}>
    <button type="button" aria-pressed={selectedId === id} onClick={() => onSelect(id)}>
      <span>{nodeById.get(edge.source)?.node.title} <b aria-label="引用">→</b> {nodeById.get(edge.target)?.node.title}</span>
      <small>{edge.version_id !== null && edge.page_index !== null ? `第 ${edge.page_index + 1} 页` : '无页内定位'}</small>
    </button>
  </li>)}</ul> : <p className="rt-graph-help">暂无引用</p>;
}

function CitationDetail({ citation, nodeById, onEvidence, onVersion, onNode }: {
  citation: Citation; nodeById: Map<string, ViewNode>; onEvidence: Props['onEvidence']; onVersion: Props['onVersion']; onNode: (id: string) => void;
}) {
  const edge = citation.edge;
  const hasPage = Number.isInteger(edge.page_index) && Number(edge.page_index) >= 0;
  const located = Boolean(edge.version_id && hasPage && edge.block_id);
  const url = sourceUrl(edge.metadata_source_url);
  const method = record(edge).method;
  return <section className="rt-graph-citation-detail" aria-label="原始引用详情">
    <p className="rt-graph-eyebrow">引用</p>
    <div className="rt-graph-direction"><button type="button" className="text-button" onClick={() => onNode(edge.source)}>{nodeById.get(edge.source)?.node.title}</button><span aria-label="引用">→</span><button type="button" className="text-button" onClick={() => onNode(edge.target)}>{nodeById.get(edge.target)?.node.title}</button></div>
    <h3>原始条目</h3><blockquote>{edge.text || '原始条目文本缺失'}</blockquote>
    <dl className="rt-graph-facts"><div><dt>引用 ID</dt><dd>{edge.ref_id}</dd></div><div><dt>页码</dt><dd>{hasPage ? `第 ${edge.page_index! + 1} 页` : '无'}</dd></div><div><dt>匹配方法</dt><dd>{typeof method === 'string' ? method : '—'}</dd></div><div><dt>证据状态</dt><dd>{edge.status ?? '待核对'}</dd></div></dl>
    {located ? <button type="button" className="small-button" onClick={() => onEvidence({ version_id: edge.version_id!, page_index: edge.page_index!, block_id: edge.block_id!, bbox: [], quote: edge.text, status: edge.status ?? '原始参考文献条目' })}><BookOpen size={14} />定位原始条目 · 第 {edge.page_index! + 1} 页</button>
      : <><p className="rt-graph-help">无原文定位</p>{edge.version_id && <button type="button" className="text-button" onClick={() => onVersion(edge.version_id!)}>阅读来源版本</button>}</>}
    {url && <a className="text-button" href={url} target="_blank" rel="noopener noreferrer">来源 ↗</a>}
  </section>;
}

// Canvas has an equivalent native-button node/edge list above, because Cytoscape
// canvas elements themselves do not expose accessible DOM nodes.
const styles: StylesheetStyle[] = [
  { selector: 'node', style: { width: 24, height: 24, 'background-color': '#0f1012', 'border-width': 2, 'border-color': '#fff', label: 'data(label)', 'font-size': 11, color: '#3c3f45', 'text-valign': 'bottom', 'text-margin-y': 9, 'text-wrap': 'wrap', 'text-max-width': '148px', 'text-background-color': '#ffffff', 'text-background-opacity': 0.9, 'text-background-padding': '3px' } },
  { selector: 'node.unknown-year', style: { 'background-color': '#ffffff', 'border-color': '#8d9097', 'border-width': 2 } },
  { selector: 'node.core', style: { 'background-color': '#c9f23a', width: 38, height: 38, 'border-color': '#0f1012', 'border-width': 2 } },
  { selector: 'edge', style: { width: 1.2, 'curve-style': 'bezier', 'line-color': '#c6c6be', 'target-arrow-color': '#a7a9ae', 'target-arrow-shape': 'triangle', 'arrow-scale': 1.2, 'source-arrow-shape': 'none' } },
  { selector: 'edge.path', style: { width: 3, 'line-color': '#0f1012', 'target-arrow-color': '#0f1012', label: '引用', 'font-size': 10, 'text-rotation': 'autorotate', 'text-background-color': '#fff', 'text-background-opacity': 1, 'text-background-padding': '3px', color: '#62429f' } },
  { selector: 'node.is-selected', style: { 'border-width': 5, 'border-color': '#6f8f00' } },
  { selector: 'edge.is-selected', style: { width: 4, 'line-color': '#6f8f00', 'target-arrow-color': '#6f8f00', 'z-index': 10 } },
];

function GraphCanvas({ nodes, citations, coreId, selection, isPath, onSelect }: {
  nodes: ViewNode[]; citations: Citation[]; coreId: string; selection: Selection; isPath: boolean; onSelect: (selection: Selection) => void;
}) {
  const id = useId();
  const container = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const handleSelect = useRef(onSelect);
  handleSelect.current = onSelect;
  const downloadUrl = useRef<string | null>(null);
  const [error, setError] = useState('');
  const [exporting, setExporting] = useState(false);
  const elements = useMemo<ElementDefinition[]>(() => [
    ...nodes.map(({ node, publication: published }) => ({ data: { id: `work:${node.id}`, workId: node.id, label: `${node.title.length > 38 ? node.title.slice(0, 38) + '…' : node.title}${published.year === null ? '' : `\n${published.year}`}` }, classes: [node.id === coreId ? 'core' : '', published.year === null ? 'unknown-year' : ''].join(' ') })),
    ...citations.map(({ id: edgeId, edge }) => ({ data: { id: edgeId, source: `work:${edge.source}`, target: `work:${edge.target}` }, classes: isPath ? 'path' : '' })),
  ], [nodes, citations, coreId, isPath]);

  useEffect(() => {
    if (!container.current) return;
    const instance = cytoscape({ container: container.current, elements: [], style: styles, layout: { name: 'preset' }, minZoom: 0.08, maxZoom: 3, autounselectify: true, pixelRatio: Math.min(window.devicePixelRatio || 1, 2) });
    cy.current = instance;
    instance.on('tap', 'node', event => handleSelect.current({ kind: 'node', id: event.target.data('workId') as string }));
    instance.on('tap', 'edge', event => handleSelect.current({ kind: 'edge', id: event.target.id() as string }));
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => { instance.resize(); if (instance.nodes().length) instance.fit(undefined, 46); });
    });
    observer.observe(container.current);
    return () => {
      observer.disconnect(); cancelAnimationFrame(frame); instance.destroy(); cy.current = null;
      if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current);
    };
  }, []);

  useEffect(() => {
    const instance = cy.current;
    if (!instance) return;
    instance.batch(() => { instance.elements().remove(); instance.add(elements); });
    if (nodes.length) instance.layout(isPath
      ? { name: 'breadthfirst', directed: true, padding: 46, spacingFactor: 1.2, animate: false }
      : { name: 'concentric', padding: 46, minNodeSpacing: 45, nodeDimensionsIncludeLabels: true, animate: false, concentric: node => node.data('workId') === coreId ? 2 : 1, levelWidth: () => 1 }).run();
  }, [elements, nodes.length, coreId, isPath]);

  useEffect(() => {
    const instance = cy.current;
    if (!instance) return;
    instance.elements().removeClass('is-selected');
    if (selection) instance.getElementById(selection.kind === 'node' ? `work:${selection.id}` : selection.id).addClass('is-selected');
  }, [selection?.kind, selection?.id, elements]);

  function fit() { cy.current?.fit(undefined, 46); }
  function zoom(factor: number) {
    const instance = cy.current;
    if (instance) instance.zoom({ level: Math.max(instance.minZoom(), Math.min(instance.maxZoom(), instance.zoom() * factor)), renderedPosition: { x: instance.width() / 2, y: instance.height() / 2 } });
  }
  function keyboard(event: KeyboardEvent<HTMLDivElement>) {
    if (event.target !== event.currentTarget || !cy.current) return;
    const pan: Record<string, { x: number; y: number }> = { ArrowLeft: { x: 45, y: 0 }, ArrowRight: { x: -45, y: 0 }, ArrowUp: { x: 0, y: 45 }, ArrowDown: { x: 0, y: -45 } };
    if (pan[event.key]) { event.preventDefault(); cy.current.panBy(pan[event.key]); }
    else if (event.key === '+' || event.key === '=') { event.preventDefault(); zoom(1.25); }
    else if (event.key === '-') { event.preventDefault(); zoom(0.8); }
    else if (event.key === '0' || event.key === 'Home') { event.preventDefault(); fit(); }
  }
  async function exportPng() {
    if (!cy.current || !nodes.length) return;
    setExporting(true); setError('');
    try {
      const blob = await cy.current.png({ output: 'blob-promise', full: true, bg: '#ffffff', maxWidth: 2400, maxHeight: 1800 });
      if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current);
      const url = URL.createObjectURL(blob);
      downloadUrl.current = url;
      const link = document.createElement('a');
      link.href = url; link.download = 'researchtrace-citations.png'; document.body.append(link); link.click(); link.remove();
    } catch (reason) { setError(`PNG 导出失败：${reason instanceof Error ? reason.message : String(reason)}`); }
    finally { setExporting(false); }
  }

  return <>
    <div className="rt-graph-toolbar" role="group" aria-label="图谱视图操作">
      <span className="rt-graph-legend"><i className="rt-graph-dot" />核心 <i className="rt-graph-dot rt-graph-dot-paper" />文献 <span>空心 未知年份</span><span>→ 引用</span></span>
      <div className="rt-graph-tools"><button type="button" className="small-button" aria-label="缩小图谱" onClick={() => zoom(0.8)}>−</button><button type="button" className="small-button" aria-label="放大图谱" onClick={() => zoom(1.25)}>＋</button><button type="button" className="small-button" onClick={fit}>适应画布</button><button type="button" className="small-button" disabled={!nodes.length || exporting} onClick={() => void exportPng()}><Download size={14} />{exporting ? '导出中…' : '导出 PNG'}</button></div>
    </div>
    {error && <ErrorBox error={error} />}
    {/* Refresh coordinates before hit testing when a scroll moved the canvas. */}
    <div className="rt-graph-canvas" ref={container} role="region" aria-label="交互引用图" aria-describedby={`${id}-help`} tabIndex={0} onKeyDown={keyboard} onPointerDownCapture={() => cy.current?.resize()} />
    <p id={`${id}-help`} className="sr-only">拖动平移，滚轮或双指缩放。键盘：方向键平移，+ / − 缩放，0 适应画布。Tab 可选择下方文献与右侧引用；Enter / 空格打开详情。</p>
  </>;
}
