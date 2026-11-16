"""SQLite source of truth. JSON is used for evolving artifact payloads, not secrets."""
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get('RT_DATA_DIR', ROOT / 'data')).resolve()
DATA.mkdir(parents=True, exist_ok=True, mode=0o700)

def uid():
    return uuid.uuid4().hex

@contextmanager
def db():
    conn = sqlite3.connect(DATA / 'researchtrace.sqlite', timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

def migrate():
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY,name TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS works(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,title TEXT NOT NULL,identity TEXT,metadata TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,work_id TEXT,title TEXT NOT NULL,filename TEXT NOT NULL,sha256 TEXT NOT NULL,path TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',page_count INTEGER DEFAULT 0,parsed_pages INTEGER DEFAULT 0,dense_pages INTEGER DEFAULT 0,label TEXT DEFAULT '版本待确认',identity TEXT,metadata TEXT DEFAULT '{}',created REAL NOT NULL,deleted INTEGER DEFAULT 0,UNIQUE(workspace,sha256));
        CREATE TABLE IF NOT EXISTS pages(version_id TEXT NOT NULL,page_index INTEGER NOT NULL,label TEXT,width REAL,height REAL,rotation INTEGER DEFAULT 0,status TEXT,text TEXT,PRIMARY KEY(version_id,page_index));
        CREATE TABLE IF NOT EXISTS blocks(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,version_id TEXT NOT NULL,page_index INTEGER NOT NULL,bbox TEXT NOT NULL,type TEXT NOT NULL,reading_order INTEGER NOT NULL,text TEXT NOT NULL,source TEXT NOT NULL,quality TEXT NOT NULL,metadata TEXT DEFAULT '{}');
        CREATE VIRTUAL TABLE IF NOT EXISTS block_fts USING fts5(id UNINDEXED,text,tokenize='unicode61');
        CREATE TABLE IF NOT EXISTS embeddings(block_id TEXT NOT NULL,workspace TEXT NOT NULL,version_id TEXT NOT NULL,model TEXT NOT NULL,dimension INTEGER NOT NULL,vector BLOB NOT NULL,PRIMARY KEY(block_id,model,dimension));
        CREATE TABLE IF NOT EXISTS refs(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,version_id TEXT NOT NULL,block_id TEXT,page_index INTEGER,marker TEXT,text TEXT NOT NULL,target_identity TEXT,metadata TEXT DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL,result TEXT,error TEXT,checkpoint TEXT DEFAULT '{}',idempotency TEXT,created REAL NOT NULL,updated REAL NOT NULL,UNIQUE(workspace,idempotency));
        CREATE TABLE IF NOT EXISTS steps(id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,event TEXT NOT NULL,data TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS translations(block_id TEXT NOT NULL,workspace TEXT NOT NULL,version_id TEXT NOT NULL,text TEXT NOT NULL,model TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(block_id,workspace));
        CREATE TABLE IF NOT EXISTS claims(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,run_id TEXT NOT NULL,type TEXT NOT NULL,text TEXT NOT NULL,metadata TEXT DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,claim_id TEXT NOT NULL,version_id TEXT NOT NULL,block_id TEXT NOT NULL,page_index INTEGER NOT NULL,quote TEXT NOT NULL,status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,run_id TEXT,kind TEXT NOT NULL,title TEXT NOT NULL,payload TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS quota(id TEXT PRIMARY KEY,project TEXT NOT NULL,model TEXT NOT NULL,day TEXT NOT NULL,run_id TEXT,started REAL NOT NULL,input_tokens INTEGER NOT NULL,output_tokens INTEGER DEFAULT 0,status TEXT NOT NULL,usage TEXT DEFAULT '{}');
        CREATE INDEX IF NOT EXISTS quota_window ON quota(project,model,started);
        CREATE TABLE IF NOT EXISTS provider_state(project TEXT NOT NULL,model TEXT NOT NULL,status TEXT NOT NULL,detail TEXT,updated REAL NOT NULL,PRIMARY KEY(project,model));
        CREATE TABLE IF NOT EXISTS watches(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,query TEXT NOT NULL,enabled INTEGER DEFAULT 0,interval_hours REAL DEFAULT 24,last_checked REAL,next_check REAL,result TEXT DEFAULT '[]');
        CREATE TABLE IF NOT EXISTS feedback(workspace TEXT NOT NULL,identity TEXT NOT NULL,value INTEGER NOT NULL,PRIMARY KEY(workspace,identity));
        CREATE TABLE IF NOT EXISTS search_cache(key TEXT PRIMARY KEY,payload TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS citation_edges(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,source_work TEXT NOT NULL,target_work TEXT NOT NULL,ref_id TEXT NOT NULL,method TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,applied REAL NOT NULL);
        ''')
        c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(1,?)',(time.time(),))
        # A document's bytes and its parser revisions have independent identities.
        # Existing block IDs remain the legacy revision; migration never rewrites them.
        c.executescript('''
        CREATE TABLE IF NOT EXISTS parses(id TEXT PRIMARY KEY,version_id TEXT NOT NULL,workspace TEXT NOT NULL,engine TEXT NOT NULL,device TEXT NOT NULL,status TEXT NOT NULL,parsed_pages INTEGER DEFAULT 0,page_count INTEGER NOT NULL,error TEXT,created REAL NOT NULL,provenance TEXT DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS active_parses(version_id TEXT PRIMARY KEY,parse_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS block_parses(block_id TEXT PRIMARY KEY,parse_id TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS block_parse_lookup ON block_parses(parse_id);
        CREATE TABLE IF NOT EXISTS parse_pages(parse_id TEXT NOT NULL,version_id TEXT NOT NULL,page_index INTEGER NOT NULL,label TEXT,width REAL,height REAL,rotation INTEGER,status TEXT,text TEXT,PRIMARY KEY(parse_id,page_index));
        CREATE VIEW IF NOT EXISTS current_blocks AS SELECT b.*,COALESCE(bp.parse_id,b.version_id) AS parse_id FROM blocks b LEFT JOIN block_parses bp ON bp.block_id=b.id LEFT JOIN active_parses a ON a.version_id=b.version_id WHERE COALESCE(bp.parse_id,b.version_id)=COALESCE(a.parse_id,b.version_id);
        CREATE VIEW IF NOT EXISTS current_pages AS SELECT p.*,p.version_id AS parse_id FROM pages p LEFT JOIN active_parses a ON a.version_id=p.version_id WHERE COALESCE(a.parse_id,p.version_id)=p.version_id UNION ALL SELECT p.version_id,p.page_index,p.label,p.width,p.height,p.rotation,p.status,p.text,p.parse_id FROM parse_pages p JOIN active_parses a ON a.parse_id=p.parse_id;
        ''')
        c.execute("INSERT OR IGNORE INTO parses(id,version_id,workspace,engine,device,status,parsed_pages,page_count,created) SELECT id,id,workspace,'native','cpu',status,parsed_pages,page_count,created FROM versions")
        c.execute('INSERT OR IGNORE INTO active_parses SELECT id,id FROM versions')
        c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(2,?)',(time.time(),))
        c.executescript('''
        CREATE TABLE IF NOT EXISTS quota_context(quota_id TEXT PRIMARY KEY REFERENCES quota(id),profile TEXT NOT NULL CHECK(profile IN ('smoke','evaluation','judging')),workflow_limit INTEGER NOT NULL CHECK(workflow_limit>=1));
        CREATE TABLE IF NOT EXISTS import_batches(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,status TEXT NOT NULL,index_dense INTEGER NOT NULL,created REAL NOT NULL,updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS batch_items(id TEXT PRIMARY KEY,batch_id TEXT NOT NULL,workspace TEXT NOT NULL,ordinal INTEGER NOT NULL,filename TEXT NOT NULL,status TEXT NOT NULL,sha256 TEXT,version_id TEXT,run_id TEXT,owns_run INTEGER NOT NULL DEFAULT 0,duplicate INTEGER NOT NULL DEFAULT 0,error TEXT,created REAL NOT NULL,updated REAL NOT NULL,UNIQUE(batch_id,ordinal));
        CREATE INDEX IF NOT EXISTS import_batches_workspace ON import_batches(workspace,created);
        CREATE INDEX IF NOT EXISTS batch_items_order ON batch_items(batch_id,ordinal);
        CREATE INDEX IF NOT EXISTS batch_items_admission ON batch_items(status,created);
        ''')
        c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(3,?)',(time.time(),))
        c.executescript('''
        CREATE TABLE IF NOT EXISTS index_generations(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,model_id TEXT NOT NULL,revision TEXT NOT NULL,fingerprint TEXT NOT NULL,manifest TEXT NOT NULL,status TEXT NOT NULL,expected_blocks INTEGER NOT NULL DEFAULT 0,covered_blocks INTEGER NOT NULL DEFAULT 0,excluded_blocks INTEGER NOT NULL DEFAULT 0,chunk_count INTEGER NOT NULL DEFAULT 0,vector_count INTEGER NOT NULL DEFAULT 0,dimension INTEGER NOT NULL,created REAL NOT NULL,activated REAL,error TEXT);
        CREATE TABLE IF NOT EXISTS retrieval_chunks(id TEXT PRIMARY KEY,generation_id TEXT NOT NULL REFERENCES index_generations(id),workspace TEXT NOT NULL,version_id TEXT NOT NULL,parse_id TEXT NOT NULL,ordinal INTEGER NOT NULL,text TEXT NOT NULL,retrieval_text TEXT NOT NULL,token_count INTEGER NOT NULL,kind TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS retrieval_spans(chunk_id TEXT NOT NULL REFERENCES retrieval_chunks(id),block_id TEXT NOT NULL,start INTEGER NOT NULL,end INTEGER NOT NULL,PRIMARY KEY(chunk_id,block_id,start,end));
        CREATE TABLE IF NOT EXISTS retrieval_vectors(chunk_id TEXT PRIMARY KEY REFERENCES retrieval_chunks(id),dimension INTEGER NOT NULL,vector BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS active_retrieval_indices(workspace TEXT NOT NULL,version_id TEXT NOT NULL,model_id TEXT NOT NULL,generation_id TEXT NOT NULL REFERENCES index_generations(id),PRIMARY KEY(workspace,version_id,model_id));
        CREATE INDEX IF NOT EXISTS chunks_generation ON retrieval_chunks(generation_id,version_id);
        CREATE INDEX IF NOT EXISTS spans_block ON retrieval_spans(block_id);
        CREATE VIRTUAL TABLE IF NOT EXISTS sparse_blocks_v2 USING fts5(block_id UNINDEXED,text,tokenize='unicode61');
        CREATE TABLE IF NOT EXISTS sparse_index_state(block_id TEXT PRIMARY KEY,text_sha256 TEXT NOT NULL);
        ''')
        c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(4,?)',(time.time(),))
        c.executescript('''
        CREATE TABLE IF NOT EXISTS review_accounts(id TEXT PRIMARY KEY,workspace TEXT NOT NULL UNIQUE,label TEXT NOT NULL,code_hash TEXT NOT NULL UNIQUE,created REAL NOT NULL,expires REAL NOT NULL,revoked INTEGER NOT NULL DEFAULT 0,last_login REAL);
        CREATE TABLE IF NOT EXISTS translation_cache(workspace TEXT NOT NULL,version_id TEXT NOT NULL,parse_id TEXT NOT NULL,block_id TEXT NOT NULL,source_language TEXT NOT NULL CHECK(source_language IN ('auto','en','zh')),target_language TEXT NOT NULL CHECK(target_language IN ('en','zh-Hans')),glossary_version TEXT NOT NULL,model TEXT NOT NULL,actual_model TEXT NOT NULL,text TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(workspace,version_id,parse_id,block_id,source_language,target_language,glossary_version,model));
        ''')
        c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(5,?)',(time.time(),))

def one(sql, params=()):
    with db() as c:
        row = c.execute(sql,params).fetchone()
        return dict(row) if row else None

def rows(sql, params=()):
    with db() as c:
        return [dict(x) for x in c.execute(sql,params).fetchall()]

def execute(sql, params=()):
    with db() as c:
        return c.execute(sql,params).rowcount

def event(run_id, name, data):
    execute('INSERT INTO steps(run_id,event,data,created) VALUES(?,?,?,?)',(run_id,name,json.dumps(data,ensure_ascii=False),time.time()))

def cancelled(run_id):
    return one('SELECT status FROM runs WHERE id=?',(run_id,))['status'] == 'cancelled'

def artifact(workspace, run_id, kind, title, payload):
    aid=uid()
    execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)',(aid,workspace,run_id,kind,title,json.dumps(payload,ensure_ascii=False),time.time()))
    return aid


@contextmanager
def run_execution_lock(run_id):
    """Cross-process ownership released by the OS on worker crash.

    Both worker claim and API resume acquire this only while holding the SQLite
    writer transaction. Non-blocking acquisition avoids lock-order deadlocks.
    """
    import fcntl
    import hashlib
    folder=DATA/'run_locks'
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    filename=hashlib.sha256(str(run_id).encode()).hexdigest()+'.lock'
    with (folder/filename).open('a+') as handle:
        try:
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
