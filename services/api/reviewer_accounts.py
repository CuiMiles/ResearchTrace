"""Stable reviewer invitations. Call creation/list/revoke only from admin routes.

The schema belongs to store.migrate. Account and workspace IDs are generated
here, never accepted from a login payload. Only create_reviewer returns the
access code; the database stores a domain-separated SHA-256 digest of 32 random
bytes. Login must cap session expiry to the returned expires value and check
account expiry/revocation when authenticating each reviewer session.
"""
import hashlib
import re
import secrets
import time

from .store import db, uid


_FIELDS = 'id,workspace,label,created,expires,revoked,last_login'
_CODE = re.compile(r'[A-Za-z0-9_-]{43}\Z')


def _code_hash(code):
    return hashlib.sha256(b'researchtrace:reviewer:v1:' + code.encode('ascii')).hexdigest()


def _metadata(row, now):
    data = {field: row[field] for field in _FIELDS.split(',')}
    data['revoked'] = bool(data['revoked'])
    data['status'] = 'revoked' if data['revoked'] else 'expired' if data['expires'] <= now else 'active'
    return data


def create_reviewer(label, days=7, workspace_id=None,seed_workspace_id=None):
    """Return flat account metadata plus access_code once; never log this result."""
    if not isinstance(label, str) or not 1 <= len(label.strip()) <= 120:
        raise ValueError('评审名称需要 1–120 个字符')
    if type(days) is not int or not 1 <= days <= 90:
        raise ValueError('评审访问有效期需要 1–90 整数天')
    if workspace_id is not None and (not isinstance(workspace_id,str) or not 1<=len(workspace_id)<=100):
        raise ValueError('需要选择有效的已有研究空间')
    if workspace_id and seed_workspace_id:raise ValueError('已有空间绑定和独立种子复制只能选择一种')
    label = label.strip()
    now = time.time()
    account = {'id': uid(), 'workspace': workspace_id or uid(), 'label': label, 'created': now,
               'expires': now + days * 86400, 'revoked': False, 'last_login': None,
               'status': 'active'}
    code = secrets.token_urlsafe(32)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if workspace_id:
            if not c.execute('SELECT id FROM workspaces WHERE id=?',(workspace_id,)).fetchone():
                raise ValueError('选择的研究空间不存在')
            if c.execute('SELECT id FROM review_accounts WHERE workspace=?',(workspace_id,)).fetchone():
                raise ValueError('该研究空间已有固定评审入口，请保留其访问历史')
        else:
            c.execute('INSERT INTO workspaces(id,name,created) VALUES(?,?,?)',
                      (account['workspace'], '评审空间 · ' + label, now))
        c.execute('''INSERT INTO review_accounts(id,workspace,label,code_hash,created,expires,revoked,last_login)
                     VALUES(?,?,?,?,?,?,0,NULL)''',
                  (account['id'], account['workspace'], label, _code_hash(code), now, account['expires']))
        if seed_workspace_id:
            from .seed_workspace import clone
            account['seed_copy']=clone(seed_workspace_id,account['workspace'],c)
    return {**account, 'access_code': code}


def available_workspaces(include_bound=False):
    """Admin-only selection metadata, never file paths, sessions or secrets."""
    with db() as c:
        return [dict(row) for row in c.execute('''SELECT w.id,w.name,
            (SELECT count(*) FROM versions v WHERE v.workspace=w.id AND v.deleted=0) documents,
            (SELECT count(*) FROM versions v WHERE v.workspace=w.id AND v.deleted=0 AND v.status='ready') ready_documents
            FROM workspaces w WHERE ? OR NOT EXISTS(SELECT 1 FROM review_accounts a WHERE a.workspace=w.id)
            ORDER BY documents DESC,w.created DESC''',(int(include_bound),))]


def list_reviewers():
    """Administrative metadata only: no access code or code hash is selected."""
    now = time.time()
    with db() as c:
        return [_metadata(row, now) for row in c.execute(f'SELECT {_FIELDS} FROM review_accounts ORDER BY created DESC,id')]


def revoke_reviewer(account_id):
    """Revoke only this account's workspace reviewer sessions, atomically.

    Return metadata for the revoked account, or None when it does not exist.
    Documents, other accounts, and administrator sessions are retained.
    """
    if not isinstance(account_id, str) or not account_id or len(account_id) > 128:
        return None
    now = time.time()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        account = c.execute(f'SELECT {_FIELDS} FROM review_accounts WHERE id=?', (account_id,)).fetchone()
        if account is None:
            return None
        c.execute('UPDATE review_accounts SET revoked=1 WHERE id=?', (account_id,))
        c.execute("DELETE FROM sessions WHERE workspace=? AND role='reviewer'", (account['workspace'],))
        metadata = _metadata(account, now)
        metadata.update(revoked=True, status='revoked')
        return metadata


def lookup_reviewer(code):
    """Return a stable server-owned login identity, or None for any denied code.

    Updating last_login does not extend the account expiry. A caller's existing
    anonymous session must not override the workspace returned by this lookup.
    """
    if not isinstance(code, str) or _CODE.fullmatch(code) is None:
        return None
    now = time.time()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        account = c.execute('''SELECT id,workspace,expires FROM review_accounts
                               WHERE code_hash=? AND revoked=0 AND expires>?''', (_code_hash(code), now)).fetchone()
        if account is None:
            return None
        c.execute('UPDATE review_accounts SET last_login=? WHERE id=?', (now, account['id']))
        return {'account_id': account['id'], 'workspace': account['workspace'],
                'role': 'reviewer', 'expires': account['expires']}
