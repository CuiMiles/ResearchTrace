export class ApiError extends Error { constructor(public status:number,message:string){super(message)} }
export async function api<T>(path:string,body?:unknown,method?:string):Promise<T>{
  const isForm=body instanceof FormData;
  const response=await fetch(`/api/v1${path}`,{method:method??(body===undefined?'GET':'POST'),credentials:'same-origin',headers:body!==undefined&&!isForm?{'Content-Type':'application/json'}:undefined,body:body===undefined?undefined:isForm?body:JSON.stringify(body)});
  if(!response.ok){let message=`请求失败（${response.status}）`;try{const e=await response.json();message=typeof e.detail==='string'?e.detail:JSON.stringify(e.detail??e.error??message)}catch{/* HTTP status retained */}throw new ApiError(response.status,message)}
  if(response.status===204)return undefined as T;
  return response.json() as Promise<T>;
}
export const endpoint=(path:string)=>`/api/v1${path}`;
export function parseObject<T>(value:unknown,fallback:T):T{if(typeof value==='string'){try{return JSON.parse(value) as T}catch{return fallback}}return (value??fallback) as T}
export const key=()=>crypto.randomUUID();
export const date=(value?:number)=>value?new Date(value*1000).toLocaleString('zh-CN',{hour12:false}):'尚未执行';
export const errorMessage=(error:unknown)=>error instanceof Error?error.message:String(error);

export async function documentBlocks(versionId:string,max=2000){
 const pages=await Promise.all(Array.from({length:Math.ceil(max/500)},(_,i)=>api<import('./types').Block[]>(`/documents/${versionId}/blocks?offset=${i*500}&limit=500`)));
 return pages.flat();
}
