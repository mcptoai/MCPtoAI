import sqlite3
import pytest
from mcptoai_agent.activity_events import make_event
from mcptoai_agent.activity_store import ActivityStore
from mcptoai_agent.activity_redaction import safe_target


def event(sid='s1', phase='started'):
    return make_event(session_id=sid, turn_id='t1', tool_name='run_command', phase=phase,
                      target_type='command', target_display=safe_target('command','git status'))


def test_round_trip_metadata_only(tmp_path):
    p=tmp_path/'history.db'
    with_store=ActivityStore(p)
    seq=with_store.append(event())
    assert seq > 0
    items=with_store.list_events()
    assert len(items)==1 and items[0]['target_display']==safe_target('command','git status').value
    assert 'output' not in items[0] and 'arguments' not in items[0]
    with_store.close()
    again=ActivityStore(p)
    assert len(again.list_events())==1
    again.close()


def test_cursor_session_and_limits(tmp_path):
    db=ActivityStore(tmp_path/'a.db')
    first=db.append(event())
    second=db.append(event('s2'))
    assert [e['sequence'] for e in db.list_events()]==[second,first]
    assert [e['sequence'] for e in db.list_events(session_id='s1')]==[first]
    assert [e['sequence'] for e in db.list_events(before=second)]==[first]
    for limit in [0,501,True]:
        with pytest.raises(ValueError): db.list_events(limit=limit)
    with pytest.raises(TypeError): db.append({'output':'secret'})
    db.close()


def test_reject_corrupted_stored_wire(tmp_path):
    db=ActivityStore(tmp_path/'a.db')
    db.append(event())
    db._db.execute("UPDATE activity SET payload = ?", ('{"output":"secret"}',))
    db._db.commit()
    with pytest.raises(ValueError): db.list_events()
    db.close()


# --- 0.2.9 PR 2: kota, gerçek silme, kurtarma, eşzamanlılık -----------------------
import multiprocessing
import os
import sys


def _all_bytes(path):
    data = b''
    for suffix in ('', '-wal', '-shm', '-journal'):
        p = str(path) + suffix
        if os.path.exists(p):
            with open(p, 'rb') as f:
                data += f.read()
    return data


def test_quota_counts_wal_and_shm_and_keeps_newest(tmp_path):
    db = ActivityStore(tmp_path / 'q.db', max_bytes=256 * 1024)
    last = 0
    for i in range(1500):
        last = db.append(event(f's{i % 7}'))
    assert db.disk_usage() <= 256 * 1024
    items = db.list_events(limit=500)
    assert items[0]['sequence'] == last
    assert len(db._db.execute('SELECT sequence FROM activity').fetchall()) < 1500
    db.close()


def test_clear_physically_removes_deleted_rows(tmp_path, monkeypatch):
    p = tmp_path / 'c.db'
    db = ActivityStore(p)
    for _ in range(50):
        db.append(event('session-canary-7f3a'))
    db.append(event('keep-me'))
    from mcptoai_agent.activity_test_guard import assert_isolated_activity_db
    from mcptoai_agent import activity_test_guard
    (tmp_path / '.mcptoai-activity-test-only').touch()
    # This store uses an explicit test path; assert the resolved path before ANY delete.
    monkeypatch.setattr(activity_test_guard, 'config_dir', lambda: tmp_path)
    assert_isolated_activity_db(tmp_path)
    print(f"ACTIVITY_TEST_DB_RESOLVED={p.resolve()}", flush=True)
    assert p.resolve().is_relative_to(tmp_path.resolve())
    assert db.clear(session_id='session-canary-7f3a') == 50
    assert [e['session_id'] for e in db.list_events()] == ['keep-me']
    assert b'session-canary-7f3a' not in _all_bytes(p)
    assert p.resolve().is_relative_to(tmp_path.resolve())
    print(f"ACTIVITY_TEST_DB_RESOLVED={p.resolve()}", flush=True)
    db.clear()
    assert db.list_events() == []
    db.close()
    assert b'keep-me' not in _all_bytes(p)


def test_corrupted_database_is_replaced(tmp_path, caplog):
    p = tmp_path / 'bad.db'
    p.write_bytes(b'this is not a sqlite database' * 200)
    with caplog.at_level('WARNING'):
        db = ActivityStore(p)
    assert db.list_events() == []
    assert any('corrupted' in r.getMessage() for r in caplog.records)
    db.append(event())
    assert len(db.list_events()) == 1
    db.close()


