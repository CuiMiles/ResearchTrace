import { useEffect,useState } from 'react';
import { api,errorMessage } from './api';
import { Badge,ErrorBox } from './ui';
type Report={checked_at:number;provider_calls:number;components:Record<string,{status:string;reason?:string;indexed_blocks?:number;eligible_blocks?:number}>};
export function Readiness(){
 const [report,setReport]=useState<Report|null>(null);const [error,setError]=useState('');
 useEffect(()=>{let live=true;const load=async()=>{try{const value=await api<Report>('/readiness');if(live){setReport(value);setError('')}}catch(e){if(live)setError(errorMessage(e))}};void load();const timer=setInterval(()=>void load(),15000);return()=>{live=false;clearInterval(timer)}},[]);
 const labels:Record<string,string>={database:'文献与记录',worker_documents:'文档处理',worker_interactive:'交互任务',local_models:'本地检索模型',index:'全文语义索引',analysis:'核心分析',public_https:'外网评审入口'};
 return <section aria-label="实时服务状态"><h2>运行状态</h2><p className="muted">15 秒刷新，仅检查状态，不调用生成模型。配置存在不代表上游此刻可用。</p>{error&&<ErrorBox error={error}/>}<div className="service-readiness">{report&&Object.entries(report.components).map(([key,item])=><div key={key}><strong>{labels[key]??key}</strong><Badge>{item.status}</Badge>{key==='index'&&<p>{item.indexed_blocks}/{item.eligible_blocks} 块</p>}{item.reason&&<p className="muted">{item.reason}</p>}</div>)}</div></section>
}
