"""Copy a prepared corpus and its actual vectors into an isolated reviewer space."""
import json
import time

from . import store

TABLES=('works','versions','parses','pages','blocks','block_parses','parse_pages','active_parses','refs',
        'embeddings','index_generations','retrieval_chunks','retrieval_spans','retrieval_vectors','active_retrieval_indices')
# Finished results that a guest may browse as saved history (never the quota ledger).
SHOWCASE=('runs','steps','claims','evidence','artifacts','translation_cache','citation_edges','document_cards',
          'document_version_choices','document_work_selections')
SHOWCASE_KINDS=('qa','agent','writing','version_summary','version_impact','translate','text_translation',
                'idea_audit','audit','research_note','chart')


def clone(source,target,connection=None,index_models=None,showcase=False):
    """Copy the corpus; `index_models` limits copied vector generations to those model ids.

    Guests receive only the compact cloud index (e.g. 768-d Gemini vectors),
    never the large local 4096-d generations, so each guest space stays small.
    `showcase` also copies finished runs (answers, claims, evidence, artifacts and
    cached translations) as saved history, re-keyed to the copied corpus and
    marked with `payload.showcase_copy`; quota rows are never copied.
    """
    if source==target:raise ValueError('种子来源和目标空间必须不同')
    if connection is None:
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            return clone(source,target,c,index_models,showcase)
    c=connection
    if not c.execute('SELECT id FROM workspaces WHERE id=?',(source,)).fetchone():raise ValueError('种子工作区不存在')
    if not c.execute('SELECT id FROM workspaces WHERE id=?',(target,)).fetchone():raise ValueError('目标工作区不存在')
    if c.execute('SELECT 1 FROM versions WHERE workspace=?',(target,)).fetchone():raise ValueError('仅能给空白评审空间复制种子资料')
    model_args=tuple(index_models or ())
    if index_models is not None and not model_args:raise ValueError('需要至少一个可复制的索引模型')
    model_filter=(' AND model_id IN ('+','.join('?' for _ in model_args)+')') if index_models is not None else ''
    # Only corpus-owned rows; never copy sessions, invitation codes, quota,
    # tasks, answers or private historical notes into another identity.
    queries={
        'works':('workspace=?',(source,)), 'versions':('workspace=? AND deleted=0',(source,)),
        'parses':('workspace=? AND version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0)',(source,source)),
        'pages':('version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0)',(source,)),
        'blocks':('workspace=? AND version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0)',(source,source)),
        # Deleted versions keep their blocks and parse links; only live ones are copied.
        'block_parses':('block_id IN (SELECT id FROM blocks WHERE workspace=? AND version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0))',(source,source)),
        'parse_pages':('version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0)',(source,)),
        'active_parses':('version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0)',(source,)),
        'refs':('workspace=? AND version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0)',(source,source)),
        'embeddings':('workspace=? AND version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0)',(source,source)),
        'index_generations':("workspace=? AND status='ready'"+model_filter,(source,*model_args)),
        'retrieval_chunks':("workspace=? AND version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0) AND generation_id IN (SELECT id FROM index_generations WHERE workspace=? AND status='ready'"+model_filter+")",(source,source,source,*model_args)),
        'retrieval_spans':("chunk_id IN (SELECT id FROM retrieval_chunks WHERE workspace=? AND version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0) AND generation_id IN (SELECT id FROM index_generations WHERE workspace=? AND status='ready'"+model_filter+"))",(source,source,source,*model_args)),
        'retrieval_vectors':("chunk_id IN (SELECT id FROM retrieval_chunks WHERE workspace=? AND version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0) AND generation_id IN (SELECT id FROM index_generations WHERE workspace=? AND status='ready'"+model_filter+"))",(source,source,source,*model_args)),
        'active_retrieval_indices':("workspace=? AND version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0) AND generation_id IN (SELECT id FROM index_generations WHERE workspace=? AND status='ready'"+model_filter+")",(source,source,source,*model_args)),
    }
    if showcase:
        kinds=','.join('?' for _ in SHOWCASE_KINDS)
        runs=f"SELECT id FROM runs WHERE workspace=? AND status IN ('completed','partial') AND kind IN ({kinds})"
        rargs=(source,*SHOWCASE_KINDS)
        live="SELECT id FROM versions WHERE workspace=? AND deleted=0"
        queries.update({
            'runs':(f'id IN ({runs})',rargs),
            'steps':(f'run_id IN ({runs})',rargs),
            'claims':(f'workspace=? AND run_id IN ({runs})',(source,*rargs)),
            'evidence':(f'workspace=? AND claim_id IN (SELECT id FROM claims WHERE workspace=? AND run_id IN ({runs}))',(source,source,*rargs)),
            'artifacts':(f'workspace=? AND (run_id IS NULL OR run_id IN ({runs}))',(source,*rargs)),
            'translation_cache':(f'workspace=? AND version_id IN ({live})',(source,source)),
            'citation_edges':('workspace=?',(source,)),
            'document_cards':(f'workspace=? AND version_id IN ({live})',(source,source)),
            'document_version_choices':(f'workspace=? AND version_id IN ({live})',(source,source)),
            'document_work_selections':('workspace=?',(source,)),
        })
    if index_models is not None:
        # The legacy per-block embedding table follows the same model filter.
        where,args=queries['embeddings']
        queries['embeddings']=(where+' AND model IN ('+','.join('?' for _ in model_args)+')',(*args,*model_args))
    # Vector BLOBs can exceed the API's entire memory allowance. IDs and source
    # mappings are small; copy both vector stores with a bounded cursor instead
    # of retaining every BLOB in a Python list at once.
    streamed={'embeddings','retrieval_vectors','steps','translation_cache'}
    records={table:[dict(r) for r in c.execute('SELECT * FROM '+table+' WHERE '+where,args).fetchall()]
             for table,(where,args) in queries.items() if table not in streamed}
    def source_rows(table):
        if table not in streamed:
            yield from records[table]
            return
        where,args=queries[table]
        cursor=c.execute('SELECT * FROM '+table+' WHERE '+where,args)
        while batch:=cursor.fetchmany(64):
            yield from (dict(row) for row in batch)
    ids={source:target}
    for table in ('works','versions','parses','index_generations','retrieval_chunks')+(('runs','claims','evidence','artifacts','citation_edges') if showcase else ()):
        for row in records[table]:ids.setdefault(row['id'],store.uid())
    for row in records['blocks']:
        bid=row['id'];vid=row['version_id']
        ids[bid]=ids[vid]+bid[len(vid):] if bid.startswith(vid+':') else store.uid()
    for row in records['refs']:ids[row['id']]=store.uid()
    def replace(value):
        if isinstance(value,dict):return {key:replace(item) for key,item in value.items()}
        if isinstance(value,list):return [replace(item) for item in value]
        if isinstance(value,str):
            if value in ids:return ids[value]
            if value.startswith(('{','[')):
                try:return json.dumps(replace(json.loads(value)),ensure_ascii=False)
                except ValueError:pass
        return value
    counts={}
    for table in TABLES+(SHOWCASE if showcase else ()):
        count=0
        for row in source_rows(table):
            # Bytes paths and source text are immutable content, not IDs.
            copied={key:value if key in ('path','text','retrieval_text','vector','sha256','filename','title','quote') else replace(value) for key,value in row.items()}
            if table=='steps':copied.pop('id',None)
            if table=='runs':
                payload=json.loads(copied['payload'] or '{}')
                payload['showcase_copy']={'copied_at':time.time()}
                copied['payload']=json.dumps(payload,ensure_ascii=False)
            if table=='index_generations':
                manifest=json.loads(copied['manifest'])
                manifest['seed_copy']={'copied_at':time.time(),'vectors_recomputed':False}
                copied['manifest']=json.dumps(manifest,ensure_ascii=False)
            columns=list(copied)
            c.execute('INSERT INTO '+table+' ('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',tuple(copied.values()))
            count+=1
        counts[table]=count
    return {'source_workspace':source,'target_workspace':target,'counts':counts,'provider_calls':0,
            'index_models':list(model_args) if index_models is not None else 'all',
            'vectors_recomputed':False,'isolated_ids':True,'historical_answers_copied':bool(showcase),
            'vector_copy_batch':64}
