"""No-provider readiness from expiring worker heartbeats."""
import json
import os
import time
from pathlib import Path
from .store import DATA


def read_worker_status(pool,max_age=15,data_dir=None):
    if pool not in ('all','documents','interactive'):raise ValueError('Unknown worker pool')
    path=Path(data_dir or DATA)/f'worker-status-{pool}.json'
    try:
        data=json.loads(path.read_text())
        if data.get('pool')!=pool or type(data.get('pid')) is not int:raise ValueError
        os.kill(data['pid'],0)
        stale=time.time()-data['timestamp']>max_age
        return {**data,'healthy':not stale,'reason':'heartbeat_stale' if stale else None}
    except (OSError,ValueError,KeyError,TypeError):
        return {'pool':pool,'healthy':False,'reason':'worker_not_available','busy':None}
