import { Readiness } from './Readiness';
import { ReviewAccounts } from './ReviewAccounts';
import { useEffect, useState, lazy, Suspense } from 'react';
import { BarChart3, Code2, Download, FilePenLine, Image, ListChecks, RefreshCw, ShieldCheck, UploadCloud } from './icons';
import { api, date, endpoint, errorMessage, key, parseObject, shownVersion } from './api';
import type { Artifact, ChartResult, Evidence, Version, Run, Result } from './types';
import { Badge, Busy, Disclosure, Empty, ErrorBox, Markdown } from './ui';
import { useModelConfig } from './ModelConfig';
import { RunDetail } from './RunPanel';
const Diagram=lazy(()=>import('./DiagramStudio'));
import './writing-workflows.css';
const artifactTitle=(title:string)=>title.split(/[。！？]/)[0];
const ARTIFACT_KINDS:Record<string,string>={research_note:'笔记',agent_note:'草稿',outline:'论文框架',survey:'综述',chart:'图表',diagram:'结构图',idea_audit:'Future Work',translation:'翻译'};
export function WritingPage({versions,onEvidence,refresh}:{versions:Version[];onEvidence:(e:Evidence)=>void;refresh:()=>void}){const model=useModelConfig();const [tab,setTab]=useState('chart');const [file,setFile]=useState<File|null>(null);const [kind,setKind]=useState('line');const [x,setX]=useState('');const [y,setY]=useState<string[]>([]);const [z,setZ]=useState('');const [title,setTitle]=useState('');const [xUnit,setXUnit]=useState('');const [yUnit,setYUnit]=useState('');const [aggregate,setAggregate]=useState('none');const [chart,setChart]=useState<ChartResult|null>(null);const [loading,setLoading]=useState(false);const [error,setError]=useState('');const [columns,setColumns]=useState<string[]>([]);const [selected,setSelected]=useState<string[]>([]);const [question,setQuestion]=useState('');const [runId,setRun]=useState<string|null>(null);const [artifacts,setArtifacts]=useState<Artifact[]>([]);const [opened,setOpened]=useState<Artifact|null>(null);async function loadArtifacts(){try{setArtifacts((await api<Artifact[]>('/artifacts')).map(a=>({...a,payload:parseObject(a.payload,{})})))}catch(e){setError(errorMessage(e))}}useEffect(()=>{void loadArtifacts()},[]);async function plot(){if(!file)return;setLoading(true);setError('');try{const form=new FormData();form.append('file',file);form.append('spec',JSON.stringify({kind,...(x?{x}:{}),...(y.length?{y}:{}),...(z?{z}:{}),title,x_unit:xUnit,y_unit:yUnit,aggregate}));const r=await api<ChartResult>('/charts',form);setChart(r);const c=r.columns;if(Array.isArray(c)){setColumns(c.map(col=>typeof col==='string'?col:String((col as Record<string,unknown>).name??col)));}else if(c&&typeof c==='object'){setColumns(Object.keys(c))}await loadArtifacts()}catch(e){setError(errorMessage(e))}finally{setLoading(false)}}async function write(){setLoading(true);setError('');try{const r=await api<{id:string}>('/agent/runs',{question:question||'请根据所选文献生成 Related Work 草稿，包含研究问题、方法脉络、差异、局限和可验证的待研究点。所有事实有证据；没有实验结果写待填写，不能编造结果。',version_ids:selected,idempotency_key:key()});setRun(r.id);refresh()}catch(e){setError(errorMessage(e))}finally{setLoading(false)}}const shownArtifacts=artifacts.filter(a=>a.kind!=='agent_tool_result');function selectFile(next:File|null){setFile(next);setColumns([]);setX('');setY([]);setZ('');setChart(null)}return <div className="page-content writing-page"><div className="page-heading"><div><h1>写作</h1></div></div><div className="tab-row wide"><button className={tab==='chart'?'active':''} onClick={()=>setTab('chart')}><BarChart3 size={17}/>图表</button><button className={tab==='write'?'active':''} onClick={()=>setTab('write')}><FilePenLine size={17}/>写作</button><button className={tab==='outline'?'active':''} onClick={()=>setTab('outline')}>论文框架</button><button className={tab==='survey'?'active':''} onClick={()=>setTab('survey')}>综述</button><button className={tab==='translate'?'active':''} onClick={()=>setTab('translate')}>翻译</button><button className={tab==='diagram'?'active':''} onClick={()=>setTab('diagram')}><Code2 size={17}/>结构图</button><button className={tab==='artifacts'?'active':''} onClick={()=>{setTab('artifacts');void loadArtifacts()}}><Image size={17}/>产物</button></div>{error&&<ErrorBox error={error} onClose={()=>setError('')}/>}
{tab==='chart'&&<div className="chart-workbench"><section className="chart-controls"><h2>数据</h2><label className="csv-upload"><UploadCloud size={25}/><strong>{file?.name??'选择 CSV'}</strong><small>UTF-8 / GB18030</small><input type="file" accept=".csv,text/csv" onChange={e=>selectFile(e.target.files?.[0]??null)} aria-label="上传 CSV"/></label><label>类型<select value={kind} onChange={e=>setKind(e.target.value)}><option value="line">折线图</option><option value="bar">柱状图</option><option value="radar">雷达图</option><option value="3d">三维图</option></select></label><label>标题<input value={title} onChange={e=>setTitle(e.target.value)} placeholder="可选"/></label>{columns.length>0&&<><label>X 轴<select value={x} onChange={e=>setX(e.target.value)}><option value="">自动选择</option>{columns.map(c=><option key={c}>{c}</option>)}</select></label><label>Y 轴<select multiple value={y} onChange={e=>setY(Array.from(e.target.selectedOptions).map(o=>o.value))}>{columns.map(c=><option key={c}>{c}</option>)}</select></label>{kind==='3d'&&<label>Z 轴<select value={z} onChange={e=>setZ(e.target.value)}><option value="">选择数值列</option>{columns.map(c=><option key={c}>{c}</option>)}</select></label>}</>}<div className="field-pair"><label>X 单位<input value={xUnit} onChange={e=>setXUnit(e.target.value)} placeholder="可选"/></label><label>Y 单位<input value={yUnit} onChange={e=>setYUnit(e.target.value)} placeholder="可选"/></label></div><label>聚合<select value={aggregate} onChange={e=>setAggregate(e.target.value)}><option value="none">不聚合</option><option value="mean">均值</option><option value="sum">求和</option></select></label><button className="primary-button" disabled={!file||loading} onClick={()=>void plot()}>{loading?<Busy/>:<BarChart3 size={16}/>} {chart?'重新绘图':'生成图表'}</button></section><section className="chart-output">{chart?<><div className="section-heading"><h2>结果</h2><Badge>已保存</Badge></div>{chart.files.png&&<img className="generated-chart" src={chart.files.png} alt={chart.caption||'CSV 数据生成的图表'}/>}<div className="chart-caption"><strong>Caption</strong><p>{chart.caption}</p></div>{chart.warnings?.map((w,i)=><p className="warning-note" key={i}>{w}</p>)}<div className="export-row">{Object.entries(chart.files).map(([kind,url])=><a className="small-button" key={kind} href={url} download><Download size={14}/>{({png:'PNG',svg:'SVG',script:'复现脚本',spec:'PlotSpec',csv:'原始 CSV'} as Record<string,string>)[kind]??kind}</a>)}</div><Disclosure title="统计"><pre className="code-block">{JSON.stringify({columns:chart.columns,statistics:chart.statistics},null,2)}</pre></Disclosure></>:<Empty title="上传 CSV" icon={<BarChart3 size={40} strokeWidth={1.3}/>}/>}</section></div>}
{tab==='write'&&<><h2>来源</h2><div className="compare-selector">{versions.map(v=><label key={v.id} className={selected.includes(v.id)?'selected':''}><input type="checkbox" checked={selected.includes(v.id)} onChange={()=>setSelected(s=>s.includes(v.id)?s.filter(id=>id!==v.id):[...s,v.id])}/><div><strong>{v.title}</strong><span>{shownVersion(v.label)}</span></div></label>)}</div><div className="compose-block"><label>任务<textarea rows={4} value={question} onChange={e=>setQuestion(e.target.value)} placeholder="Related Work / 提纲 / 段落"/></label><button className="primary-button" disabled={model?.model_configured===false||!selected.length||loading} onClick={()=>void write()}>{model?.model_configured===false?'模型配置缺失':loading?<Busy/>:'生成草稿'}</button></div>{runId&&<RunDetail runId={runId} onEvidence={onEvidence} onUpdate={()=>void loadArtifacts()}/>}</>}
{(tab==='outline'||tab==='survey')&&<WritingWorkflowForm key={tab} workflow={tab} versions={versions} onEvidence={onEvidence} onQueued={refresh}/>}
{tab==='translate'&&<WritingTranslation versions={versions} onEvidence={onEvidence} onQueued={refresh}/>}
{tab==='diagram'&&<Suspense fallback={<Busy>载入结构图编辑器</Busy>}><Diagram versions={versions} onEvidence={onEvidence} onQueued={refresh}/></Suspense>}
{tab==='artifacts'&&<div className="artifact-list">{!shownArtifacts.length?<Empty title="暂无产物"/>:shownArtifacts.map(a=><button key={a.id} className={`artifact-row ${opened?.id===a.id?'selected':''}`} onClick={()=>setOpened(a)}><FilePenLine size={20}/><div><strong>{artifactTitle(a.title)}</strong><span>{ARTIFACT_KINDS[a.kind]??a.kind} · {date(a.created)}</span></div><Download size={16}/></button>)}{opened&&<section className="artifact-preview"><div className="section-heading"><h2>{artifactTitle(opened.title)}</h2><button className="text-button" onClick={()=>setOpened(null)}>关闭</button></div><Markdown>{String(opened.payload.markdown??opened.payload.answer??opened.payload.caption??JSON.stringify(opened.payload,null,2))}</Markdown><div className="export-row">{(opened.kind==='diagram'?['mermaid','dot','tikz','matplotlib','json']:['survey','outline'].includes(opened.kind)?['md','bib']:['md','html','bib']).map(f=><a className="small-button" key={f} href={endpoint(`${['survey','outline','diagram'].includes(opened.kind)?'/writing':''}/artifacts/${opened.id}/export?format=${f}`)} download><Download size={14}/>{f}</a>)}</div></section>}</div>}
</div>}
interface ProviderReport { configured:boolean;paid_fallback:boolean;reset_at:number|string;projects:unknown;models:{model:string;rpm:number;tpm:number;rpd:number}[];status:unknown;usage:{project:string;model:string;day:string;calls:number;input_tokens:number;output_tokens:number}[];hydrogen_total_used:number;hydrogen_budget:number;remaining_balance:unknown }
export function ResourcesPage({role,onOpenAcceptance}:{role:string;onOpenAcceptance?:()=>void}){const [report,setReport]=useState<ProviderReport|null>(null);const [error,setError]=useState('');const [loading,setLoading]=useState(false);async function load(){setLoading(true);setError('');try{setReport(await api<ProviderReport>('/admin/providers'))}catch(e){setError(errorMessage(e))}finally{setLoading(false)}}useEffect(()=>{if(role==='admin')void load()},[role]);return <div className="page-content"><div className="page-heading"><div><h1>资源与配额</h1></div>{role==='admin'&&<div className="run-actions">{onOpenAcceptance&&<button className="primary-button" onClick={onOpenAcceptance}><ListChecks size={15}/>验收</button>}<button className="secondary-button" disabled={loading} onClick={()=>void load()}><RefreshCw size={15}/>刷新</button></div>}</div><Readiness/><ReviewAccounts role={role}/>{error&&<ErrorBox error={error}/>} {role!=='admin'?null:loading&&!report?<Busy/>:report&&<><div className="provider-policy"><div><ShieldCheck size={22}/><strong>付费兜底 {report.paid_fallback?'已启用':'关闭'}</strong></div></div><div className="provider-overview"><div><span>模型配置</span><strong>{report.configured?'已配置':'缺少配置'}</strong></div><div><span>Hydrogen 本地累计</span><strong>{report.hydrogen_total_used} / {report.hydrogen_budget}</strong></div><div><span>日配额复位</span><strong>{typeof report.reset_at==='number'?date(report.reset_at):report.reset_at}</strong><small>America/Los_Angeles</small></div></div><section><h2>模型限额</h2><div className="data-table-wrap"><table><thead><tr><th>模型</th><th>RPM</th><th>输入 TPM</th><th>RPD</th></tr></thead><tbody>{report.models?.map(m=><tr key={m.model}><td>{m.model}</td><td>{m.rpm}</td><td>{m.tpm.toLocaleString()}</td><td>{m.rpd}</td></tr>)}</tbody></table></div></section><section><h2>请求账本</h2><div className="data-table-wrap"><table><thead><tr><th>项目</th><th>模型</th><th>太平洋日期</th><th>请求数</th><th>输入 tokens</th><th>输出 tokens</th></tr></thead><tbody>{report.usage?.map((u,i)=><tr key={i}><td>{u.project}</td><td>{u.model}</td><td>{u.day}</td><td>{u.calls}</td><td>{u.input_tokens}</td><td>{u.output_tokens}</td></tr>)}</tbody></table>{!report.usage?.length&&<p className="muted padded">暂无</p>}</div></section><Disclosure title="连接与项目" initial><pre className="code-block">{JSON.stringify({projects:report.projects,status:report.status,remaining_balance:report.remaining_balance},null,2)}</pre></Disclosure></>}</div>}

