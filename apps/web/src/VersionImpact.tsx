import { useState } from 'react';
import { api,errorMessage } from './api';
import { Badge,ErrorBox } from './ui';
import type { Evidence } from './types';
type Impact={notice:string;unchanged:number;needs_review:number;claims:{artifact_id:string;claim_text:string;status:string;mappings:{status:string;notice:string;new?:Evidence}[]}[]};
export function VersionImpact({selected,onEvidence}:{selected:string[];onEvidence:(e:Evidence)=>void}){
 const [result,setResult]=useState<Impact|null>(null);const [error,setError]=useState('');const [loading,setLoading]=useState(false);
 async function inspect(){setLoading(true);setError('');try{setResult(await api<Impact>('/versions/impact',{left:selected[0],right:selected[1]}))}catch(e){setError(errorMessage(e))}finally{setLoading(false)}}
 return <section><button className="secondary-button" disabled={selected.length!==2||loading} onClick={()=>void inspect()}>{loading?'核对中':'核对旧笔记在新版本中的证据'}</button>{error&&<ErrorBox error={error}/>} {result&&<><p className="info-note">{result.notice}</p><p>原引文仍能定位 {result.unchanged} 项 · 需要复核 {result.needs_review} 项</p>{!result.claims.length&&<p className="muted">当前工作区还没有引用第一个所选版本的历史笔记。</p>}{result.claims.map((claim,i)=><article className="impact-row" key={claim.artifact_id+'-'+i}><Badge>{claim.status==='source_unchanged'?'原引文仍可定位':'需要复核'}</Badge><p>{claim.claim_text}</p>{claim.mappings.map((mapping,j)=><div key={j}><small>{mapping.notice}</small>{mapping.new&&<button className="text-button" onClick={()=>onEvidence(mapping.new!)}>查看新版本原文 · 第 {mapping.new.page_index+1} 页</button>}</div>)}</article>)}</>}</section>
}
