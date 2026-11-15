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