def test_locked_database_is_never_deleted(tmp_path, monkeypatch):
    """'database is locked' gibi geçici hatalar bozulma sayılmaz; dosya silinmez."""
    p = tmp_path / 'locked.db'
    first = ActivityStore(p)
    first.append(event('precious'))
    first.close()

    def locked(self):
        raise sqlite3.OperationalError('database is locked')

    monkeypatch.setattr(ActivityStore, '_connect', locked)
    with pytest.raises(sqlite3.OperationalError):
        ActivityStore(p)
    monkeypatch.undo()
    again = ActivityStore(p)
    assert [e['session_id'] for e in again.list_events()] == ['precious']
    again.close()


def test_wal_mode_allows_opening_while_another_writer_holds_a_lock(tmp_path):
    p = tmp_path / 'busy.db'
    ActivityStore(p).close()
    holder = sqlite3.connect(str(p), timeout=0.1, isolation_level=None)
    holder.execute('BEGIN IMMEDIATE')
    try:
        reader = ActivityStore(p, busy_timeout_ms=200)
        assert reader.list_events() == []
        reader.close()
    finally:
        holder.execute('ROLLBACK')
        holder.close()


@pytest.mark.skipif(os.name == 'nt', reason='POSIX symlink and permission checks')
def test_symlink_refused_and_files_private(tmp_path):
    real = tmp_path / 'real.db'
    ActivityStore(real).close()
    link = tmp_path / 'link.db'
    link.symlink_to(real)
    with pytest.raises(ValueError):
        ActivityStore(link)
    db = ActivityStore(tmp_path / 'perm.db')
    db.append(event())
    for suffix in ('', '-wal', '-shm'):
        f = str(tmp_path / 'perm.db') + suffix
        if os.path.exists(f):
            assert (os.stat(f).st_mode & 0o777) == 0o600, f
    db.close()


def _writer(path, sid, count):
    store = ActivityStore(path)
    for _ in range(count):
        store.append(event(sid))
    store.close()


def test_concurrent_processes_can_append(tmp_path):
    p = str(tmp_path / 'shared.db')
    ActivityStore(p).close()
    ctx = multiprocessing.get_context('spawn')
    procs = [ctx.Process(target=_writer, args=(p, f'proc{i}', 150)) for i in range(3)]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(120)
        assert proc.exitcode == 0
    db = ActivityStore(p)
    assert db._db.execute('SELECT COUNT(*) FROM activity').fetchone()[0] == 450
    db.close()


def test_incompatible_schema_is_recreated(tmp_path, caplog):
    p = tmp_path / 'old.db'
    con = sqlite3.connect(str(p))
    con.execute('CREATE TABLE activity (sid TEXT NOT NULL, id INTEGER NOT NULL, ts REAL NOT NULL, payload TEXT NOT NULL)')
    con.commit(); con.close()
    with caplog.at_level('WARNING'):
        db = ActivityStore(p)
    db.append(event())
    assert len(db.list_events()) == 1
    db.close()


def test_default_path_does_not_reuse_prototype_file(monkeypatch, tmp_path):
    from mcptoai_agent import activity_store
    monkeypatch.setattr(activity_store, 'config_dir', lambda: tmp_path)
    proto = tmp_path / 'activity.sqlite3'
    proto.write_bytes(b'prototype data')
    db = activity_store.ActivityStore()
    assert db.path.name == 'activity-v1.sqlite3'
    db.close()
    assert proto.read_bytes() == b'prototype data'


def test_tampered_stored_display_is_rescanned_on_read(tmp_path):
    db = ActivityStore(tmp_path / 't.db')
    db.append(event())
    row = db._db.execute('SELECT payload FROM activity').fetchone()[0]
    import json as _json
    data = _json.loads(row)
    data['target_display'] = 'curl token=sk-live-SECRET1234567890abcdef'
    db._db.execute('UPDATE activity SET payload = ?', (_json.dumps(data),))
    db._db.commit()
    shown = db.list_events()[0]['target_display']
    assert 'SECRET' not in shown and shown == '[CONTENT HIDDEN]'
    db.close()
