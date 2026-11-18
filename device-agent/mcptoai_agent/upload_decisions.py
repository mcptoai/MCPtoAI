"""Device-local, metadata-only pending upload approvals for headless Linux.

The CLI and agent share a SQLite database on the same volume/user. Docker
operators use `docker exec ... mcptoai-agent uploads list|accept|deny`.
"""
from __future__ import annotations
import os
import sqlite3
import time
from pathlib import Path

TTL = 60

def database_path():
    return Path(os.environ.get('MCPTOAI_UPLOAD_APPROVAL_DB', str(Path.home()/'.config'/'mcptoai'/'upload-decisions.sqlite3')))

def _db():
    path = database_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.stat().st_mode & 0o077:
        raise PermissionError('Unsafe upload approval directory')
    if path.exists() and (path.is_symlink() or path.stat().st_mode & 0o077):
        raise PermissionError('Unsafe upload approval database')
    connection = sqlite3.connect(path, timeout=5)
    os.chmod(path, 0o600)
    connection.execute('CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, name TEXT NOT NULL, size INTEGER NOT NULL, workspace TEXT NOT NULL, sha256 TEXT NOT NULL, expires REAL NOT NULL, decision TEXT NOT NULL)')
    connection.execute('DELETE FROM approvals WHERE expires < ?', (time.time(),))
    connection.commit()
    return connection

def create(transfer_id, name, size, workspace, sha256):
    with _db() as db:
        db.execute('INSERT INTO approvals VALUES (?,?,?,?,?,?,?)',
                   (transfer_id,name,size,workspace,sha256,time.time()+TTL,'pending'))

def list_pending():
    with _db() as db:
        return [dict(zip(('transfer_id','name','size','workspace','sha256','expires'),row))
                for row in db.execute('SELECT id,name,size,workspace,sha256,expires FROM approvals WHERE decision=? AND expires>? ORDER BY expires',('pending',time.time()))]

def decide(transfer_id, decision):
    if decision not in ('accepted','denied'):
        raise ValueError('Invalid decision')
    with _db() as db:
        cur=db.execute('UPDATE approvals SET decision=? WHERE id=? AND decision=? AND expires>?',(decision,transfer_id,'pending',time.time()))
        return cur.rowcount == 1

def consume(transfer_id):
    with _db() as db:
        row=db.execute('SELECT decision FROM approvals WHERE id=? AND expires>?',(transfer_id,time.time())).fetchone()
        if row and row[0] != 'pending':
            db.execute('DELETE FROM approvals WHERE id=?',(transfer_id,))
            return row[0]
        return None

def cancel(transfer_id):
    with _db() as db:
        db.execute('DELETE FROM approvals WHERE id=?',(transfer_id,))

def wait_for_decision(transfer_id):
    while True:
        decision=consume(transfer_id)
        if decision is not None:
            return decision == 'accepted'
        with _db() as db:
            row=db.execute('SELECT expires FROM approvals WHERE id=?',(transfer_id,)).fetchone()
        if not row or time.time()>=row[0]:
            cancel(transfer_id)
            return False
        time.sleep(0.25)
