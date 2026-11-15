# Contract v1 (backend OpenAPI is authoritative)

All endpoints use `/api/v1`. A server session cookie maps to an isolated workspace.
Login `POST /auth/login {code:string, workspace?:string}` returns `{workspace,role}`.
GET /auth/session. POST /auth/logout. 401 before login. Admin code distinct.

JSON timestamps are Unix seconds. Physical `page_index` is ZERO based everywhere.
Bboxes are `[x0,top,x1,bottom]` NORMALIZED to the visible crop, after rotation, origin top left. PDF.js overlay uses the same page viewport percentages.
JSON columns serialized on the wire. IDs opaque. Version immutable; deletion is soft.

GET /documents → Version[]. POST /documents multipart `files` → `{documents:Version[],runs:RunRef[]}`. Duplicate returns original, `duplicate:true`.
Version: `{id,work_id,title,filename,sha256,status,page_count,parsed_pages,dense_pages,label,metadata,created}`.
GET /documents/{id}/status → Version. GET /documents/{id}/file → PDF.
GET /documents/{id}/pages/{page_index} → `{page_index,label,width,height,rotation,blocks:Block[]}`.
GET /documents/{id}/blocks?offset=0&limit=100&page_index=0 → Block[]. GET /documents/{id}/references → Ref[].
Block `{id,version_id,page_index,bbox:number[],type,reading_order,text,source,quality,metadata}`.
PATCH /documents/{id} `{title?,tags?,work_id?}`. DELETE /documents/{id}.
POST /versions/compare `{left:string,right:string}` → `{changes:[{kind,before?,after?}],...}`.
POST /qa/runs `{question,version_ids:string[],idempotency_key:string}` → RunRef.
GET /agent/tools → `{tools,max_steps,provider_budget,notice}`.
POST /agent/runs same, performs evidence constrained comparison or writing.
POST /translations `{version_id,block_ids?:string[],idempotency_key}` → RunRef.
GET /translations/{version_id} → `{block_id,text,model}[]`. GET /translations/{version_id}/export?format=md|html.
GET /runs/{id} → `{id,kind,status,payload,result,error,created,updated,steps:Step[]}`.
Step `{id,event,data,created}`. result for QA `{answer,claims:[{text,type,evidence:[{block_id,version_id,page_index,bbox,quote,status}]}],model,retrieval,artifact_id}`.
GET /runs/{id}/events?after=0 → SSE ordered persistent step events, id event sequence. Last-Event-ID supported. Steps represent real tool progress; no simulated tokens.
POST /runs/{id}/cancel. POST /runs/{id}/resume.
GET /runs → latest 40 runs.
POST /search `{query,sources?:['arxiv','crossref'],limit?:20}` → `{results:Paper[],errors:[],cached:boolean,searched_at:number}`.
Paper `{identity,title,authors:string[],year,doi?,arxiv_id?,url,pdf_url?,source,abstract?,reason?}`.
POST /search/import `{paper:Paper}` → metadata Work + optional PDF run, only public URLs; unavailable full text explicit.
POST /feedback `{identity,value:1|-1|0}`. POST /watch-queries `{query,enabled:false,interval_hours:24}`. GET /watch-queries; POST /watch-queries/{id}/check; PATCH /watch-queries/{id} `{enabled}`.
POST /graphs `{}` → `{nodes:[{id,title,rank,indegree}],edges:[{source,target,ref_id,text,version_id,page_index}],scope}`. Graph derived from REAL parsed references only.
POST /ideas/audits `{version_id,block_id,question,idempotency_key}` → RunRef.
POST /charts multipart `file`, `spec` JSON `{kind:'line'|'bar'|'radar'|'3d',x?:string,y?:string[],z?:string,title?:string,x_unit?:string,y_unit?:string,aggregate?:'none'|'mean'|'sum'}` → `{artifact_id,columns,statistics,warnings,caption,files:{png,svg,script,spec,csv}}`. Files are authenticated `/artifacts/{id}/files/{name}` URLs.
GET /artifacts → Artifact[]. GET /artifacts/{id} → Artifact. GET /artifacts/{id}/export?format=md|html|bib.
GET /admin/providers → redacted configuration + local usage; admin only.

Internal modules: `store.py` owns schema/helpers `db,one,rows,execute,uid,event,cancelled,artifact,DATA`. Functions synchronous, worker runs outside async API loop.
documents.py exports `parse_document(run:dict)->dict`, `upload_document(workspace,filename,content:bytes)->dict`, `compare_versions(workspace,left,right)->dict`. Upload returns `{document,run_id?,duplicate}`; creates parse run. Parser updates page checkpoints.
retrieval.py exports `retrieve(workspace,version_ids,question,limit=16)->dict {blocks:[],sparse:[],dense:[],mode}`, `index_dense(workspace,version_id,run_id)->dict` via models.embed(texts,run_id) if available.
research.py exports `search_papers(workspace,query,sources=None,limit=10)->dict`, `import_paper(workspace,paper)->dict`, `build_graph(workspace)->dict`, `check_watch(workspace,watch_id)->dict`.
charts.py exports `create_chart(workspace,filename,content,spec)->dict`, `artifact_file(workspace,artifact_id,name)->Path`.
models.py exports `generate(system,prompt,run_id,core=True)->dict {text,model,usage,project}` and `embed(texts,run_id,task='RETRIEVAL_DOCUMENT')->dict {vectors,model,dimension}`. Raises safe ModelError; no secret messages.


Ubuntu 24 parser revisions (2026-11-15):
- `POST /documents?index_dense=false` imports without spending embedding quota; default remains true.
- `GET /documents/{vid}/parses` returns `{id,version_id,engine,device,status,parsed_pages,page_count,error,created,active,provenance}[]`.
- `POST /documents/{vid}/parses {engine:native|paddleocr|mineru,device:cpu|gpu,idempotency_key}` returns `{id:run_id,run_id,parse_id,status}`. GPU is supported only for MinerU; server applies live resource guards.
- Pages, blocks, search and references accept optional `parse_id`. Omission reads the active revision. Full successful parsing publishes a new current revision atomically; partial/failed revisions do not displace it.
- Existing versions, source bytes, block IDs, text, bbox, translations, embeddings and historic evidence stay unchanged. Native legacy revisions use the existing version ID as parse ID. New blocks keep the original version ID, and use the independent parse ID in their opaque block ID.
- Returned blocks and run evidence contain `parse_id`, including legacy stored run evidence enriched by its immutable block identity. Queries and bibliography graph use current revisions; old reader routes remain available within the same workspace.
- Reparse does not automatically spend embedding quota. Coverage resets honestly to zero for the new active revision; old vectors remain bound to old block IDs.
- Enhanced workers are optional, Unix-socket only, no model credentials inherited. Broker health is liveness; offline preflight is not proof of inference.
