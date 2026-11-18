import { useEffect, useRef, useState } from 'react';
import { api, date, errorMessage, key } from './api';
import type { ParseSnapshot } from './types';
import { Busy, ErrorBox } from './ui';

export const parseInProgress = (status:string) => ['queued','pending','running','parsing','resuming'].includes(status);
const statusLabel = (status:string) => ({queued:'排队中',pending:'等待中',running:'解析中',parsing:'解析中',resuming:'恢复中',completed:'已完成',ready:'已完成',failed:'失败',blocked:'受阻',cancelled:'已取消',partial:'部分完成'} as Record<string,string>)[status] ?? status;

export function useParseSnapshots(versionId?:string) {
 const [snapshots,setSnapshots]=useState<ParseSnapshot[]>([]);
 const [error,setError]=useState('');
 const [loading,setLoading]=useState(true);
 const [revision,setRevision]=useState(0);
 const reload=()=>setRevision(n=>n+1);
 useEffect(()=>{
  setSnapshots([]);setError('');
 },[versionId]);
 useEffect(()=>{
  if(!versionId){setLoading(false);return;}
  let live=true;let timer:ReturnType<typeof setTimeout>;
  async function load(){
   setLoading(true);
   try {
    const rows=await api<ParseSnapshot[]>(`/documents/${versionId}/parses`);
    if(!Array.isArray(rows)||rows.some(s=>typeof s.id!=='string'||typeof s.status!=='string'))throw new Error('快照格式无效');
    if(live){setSnapshots(rows);setError('')}
   }catch(e){if(live)setError(errorMessage(e))}
   finally{if(live){setLoading(false);timer=setTimeout(()=>void load(),5000)}}
  }
  void load();return()=>{live=false;clearTimeout(timer)};
 },[versionId,revision]);
 return {snapshots,error,loading,reload};
}

export function ParseControls({versionId,snapshots,selected,onSelect,error,loading,reload,onSubmitted}:{versionId:string;snapshots:ParseSnapshot[];selected:string;onSelect:(id:string)=>void;error:string;loading:boolean;reload:()=>void;onSubmitted:(runId:string)=>void}) {
 const [engine,setEngine]=useState<'native'|'paddleocr'|'paddleocr_vl'|'mineru'>('native');
 const [device,setDevice]=useState<'cpu'|'gpu'>('cpu');
 const [submitting,setSubmitting]=useState(false);
 const [submitError,setSubmitError]=useState('');
 const [message,setMessage]=useState('');
 const request=useRef<{signature:string;id:string}|null>(null);
 const busy=useRef(false);
 const currentVersion=useRef(versionId);currentVersion.current=versionId;
 useEffect(()=>{request.current=null;setSubmitError('');setMessage('')},[versionId,engine,device]);
 async function submit(){
  if(busy.current)return;
  const signature=JSON.stringify([versionId,engine,device]);
  if(request.current?.signature!==signature)request.current={signature,id:key()};
  busy.current=true;setSubmitting(true);setSubmitError('');setMessage('');
  try{
   const result=await api<{id:string;run_id:string;status:string;parse_id:string}>(`/documents/${versionId}/parses`,{engine,device,idempotency_key:request.current.id});
   if(typeof result.run_id!=='string'||typeof result.parse_id!=='string')throw new Error('提交结果无效');
   if(currentVersion.current!==versionId)return;
   request.current=null;setMessage('已提交');reload();onSubmitted(result.run_id);
  }catch(e){if(currentVersion.current===versionId)setSubmitError(errorMessage(e))}
  finally{busy.current=false;setSubmitting(false)}
 }
 const snapshot=snapshots.find(s=>s.id===selected)||snapshots.find(s=>Boolean(s.active));
 return <details className="parse-controls" open>
  <summary>解析快照与重新解析</summary>
  <label>阅读快照<select aria-label="选择解析快照" value={selected} onChange={e=>onSelect(e.target.value)} disabled={Boolean(error)||!snapshots.length}>
   <option value="">当前活动快照</option>
   {selected&&!snapshots.some(s=>s.id===selected)&&<option value={selected}>引用快照 {selected.slice(0,12)}</option>}
   {snapshots.map(s=><option key={s.id} value={s.id}>{s.engine} · {statusLabel(s.status)}{s.active?' · 活动':''} · {s.id.slice(0,8)}</option>)}
  </select></label>
  {snapshot&&<div className="parse-snapshot-detail"><span>{statusLabel(snapshot.status)} · {snapshot.device??'设备未记录'}</span><span>已解析 {snapshot.parsed_pages??'?'} / {snapshot.page_count??'?'} 页</span><span>{date(snapshot.created)}</span>{snapshot.error&&<p role="alert">{snapshot.error}</p>}</div>}
  <button className="text-button" disabled={loading} onClick={reload}>{loading?<Busy>刷新快照</Busy>:'刷新快照'}</button>
  {error&&<ErrorBox error={`解析快照暂不可用：${error}`}/>}
  
  <div className="parse-options"><label>解析引擎<select aria-label="解析引擎" value={engine} disabled={submitting} onChange={e=>{setEngine(e.target.value as typeof engine);if(e.target.value!=='mineru')setDevice('cpu')}}><option value="native">原生解析</option><option value="paddleocr">PaddleOCR · 文字识别</option><option value="paddleocr_vl">PaddleOCR-VL-1.6 · 文档大模型</option><option value="mineru">MinerU · 版面结构</option></select></label><label>设备<select aria-label="解析设备" value={device} disabled={submitting} onChange={e=>setDevice(e.target.value as typeof device)}><option value="cpu">CPU</option><option value="gpu" disabled={engine!=='mineru'}>GPU · MinerU</option></select></label></div>
  
  <button className="small-button" disabled={submitting||Boolean(error)||loading||snapshots.some(s=>parseInProgress(s.status))} onClick={()=>void submit()}>{submitting?<Busy>提交中</Busy>:submitError?'重试同一解析请求':'创建解析快照'}</button>
  {snapshots.some(s=>parseInProgress(s.status))&&<p className="muted">解析中</p>}
  {message&&<p role="status">{message}</p>}{submitError&&<ErrorBox error={submitError}/>}
 </details>;
}
