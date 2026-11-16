"""Copy a prepared corpus and its actual vectors into an isolated reviewer space."""
import json
import time

from . import store

TABLES=('works','versions','parses','pages','blocks','block_parses','parse_pages','active_parses','refs',
        'embeddings','index_generations','retrieval_chunks','retrieval_spans','retrieval_vectors','active_retrieval_indices')


def clone(source,target,connection=None):
    if source==target:raise ValueError('种子来源和目标空间必须不同')
    if connection is None:
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            return clone(source,target,c)
    c=connection
    if not c.execute('SELECT id FROM workspaces WHERE id=?',(source,)).fetchone():raise ValueError('种子工作区不存在')
    if not c.execute('SELECT id FROM workspaces WHERE id=?',(target,)).fetchone():raise ValueError('目标工作区不存在')
    if c.execute('SELECT 1 FROM versions WHERE workspace=?',(target,)).fetchone():raise ValueError('仅能给空白评审空间复制种子资料')
    # Only corpus-owned rows; never copy sessions, invitation codes, quota,
    # tasks, answers or private historical notes into another identity.
    queries={
        'works':('workspace=?',(source,)), 'versions':('workspace=? AND deleted=0',(source,)),
        'parses':('workspace=? AND version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0)',(source,source)),
        'pages':('version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0)',(source,)),
        'blocks':('workspace=? AND version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0)',(source,source)),
        'block_parses':('block_id IN (SELECT id FROM blocks WHERE workspace=?)',(source,)),
        'parse_pages':('version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0)',(source,)),
        'active_parses':('version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0)',(source,)),
        'refs':('workspace=? AND version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0)',(source,source)),
        'embeddings':('workspace=? AND version_id IN (SELECT id FROM versions WHERE workspace=? AND deleted=0)',(source,source)),
        'index_generations':("workspace=? AND status='ready'",(source,)),
        'retrieval_chunks':("workspace=? AND generation_id IN (SELECT id FROM index_generations WHERE workspace=? AND status='ready')",(source,source)),
        'retrieval_spans':("chunk_id IN (SELECT id FROM retrieval_chunks WHERE workspace=? AND generation_id IN (SELECT id FROM index_generations WHERE workspace=? AND status='ready'))",(source,source)),
        'retrieval_vectors':("chunk_id IN (SELECT id FROM retrieval_chunks WHERE workspace=? AND generation_id IN (SELECT id FROM index_generations WHERE workspace=? AND status='ready'))",(source,source)),
        'active_retrieval_indices':("workspace=? AND generation_id IN (SELECT id FROM index_generations WHERE workspace=? AND status='ready')",(source,source)),
    }
    records={table:[dict(r) for r in c.execute('SELECT * FROM '+table+' WHERE '+where,args).fetchall()]
             for table,(where,args) in queries.items()}
    ids={source:target}
    for table in ('works','versions','parses','index_generations','retrieval_chunks'):
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
    for table in TABLES:
        count=0
        for row in records[table]:
            # Bytes paths and source text are immutable content, not IDs.
            copied={key:value if key in ('path','text','retrieval_text','vector','sha256','filename','title') else replace(value) for key,value in row.items()}
            if table=='index_generations':
                manifest=json.loads(copied['manifest'])
                manifest['seed_copy']={'copied_at':time.time(),'vectors_recomputed':False}
                copied['manifest']=json.dumps(manifest,ensure_ascii=False)
            columns=list(copied)
            c.execute('INSERT INTO '+table+' ('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',tuple(copied.values()))
            count+=1
        counts[table]=count
    return {'source_workspace':source,'target_workspace':target,'counts':counts,'provider_calls':0,
            'vectors_recomputed':False,'isolated_ids':True,'historical_answers_copied':False}
