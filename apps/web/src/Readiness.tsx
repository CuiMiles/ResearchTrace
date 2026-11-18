import { useEffect,useState } from 'react';
import { api,errorMessage } from './api';
import { ErrorBox } from './ui';
const STATES:Record<string,[string,string]>={PASS:['正常','ok'],FAIL:['异常','bad'],BLOCKED:['未启用','off'],'NOT RUN':['未检查','off']};
type Report={checked_at:number;provider_calls:number;components:Record<string,{status:string;reason?:string;indexed_blocks?:number;eligible_blocks?:number}>};
export function Readiness(){
 const [report,setReport]=useState<Report|null>(null);const [error,setError]=useState('');
 useEffect(()=>{let live=true;const load=async()=>{try{const value=await api<Report>('/readiness');if(live){setReport(value);setError('')}}catch(e){if(live)setError(errorMessage(e))}};void load();const timer=setInterval(()=>void load(),15000);return()=>{live=false;clearInterval(timer)}},[]);
 const labels:Record<string,string>={database:'文献与记录',worker_documents:'文档处理',worker_interactive:'交互任务',local_models:'本地检索模型',index:'全文语义索引',analysis:'核心分析',public_https:'外网评审入口'};
 if(!report&&!error)return null;
 return <section aria-label="实时服务状态"><h2>运行状态</h2>{error&&<ErrorBox error={error}/>}<div className="service-readiness">{report&&Object.entries(report.components).map(([key,item])=>{const [label,tone]=STATES[item.status]??[item.status,'off'];return <div key={key} title={item.reason}><strong>{labels[key]??key}</strong>{key==='index'&&<small>{item.indexed_blocks}/{item.eligible_blocks}</small>}<span className={`state ${tone}`}>{label}</span></div>})}</div></section>
}
