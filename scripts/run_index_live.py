"""Continue one explicitly created index run; preserves sent/unknown ledger rows."""
import json
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
from services.api import store,index_generations
from services.api.embedding_providers import configured_provider

rid=sys.argv[1]
with store.run_execution_lock(rid) as owned:
    if not owned:raise SystemExit('Run already owned; no duplicate index execution')
    run=store.one('SELECT * FROM runs WHERE id=?',(rid,))
    if not run or run['kind']!='index':raise SystemExit('Not an index run')
    if run['status'] in ('completed','cancelled'):raise SystemExit('Run already terminal')
    if store.one("SELECT 1 FROM quota WHERE run_id=? AND status IN ('reserved','unknown') LIMIT 1",(rid,)):
        raise SystemExit('An upstream attempt is unknown; inspect receipt before any resubmission')
    p=json.loads(run['payload']);store.execute("UPDATE runs SET status='running',error=NULL,updated=? WHERE id=?",(time.time(),rid))
    try:
        result=index_generations.build(run['workspace'],p['version_ids'],provider=configured_provider(p.get('provider'),rid),
               run_id=rid,generation_id=p['generation_id'],source_generation_id=p.get('source_generation_id'),pack_cloud=p.get('pack_cloud',False),
               chunks_only=p.get('chunks_only',False),activate=p.get('activate',True))
        status='queued' if result.get('status')=='queued' else 'completed'
        store.execute('UPDATE runs SET status=?,result=?,updated=? WHERE id=?',(status,json.dumps(result,ensure_ascii=False),time.time(),rid))
        print(json.dumps({'run':rid,'status':status,'vectors':result['vector_count'],'chunks':result['chunk_count']}),flush=True)
    except Exception as error:
        safe=str(error)[:300] if isinstance(error,ValueError) else type(error).__name__
        store.execute("UPDATE runs SET status='failed',error=?,updated=? WHERE id=?",(safe,time.time(),rid))
        print(json.dumps({'run':rid,'status':'FAIL','error':safe}),flush=True)
        raise
