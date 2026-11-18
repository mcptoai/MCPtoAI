import threading
import time
from mcptoai_agent import upload_decisions as u


def test_headless_accept_and_one_shot(tmp_path,monkeypatch):
    monkeypatch.setenv('MCPTOAI_UPLOAD_APPROVAL_DB',str(tmp_path/'approval.sqlite3'))
    tid='00000000-0000-4000-8000-000000000001'
    u.create(tid,'a.pdf',3,str(tmp_path),'a'*64)
    assert len(u.list_pending())==1
    assert u.decide(tid,'accepted')
    assert not u.decide(tid,'denied')
    assert u.consume(tid)=='accepted'
    assert u.consume(tid) is None
    assert not u.list_pending()


def test_headless_deny_and_timeout(tmp_path,monkeypatch):
    monkeypatch.setenv('MCPTOAI_UPLOAD_APPROVAL_DB',str(tmp_path/'approval.sqlite3'))
    tid='00000000-0000-4000-8000-000000000002'
    u.create(tid,'a.pdf',3,str(tmp_path),'a'*64)
    assert u.decide(tid,'denied')
    assert not u.wait_for_decision(tid)
    assert not u.decide(tid,'accepted')


def test_headless_cross_thread_cli_decision(tmp_path,monkeypatch):
    monkeypatch.setenv('MCPTOAI_UPLOAD_APPROVAL_DB',str(tmp_path/'approval.sqlite3'))
    tid='00000000-0000-4000-8000-000000000003'
    u.create(tid,'a.pdf',3,str(tmp_path),'a'*64)
    timer=threading.Timer(.1,lambda:u.decide(tid,'accepted'))
    timer.start()
    try:assert u.wait_for_decision(tid)
    finally:timer.join()
