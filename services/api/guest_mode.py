"""Guest access without a reviewer code.

A guest gets an isolated workspace that expires (default 24 h). It may be seeded
from an operator-chosen template workspace, copying only the compact cloud
(Gemini embedding) index, never the large local vectors. Every model call of a
guest run is limited to the guest model chain (default Gemini 3.5 Flash Lite)
and to two server-side daily caps: one per guest workspace and one shared by all
guests. Refusals, failures and unknown outcomes stay in the same project ledger;
a guest never receives an independent quota and nothing here resets counters.

Configuration (server environment only; never accepted from a request):
  RT_GUEST_MODE=true                enable the guest entrance
  RT_GUEST_SEED_WORKSPACE=<id>      optional template workspace to copy
  RT_GUEST_MODEL_CHAIN              comma list, default the batch (Flash Lite) model
  RT_GUEST_DAILY_CALLS=20           generation calls per guest workspace per day
  RT_GUEST_GLOBAL_DAILY_CALLS=300   generation calls of all guests per day
  RT_GUEST_HOURS=24                 lifetime of a guest workspace
  RT_GUEST_MAX_ACTIVE=60            unexpired guest workspaces at once
  RT_GUEST_PER_CLIENT_HOURLY=3      new guest workspaces per client per hour
  RT_GUEST_MAX_DOCUMENTS=5          uploads per guest workspace (keyword index only)
"""
import hashlib
import os
import time

from . import store


def _model_id_ok(m):
    return m.isascii() and len(m) <= 80 and m.replace('-', '').replace('.', '').replace('_', '').isalnum()


class GuestRefused(Exception):
    def __init__(self, message, status=403):
        super().__init__(message)
        self.status = status


def _int(name, default, low, high):
    raw = os.getenv(name, str(default)).strip()
    if not raw.isdecimal() or not low <= int(raw) <= high:
        raise GuestRefused(f'{name} 配置无效', 503)
    return int(raw)


def enabled():
    return os.getenv('RT_GUEST_MODE', 'false').lower() == 'true'


def model_chain():
    from .models import BATCH
    raw = os.getenv('RT_GUEST_MODEL_CHAIN', '') or BATCH
    chain = [m.strip() for m in raw.split(',') if m.strip()]
    if not chain or not all(_model_id_ok(m) for m in chain):
        raise GuestRefused('RT_GUEST_MODEL_CHAIN 配置无效', 503)
    return list(dict.fromkeys(chain))


def settings():
    return {
        'daily_calls': _int('RT_GUEST_DAILY_CALLS', 20, 1, 10000),
        'global_daily_calls': _int('RT_GUEST_GLOBAL_DAILY_CALLS', 300, 1, 100000),
        'hours': _int('RT_GUEST_HOURS', 24, 1, 168),
        'max_active': _int('RT_GUEST_MAX_ACTIVE', 60, 1, 10000),
        'per_client_hourly': _int('RT_GUEST_PER_CLIENT_HOURLY', 3, 1, 100),
        'max_documents': _int('RT_GUEST_MAX_DOCUMENTS', 5, 0, 100),
    }


def is_guest(workspace, connection=None):
    if not workspace:
        return False
    sql = 'SELECT 1 FROM guest_workspaces WHERE workspace=?'
    if connection is not None:
        return connection.execute(sql, (workspace,)).fetchone() is not None
    return store.one(sql, (workspace,)) is not None


def run_workspace(run_id, connection=None):
    if not run_id:
        return None
    sql = 'SELECT workspace FROM runs WHERE id=?'
    row = connection.execute(sql, (run_id,)).fetchone() if connection is not None else store.one(sql, (run_id,))
    return row['workspace'] if row else None


def chain_for_run(run_id):
    """The guest model chain when the run belongs to a guest workspace, else None."""
    workspace = run_workspace(run_id)
    return model_chain() if workspace and is_guest(workspace) else None


def _client_hash(client):
    return hashlib.sha256(b'researchtrace:guest-client:v1:' + str(client).encode()).hexdigest()


