import {useEffect,useState} from 'react';
import {api,errorMessage,key} from '../api';
import {Busy,ErrorBox} from '../ui';
import {RunDetail} from '../RunPanel';
import type {Evidence,Paper} from '../types';
type State={profile:null|{query:string;interval_hours:number;enabled:number};suggested_query:string;latest:null|{results:Paper[];searched_at:number;scope_notice:string}};
export function Recommendations({onEvidence}:{onEvidence?:(e:Evidence)=>void}){
 const [state,setState]=useState<State|null>(null),[query,setQuery]=useState(''),[interval,setInterval]=useState(24),[enabled,setEnabled]=useState(false),[rid,setRid]=useState<string|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 async function load(){try{const s=await api<State>('/recommendations');setState(s);setQuery(s.profile?.query??s.suggested_query);setInterval(s.profile?.interval_hours??24);setEnabled(Boolean(s.profile?.enabled))}catch(e){setError(errorMessage(e))}}
 useEffect(()=>{void load()},[]);
 async function save(refresh=false){setBusy(true);setError('');try{await api('/recommendations/config',{query,interval_hours:interval,enabled});if(refresh){const r=await api<{id:string}>('/recommendations/refresh',{});setRid(r.id)}await load()}catch(e){setError(errorMessage(e))}finally{setBusy(false)}}
 async function vote(identity:string,value:number){try{await api('/feedback',{identity,value});await load()}catch(e){setError(errorMessage(e))}}
 return <section className="compose-block"><h2>每日 / 每周新论文推荐</h2><p>依据文献库主题查找最新 arXiv 元数据，以摘要说明推荐理由。代码链接只是待验证线索。</p><label>兴趣关键词<input value={query} onChange={e=>setQuery(e.target.value)}/></label><label>推荐频率<select value={interval} onChange={e=>setInterval(Number(e.target.value))}><option value={24}>每天</option><option value={168}>每周</option></select></label><label><input type="checkbox" checked={enabled} onChange={e=>setEnabled(e.target.checked)}/>开启定时推荐</label><button disabled={busy} className="secondary-button" onClick={()=>void save()}>保存设置</button><button disabled={busy} className="primary-button" onClick={()=>void save(true)}>{busy?<Busy/>:'获取本次推荐'}</button>{error&&<ErrorBox error={error}/>} {rid&&<RunDetail runId={rid} onEvidence={onEvidence??(()=>{})} onUpdate={load}/>}
 {state?.latest?.results.map(p=><article className="paper-result" key={p.identity}><a href={p.url} target="_blank" rel="noreferrer">{p.title}</a><p>{p.reason}</p><small>{String((p as unknown as {code_clues?:string[]}).code_clues?.length?'摘要 / comments 含代码线索':'未在摘要 / comments 发现代码')}</small><div><button className="text-button" onClick={()=>void vote(p.identity,1)}>感兴趣</button><button className="text-button" onClick={()=>void vote(p.identity,-1)}>不感兴趣</button></div></article>)}</section>;
}
