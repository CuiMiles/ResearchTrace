export type Json = Record<string, unknown>;
export interface Session { workspace: string; role: string; }
export interface Version { id:string; work_id:string; title:string; filename:string; sha256:string; status:string; page_count:number; parsed_pages:number; dense_pages:number; label:string; metadata:Json; created:number; duplicate?:boolean; local_index?:{semantic_ready:boolean;indexed_blocks:number;eligible_blocks:number;status:string;model_id:string} }
export interface ParseSnapshot { id:string; engine:string; device?:string; status:string; active?:boolean|number; parsed_pages?:number; page_count?:number; created?:number; error?:string|null }
export interface Block { parse_id?:string; id:string; version_id:string; page_index:number; bbox:number[]; type:string; reading_order:number; text:string; source:string; quality:string; metadata:Json }
export interface Page { page_index:number; label?:string; status?:string; width:number; height:number; rotation:number; blocks:Block[] }
export interface Evidence { parse_id?:string; block_id:string; version_id:string; page_index:number; bbox:number[]; quote:string; status:string }
export interface Claim { id?:string; text:string; type:string; evidence:Evidence[]; review?:{status:string;label?:string;reason?:string;method?:string;human_status?:string} }
export interface Run { id:string; kind:string; status:string; payload:Json; result:Result|null; error:string|null; created:number; updated:number; steps?:Step[] }
export interface Step { id:number; event:string; data:Json; created:number }
export interface Result extends Json { answer?:string; answer_segments?:{text:string;claim_ids:string[]}[]; claims?:Claim[]; publication_notice?:string; model?:string; artifact_id?:string; retrieval?:Json }
export interface Ref { id:string; block_id:string; version_id:string; marker?:string; text:string; page_index:number; metadata?:Json }
export interface Translation { block_id:string; text:string; model:string }
export interface Paper { identity:string; title:string; authors:string[]; year?:number; doi?:string; arxiv_id?:string; url:string; pdf_url?:string; source:string; abstract?:string; reason?:string; score?:number }
export interface SearchResult { results:Paper[]; errors:unknown[]; cached:boolean; searched_at:number }
export interface Watch { id:string; query:string; enabled:boolean|number; last_checked?:number; next_check?:number; result?:unknown }
export interface GraphNode { id:string; title:string; rank:number; indegree:number }
export interface GraphEdge { source:string; target:string; ref_id:string; text:string; version_id:string|null; page_index:number|null; block_id?:string; metadata_source_url?:string; status?:string }
export interface Graph { nodes:GraphNode[]; edges:GraphEdge[]; scope:unknown }
export interface Artifact { id:string; kind:string; title:string; payload:Json; created:number }
export interface ChartResult { artifact_id:string; columns:unknown; statistics:unknown; warnings:string[]; caption:string; files:Record<string,string> }
export interface Change { kind:string; before?:Block; after?:Block }