def create(client):
    """Create one isolated guest workspace; returns (workspace, expires)."""
    if not enabled():
        raise GuestRefused('游客模式未开启', 404)
    cfg = settings()
    model_chain()  # validate before creating anything
    now = time.time()
    client_hash = _client_hash(client)
    workspace = store.uid()
    expires = now + cfg['hours'] * 3600
    seed = os.getenv('RT_GUEST_SEED_WORKSPACE', '').strip()
    purge_expired(limit=3, now=now)
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        active = c.execute('SELECT count(*) FROM guest_workspaces WHERE expires>?', (now,)).fetchone()[0]
        if active >= cfg['max_active']:
            raise GuestRefused('当前游客人数已满，请稍后再试或使用评审访问码登录', 429)
        recent = c.execute('SELECT count(*) FROM guest_workspaces WHERE client_hash=? AND created>?',
                           (client_hash, now - 3600)).fetchone()[0]
        if recent >= cfg['per_client_hourly']:
            raise GuestRefused('同一网络创建游客空间过于频繁，请稍后再试', 429)
        c.execute('INSERT INTO workspaces(id,name,created) VALUES(?,?,?)', (workspace, '游客空间', now))
        seeded = 0
        if seed:
            from .models import EMBED
            from .seed_workspace import clone
            seeded = clone(seed, workspace, c, index_models=[EMBED])['counts']['versions']
        c.execute('INSERT INTO guest_workspaces(workspace,created,expires,client_hash,seeded) VALUES(?,?,?,?,?)',
                  (workspace, now, expires, client_hash, seeded))
    return workspace, expires


def _used(c, workspace, day):
    """Generation calls (all outcomes) of one guest workspace and of all guests today."""
    own = c.execute('''SELECT count(*) FROM quota q JOIN runs r ON r.id=q.run_id
                       WHERE r.workspace=? AND q.day=? AND q.model NOT LIKE '%embedding%' ''',
                    (workspace, day)).fetchone()[0]
    everyone = c.execute('''SELECT count(*) FROM quota q JOIN runs r ON r.id=q.run_id
                            JOIN guest_workspaces g ON g.workspace=r.workspace
                            WHERE q.day=? AND q.model NOT LIKE '%embedding%' ''', (day,)).fetchone()[0]
    return own, everyone


def check_reservation(c, workspace, model, now):
    """Called inside models.reserve's transaction for runs of guest workspaces."""
    from .models import EMBED, QuotaRefusal, quota_day
    row = c.execute('SELECT expires FROM guest_workspaces WHERE workspace=?', (workspace,)).fetchone()
    if row is None:
        return
    if row['expires'] <= now:
        raise QuotaRefusal('游客空间已到期；没有发出新的模型请求', scope='global', code='guest_expired')
    if model != EMBED and 'embedding' not in model and model not in model_chain():
        raise QuotaRefusal('游客模式只使用轻量模型；没有发出该模型请求', scope='global', code='guest_model')
    if 'embedding' in model:
        return
    cfg = settings()
    own, everyone = _used(c, workspace, quota_day(now))
    if own >= cfg['daily_calls']:
        raise QuotaRefusal('本游客空间今日 AI 调用次数已用完；评审请使用访问码登录', scope='global', code='guest_daily')
    if everyone >= cfg['global_daily_calls']:
        raise QuotaRefusal('今日全部游客共享的 AI 调用额度已用完；评审请使用访问码登录', scope='global', code='guest_global')


def status(workspace):
    from .models import EMBED, quota_day
    cfg = settings()
    now = time.time()
    with store.db() as c:
        row = c.execute('SELECT created,expires,seeded FROM guest_workspaces WHERE workspace=?', (workspace,)).fetchone()
        if row is None:
            return None
        own, everyone = _used(c, workspace, quota_day(now))
        documents = c.execute('SELECT count(*) FROM versions WHERE workspace=? AND deleted=0', (workspace,)).fetchone()[0]
    return {
        'guest': True,
        'models': model_chain(),
        'embedding_model': EMBED,
        'retrieval': 'gemini_embedding_and_keywords',
        'reranker': False,
        'daily_calls': cfg['daily_calls'],
        'used_calls': own,
        'remaining_calls': max(0, min(cfg['daily_calls'] - own, cfg['global_daily_calls'] - everyone)),
        'global_remaining_calls': max(0, cfg['global_daily_calls'] - everyone),
        'expires': row['expires'],
        'seeded_documents': row['seeded'],
        'documents': documents,
        'max_documents': cfg['max_documents'],
        'uploads_index': 'keyword_only',
    }


