import {useEffect,useState} from 'react';
import {api,errorMessage,key} from '../api';
import {Busy,ErrorBox} from '../ui';
import {Code2,ThumbsDown,ThumbsUp} from '../icons';
import {RunDetail} from '../RunPanel';
import type {Evidence,Paper} from '../types';
type State={profile:null|{query:string;interval_hours:number;enabled:number};suggested_query:string;latest:null|{results:Paper[];searched_at:number;scope_notice:string}};
export function Recommendations({onEvidence}:{onEvidence?:(e:Evidence)=>void}){
 const [state,setState]=useState<State|null>(null),[query,setQuery]=useState(''),[interval,setInterval]=useState(24),[enabled,setEnabled]=useState(false),[rid,setRid]=useState<string|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 async function load(){try{const s=await api<State>('/recommendations');setState(s);setQuery(s.profile?.query??s.suggested_query);setInterval(s.profile?.interval_hours??24);setEnabled(Boolean(s.profile?.enabled))}catch(e){setError(errorMessage(e))}}
 useEffect(()=>{void load()},[]);
 async function save(refresh=false){setBusy(true);setError('');try{await api('/recommendations/config',{query,interval_hours:interval,enabled});if(refresh){const r=await api<{id:string}>('/recommendations/refresh',{});setRid(r.id)}await load()}catch(e){setError(errorMessage(e))}finally{setBusy(false)}}
 async function vote(identity:string,value:number){try{await api('/feedback',{identity,value});await load()}catch(e){setError(errorMessage(e))}}
 return <section className="rec-panel"><h2>推荐</h2><div className="rec-form"><input aria-label="兴趣关键词" placeholder="关键词" value={query} onChange={e=>setQuery(e.target.value)}/><select aria-label="推荐频率" value={interval} onChange={e=>setInterval(Number(e.target.value))}><option value={24}>每天</option><option value={168}>每周</option></select><label><input type="checkbox" checked={enabled} onChange={e=>setEnabled(e.target.checked)}/>定时</label><button disabled={busy} className="secondary-button" onClick={()=>void save()}>保存</button><button disabled={busy} className="primary-button" onClick={()=>void save(true)}>{busy?<Busy>{''}</Busy>:'获取'}</button></div>{error&&<ErrorBox error={error}/>} {rid&&<RunDetail runId={rid} onEvidence={onEvidence??(()=>{})} onUpdate={load}/>}
 <div className="rec-list">{state?.latest?.results.map(p=>{const clue=Boolean((p as unknown as {code_clues?:string[]}).code_clues?.length);return <article key={p.identity}><a href={p.url} target="_blank" rel="noreferrer">{p.title}</a><p title={p.reason}>{p.reason}</p><footer>{clue&&<span><Code2 size={13}/>代码线索</span>}<button className="icon-button" aria-label={`感兴趣：${p.title}`} onClick={()=>void vote(p.identity,1)}><ThumbsUp size={14}/></button><button className="icon-button" aria-label={`不感兴趣：${p.title}`} onClick={()=>void vote(p.identity,-1)}><ThumbsDown size={14}/></button></footer></article>})}</div></section>;
}
