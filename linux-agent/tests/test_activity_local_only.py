"""Activity deletion is local-only; relay must not expose it."""
import asyncio
from pathlib import Path
from mcptoai_linux import cli
from mcptoai_linux.relay_client import RelayClient


def test_relay_clear_rejected_without_touching_store(tmp_path, monkeypatch):
    client=object.__new__(RelayClient)
    client.cfg=type('Cfg',(),{'user_settings':{'activity_recording_enabled':True}})()
    client.sessions={}
    sent=[]
    async def send(msg): sent.append(msg)
    client._send=send
    asyncio.run(client._handle_activity_settings({'request_id':'clear-attempt','action':'clear','confirm':True}))
    assert sent[0]['error']=='ValueError'
    assert 'deleted_count' not in sent[0]


def test_cli_clear_requires_confirm(monkeypatch, tmp_path):
    from mcptoai_core import activity_store
    monkeypatch.setattr(activity_store,'config_dir',lambda:tmp_path)
    from mcptoai_core.activity_store import ActivityStore
    store=ActivityStore(tmp_path/'activity-v1.sqlite3')
    store.close()
    try:
        cli.cmd_activity_clear(type('Args',(),{'confirm':False})())
    except SystemExit as exc:
        assert exc.code==2
    else:
        assert False, 'clear must require --confirm'
    assert (tmp_path/'activity-v1.sqlite3').exists()