/** Dedicated, durable writing workflows. Server truth is rendered by RunDetail. */
export function WritingWorkflowForm({ workflow, versions, onEvidence, onQueued = () => {} }: {
  workflow: 'survey' | 'outline'; versions: Version[]; onEvidence: (e: Evidence) => void; onQueued?: () => void;
}) {
  const [question, setQuestion] = useState('');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [budget, setBudget] = useState(48000);
  const [runId, setRunId] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const model = useModelConfig();
  const survey = workflow === 'survey';
  async function submit() {
    setBusy(true); setError(''); setResult(null);
    try {
      const run = await api<{ id: string }>(`/writing/${survey ? 'surveys' : 'outlines'}`, {
        question, version_ids: selected, context_budget: budget, idempotency_key: key(),
        ...(query.trim() && !survey ? { search_query: query.trim() } : {}),
      });
      setRunId(run.id); onQueued();
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  }
  async function finished() {
    if (!runId) return;
    try { const run = await api<Run>(`/runs/${runId}`); setResult(parseObject<Result | null>(run.result, null)); }
    catch (reason) { setError(errorMessage(reason)); }
  }
  return <section className="writing-workflow" aria-label={survey ? '领域综述工作流' : 'idea论文框架工作流'}>
    <h2>{survey ? '综述' : '论文框架'}</h2>
    
    <label>{survey ? '综述主题与范围' : '研究 idea'}<textarea rows={4} maxLength={3000} value={question} onChange={e => setQuestion(e.target.value)} placeholder={survey ? '问题 / 条件 / 范围' : '问题 / 方法 / 假设'} /></label>
    {!survey && <label>检索词<input maxLength={500} value={query} onChange={e => setQuery(e.target.value)} placeholder="可选" /></label>}
    <fieldset><legend>来源 {selected.length} / 50</legend>
      <div className="writing-source-actions"><button type="button" className="small-button" onClick={() => setSelected(versions.slice(0, 20).map(v => v.id))}>选择前20篇</button><button type="button" className="text-button" onClick={() => setSelected([])}>清空选择</button></div>
      <div className="writing-source-list">{versions.map(v => <label key={v.id}><input type="checkbox" checked={selected.includes(v.id)} disabled={!selected.includes(v.id) && selected.length >= 50} onChange={() => setSelected(s => s.includes(v.id) ? s.filter(id => id !== v.id) : [...s, v.id])} /><span>{v.title}<small>{[shownVersion(v.label), `${v.page_count} 页`].filter(Boolean).join(' · ')}</small></span></label>)}</div>
      {!versions.length && <p className="muted">暂无论文</p>}
    </fieldset>
    <label>上下文<select value={budget} onChange={e => setBudget(Number(e.target.value))}><option value={24000}>24 KB · 精简</option><option value={48000}>48 KB · 标准</option><option value={64000}>64 KB · 扩展</option></select></label>
    
    <button type="button" className="primary-button" disabled={busy || !question.trim() || (survey && !selected.length) || model?.model_configured === false} onClick={() => void submit()}>{busy ? <Busy /> : survey ? '生成领域综述' : '检索并生成论文框架'}</button>
    {error && <ErrorBox error={error} />}
    {runId && <RunDetail runId={runId} onEvidence={onEvidence} onUpdate={() => void finished()} />}
    {result && <StructuredWriting result={result} />}
  </section>;
}

function StructuredWriting({ result }: { result: Result }) {
  const sections = Array.isArray(result.sections) ? result.sections as { key: string; title: string; claim_ids: string[]; text: string }[] : [];
  const refs = Array.isArray(result.bibliography) ? result.bibliography as { id: string; title: string; identity: string; fulltext_status: string }[] : [];
  return <div className="writing-structured">
    {sections.length > 0 && <details open><summary>章节</summary>{sections.map(s => <section key={s.key}><h3>{s.title}</h3><p>{s.text}</p><small>主张 {s.claim_ids.join('、')}</small></section>)}</details>}
    {refs.length > 0 && <section><h3>References</h3><ul>{refs.map(r => <li key={r.id}>[{r.id}] {r.title} · {r.identity}<small>{r.fulltext_status === 'bibliography_only' ? '仅书目' : '有原文摘录'}</small></li>)}</ul></section>}
    {result.search != null && <Disclosure title="检索记录"><pre className="code-block">{JSON.stringify(result.search, null, 2)}</pre></Disclosure>}
    {Array.isArray(result.coverage) && <Disclosure title="证据覆盖"><pre className="code-block">{JSON.stringify(result.coverage, null, 2)}</pre></Disclosure>}
    {result.artifact_id && <div className="export-row">{['md', 'bib'].map(format => <a key={format} className="small-button" href={endpoint(`/writing/artifacts/${result.artifact_id}/export?format=${format}`)} download>下载 {format === 'md' ? '完整章节与证据' : '已核验 BibTeX'}</a>)}</div>}
  </div>;
}

function WritingTranslation({ versions, onEvidence, onQueued }: { versions: Version[]; onEvidence: (e: Evidence) => void; onQueued: () => void }) {
  const [text, setText] = useState('');
  const [target, setTarget] = useState('en');
  const [versionId, setVersionId] = useState('');
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [confirmWhole, setConfirmWhole] = useState(false);
  async function translate(whole: boolean) {
    setBusy(true); setError('');
    try {
      const run = await api<{ id?: string; run_id?: string }>(whole ? '/translations' : '/text/translations', whole
        ? { version_id: versionId, source_language: 'auto', target_language: target, idempotency_key: key() }
        : { text, target_language: target, idempotency_key: key() });
      setRunId(run.id ?? run.run_id ?? null); onQueued();
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  }
  return <section className="writing-workflow" aria-label="写作中英翻译">
    <h2>翻译</h2>
    <label>目标语言<select value={target} onChange={e => setTarget(e.target.value)}><option value="en">英文</option><option value="zh-Hans">简体中文</option></select></label>
    <label>文本<textarea rows={7} maxLength={12000} value={text} onChange={e => setText(e.target.value)} placeholder="粘贴文本" /></label>
    <button type="button" className="primary-button" disabled={!text.trim() || busy} onClick={() => void translate(false)}>{busy ? <Busy /> : '翻译'}</button>
    <details><summary>整篇 PDF</summary>
      <label>已解析 PDF<select value={versionId} onChange={e => { setVersionId(e.target.value); setConfirmWhole(false); }}><option value="">选择文献</option>{versions.map(v => <option key={v.id} value={v.id}>{v.title} · {v.page_count} 页</option>)}</select></label>
      
      <label className="writing-confirm"><input type="checkbox" checked={confirmWhole} onChange={e => setConfirmWhole(e.target.checked)} />确认整篇翻译</label>
      <button type="button" className="secondary-button" disabled={!versionId || !confirmWhole || busy} onClick={() => void translate(true)}>开始全文翻译</button>
    </details>
    {error && <ErrorBox error={error} />}{runId && <RunDetail runId={runId} onEvidence={onEvidence} />}
  </section>;
}
