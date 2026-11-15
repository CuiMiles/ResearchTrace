import { Component, type ReactNode, useState } from 'react';
import { AlertCircle, Check, FileText, LoaderCircle, X, ChevronDown } from './icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
export const statusLabel:Record<string,string>={queued:'等待处理',running:'正在执行',completed:'已完成',ready:'可阅读',partial:'部分完成',failed:'执行失败',cancelled:'已取消',waiting_for_user:'需要配置',parsing:'正在解析',blocked:'受阻',pending:'待处理',indexed:'已索引'};
export function Badge({status,children}:{status?:string;children?:ReactNode}){return <span className={`badge ${status??''}`}>{children??statusLabel[status??'']??status}</span>}
export function Empty({title,children,icon}:{title:string;children?:ReactNode;icon?:ReactNode}){return <div className="empty-state">{icon??<FileText size={34} strokeWidth={1.3}/>}<h3>{title}</h3><div>{children}</div></div>}
export function ErrorBox({error,onClose}:{error:string;onClose?:()=>void}){return <div role="alert" className="error-box"><AlertCircle size={17}/><span>{error}</span>{onClose&&<button className="icon-button" aria-label="关闭错误提示" onClick={onClose}><X size={16}/></button>}</div>}
export function Busy({children='正在处理…'}:{children?:ReactNode}){return <span className="busy"><LoaderCircle size={16} className="spin"/>{children}</span>}
export function Markdown({children}:{children:string}){return <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm,remarkMath]} rehypePlugins={[rehypeKatex]} components={{a:({children,href})=><a href={href?.startsWith('https://')||href?.startsWith('http://')||href?.startsWith('/api/')?href:undefined} target="_blank" rel="noopener noreferrer">{children}</a>}}>{children}</ReactMarkdown></div>}
export class Boundary extends Component<{children:ReactNode},{error:string}> {state={error:''};static getDerivedStateFromError(error:Error){return {error:error.message}}render(){return this.state.error?<ErrorBox error={`此面板无法显示：${this.state.error}`}/>:this.props.children}}
export function Disclosure({title,children,initial=false}:{title:string;children:ReactNode;initial?:boolean}){const [open,setOpen]=useState(initial);return <section className="disclosure"><button aria-expanded={open} onClick={()=>setOpen(!open)}><span>{title}</span><ChevronDown size={15} className={open?'flipped':''}/></button>{open&&children}</section>}
export function Saved({children}:{children:ReactNode}){return <span className="success-note"><Check size={14}/>{children}</span>}