def check_upload(workspace, count):
    """Guests may add a few papers of their own beyond the seeded ones."""
    if not is_guest(workspace):
        return
    cfg = settings()
    row = store.one('''SELECT g.seeded,(SELECT count(*) FROM versions v WHERE v.workspace=g.workspace AND v.deleted=0) n
                       FROM guest_workspaces g WHERE g.workspace=?''', (workspace,))
    if row['n'] - row['seeded'] + count > cfg['max_documents']:
        raise GuestRefused(f"游客空间最多上传 {cfg['max_documents']} 篇论文；评审请使用访问码登录", 403)


def purge_expired(limit=3, now=None):
    """Reclaim the corpus copy of expired guest workspaces (bounded per call).

    Removes text, vectors and indexes of the guest's own copy, its sessions and
    its uploaded files under data/pdfs/<workspace>. Runs, steps and the quota
    ledger are kept, so daily guest counters and accounting stay intact; the
    version rows stay as deleted placeholders for those historical runs.
    """
    import shutil
    now = time.time() if now is None else now
    purged = []
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        expired = [r['workspace'] for r in c.execute(
            '''SELECT g.workspace FROM guest_workspaces g WHERE g.expires<=?
               AND (EXISTS(SELECT 1 FROM versions v WHERE v.workspace=g.workspace AND v.deleted=0)
                    OR EXISTS(SELECT 1 FROM blocks b WHERE b.workspace=g.workspace)
                    OR EXISTS(SELECT 1 FROM sessions s WHERE s.workspace=g.workspace))
               ORDER BY g.expires LIMIT ?''', (now, int(limit))).fetchall()]
        for w in expired:
            blocks = "SELECT id FROM blocks WHERE workspace=?"
            chunks = "SELECT id FROM retrieval_chunks WHERE workspace=?"
            for sql in (
                f'DELETE FROM retrieval_vectors WHERE chunk_id IN ({chunks})',
                f'DELETE FROM retrieval_spans WHERE chunk_id IN ({chunks})',
                'DELETE FROM active_retrieval_indices WHERE workspace=?',
                'DELETE FROM retrieval_chunks WHERE workspace=?',
                'DELETE FROM index_generations WHERE workspace=?',
                'DELETE FROM embeddings WHERE workspace=?',
                f'DELETE FROM sparse_blocks_v2 WHERE block_id IN ({blocks})',
                f'DELETE FROM sparse_index_state WHERE block_id IN ({blocks})',
                f'DELETE FROM block_fts WHERE id IN ({blocks})',
                f'DELETE FROM block_parses WHERE block_id IN ({blocks})',
                'DELETE FROM translations WHERE workspace=?',
                'DELETE FROM translation_cache WHERE workspace=?',
                'DELETE FROM document_cards WHERE workspace=?',
                'DELETE FROM refs WHERE workspace=?',
                'DELETE FROM blocks WHERE workspace=?',
                'DELETE FROM pages WHERE version_id IN (SELECT id FROM versions WHERE workspace=?)',
                'DELETE FROM parse_pages WHERE version_id IN (SELECT id FROM versions WHERE workspace=?)',
                'UPDATE versions SET deleted=1 WHERE workspace=?',
                'DELETE FROM sessions WHERE workspace=?',
            ):
                c.execute(sql, (w,))
            purged.append(w)
    for w in purged:
        # Only a guest's own upload directory; seeded copies point at the
        # template's files and are never touched.
        if w.isalnum():
            target = (store.DATA / 'pdfs' / w).resolve()
            if target.parent == (store.DATA / 'pdfs').resolve() and target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
    return purged
