import os
import signal
import time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[2] / '.env')
from services.api.store import db, migrate, rows
from services.api.jobs import work_once

stopping=False
def stop(*_):
    global stopping
    stopping=True

def main():
    import resource
    cap=int(os.getenv('RT_WORKER_AS_MB','1400'))*1024*1024
    resource.setrlimit(resource.RLIMIT_AS,(cap,cap))
    # flock prevents two worker instances against the same DB.
    import fcntl
    from services.api.store import DATA
    lock=open(DATA/'worker.lock','w')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('A worker already owns this data directory')
    migrate()
    with db() as c:
        # A crash during an upstream call is not proof the provider did no work.
        # Explicit recovery is needed instead of silently submitting it twice.
        c.execute("UPDATE runs SET status='partial',error='上游请求状态未知；配额已保留计账。请检查账目后手动恢复。' WHERE status='running' AND id IN (SELECT run_id FROM quota WHERE status='reserved')")
        c.execute("UPDATE quota SET status='unknown' WHERE status='reserved'")
        c.execute("UPDATE runs SET status='queued' WHERE status='running'")
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    last_watch=0
    while not stopping:
        if not work_once():
            if time.time()-last_watch>30:
                last_watch=time.time()
                from services.api.research import check_watch
                for w in rows('SELECT * FROM watches WHERE enabled=1 AND next_check<=?',(time.time(),)):
                    try:
                        check_watch(w['workspace'],w['id'])
                    except Exception:
                        pass
            time.sleep(.7)

if __name__=='__main__':
    main()
