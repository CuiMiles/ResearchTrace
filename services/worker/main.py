"""Separate bounded document and interaction executors over one durable queue."""
import json
import os
from pathlib import Path
import signal
import threading
import time
from contextlib import ExitStack,contextmanager
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2]/'.env')
from services.api import store
from services.api.jobs import work_once

POOLS={'documents':('parse','parse_document','reparse','index'),
       'interactive':('qa','agent','writing','translate','audit')}
stopping=False


def stop(*_):
    global stopping
    stopping=True


@contextmanager
def worker_lock(pool):
    import fcntl
    if pool not in ('all',*POOLS):raise ValueError('Unknown worker pool')
    with ExitStack() as stack:
        gate=stack.enter_context((store.DATA/'worker.lock').open('a+'))
        try:
            fcntl.flock(gate,fcntl.LOCK_NB|(fcntl.LOCK_EX if pool=='all' else fcntl.LOCK_SH))
            if pool!='all':
                slot=stack.enter_context((store.DATA/f'worker-{pool}.lock').open('a+'))
                fcntl.flock(slot,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('An executor already owns this pool or legacy queue') from None
        yield


def recover(pool):
    kinds=POOLS.get(pool)
    where=' AND kind IN ('+','.join('?' for _ in kinds)+')' if kinds else " AND kind!='watch'"
    recovered=[]
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        candidates=c.execute("SELECT id FROM runs WHERE status='running'"+where,kinds or ()).fetchall()
        for row in candidates:
            with store.run_execution_lock(row['id']) as acquired:
                if not acquired:continue
                unknown=c.execute("SELECT 1 FROM quota WHERE run_id=? AND status IN ('reserved','unknown') LIMIT 1",(row['id'],)).fetchone()
                if unknown:
                    c.execute("UPDATE quota SET status='unknown' WHERE run_id=? AND status='reserved'",(row['id'],))
                    c.execute("UPDATE runs SET status='partial',error='上游请求状态未知；保留计账，需人工核对后恢复',updated=? WHERE id=?",(time.time(),row['id']))
                else:
                    c.execute("UPDATE runs SET status='queued',updated=? WHERE id=?",(time.time(),row['id']))
                recovered.append(row['id'])
    return recovered


def main():
    import resource
    global stopping
    stopping=False
    pool=os.getenv('RT_WORKER_POOL','all')
    if pool not in ('all',*POOLS):raise ValueError('Unknown worker pool')
    cap=int(os.getenv('RT_WORKER_AS_MB','1400'))*1024**2
    resource.setrlimit(resource.RLIMIT_AS,(cap,cap))
    store.migrate()
    with worker_lock(pool):
        recover(pool)
        from services.api.batches import admit_pending,recover_pending_uploads
        from services.api.research import check_due_watches,recover_watch_checks
        if pool in ('all','documents'):recover_pending_uploads()
        if pool in ('all','interactive'):recover_watch_checks()
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        state={'pool':pool,'pid':os.getpid(),'busy':False,'phase':'idle'}
        done=threading.Event()
        def heartbeat():
            target=store.DATA/f'worker-status-{pool}.json'
            while not done.is_set():
                temp=target.with_suffix('.tmp')
                temp.write_text(json.dumps({**state,'timestamp':time.time()}))
                temp.chmod(0o600);temp.replace(target)
                done.wait(2)
        thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
        watch_thread=None;last_watch=0
        try:
            while not stopping:
                if pool in ('all','interactive'):
                    from services.api.dependencies import wake_dependencies
                    wake_dependencies()
                if pool in ('all','documents'):admit_pending()
                if pool in ('all','interactive') and time.monotonic()-last_watch>30 and not (watch_thread and watch_thread.is_alive()):
                    last_watch=time.monotonic()
                    def watch():
                        try:check_due_watches(limit=1)
                        except Exception as exc:print('watch scheduler error: '+type(exc).__name__,flush=True)
                    watch_thread=threading.Thread(target=watch,daemon=True);watch_thread.start()
                state.update(busy=True,phase='executing')
                worked=work_once(pool=pool)
                state.update(busy=False,phase='idle')
                if not worked:time.sleep(.5)
        finally:
            state.update(busy=False,phase='stopped')
            done.set();thread.join(timeout=3)


if __name__=='__main__':main()
