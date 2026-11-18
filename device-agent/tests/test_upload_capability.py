import asyncio
from unittest.mock import AsyncMock,patch
from mcptoai_agent.relay_client import RelayClient


def test_upload_capability_never_advertised_without_local_linux_approval(tmp_path,monkeypatch):
    client=object.__new__(RelayClient)
    client._send=AsyncMock()
    client._event_epoch='epoch'
    client.cfg=type('Cfg',(),{'allowed_roots':[tmp_path]})()
    monkeypatch.delenv('MCPTOAI_INBOUND_UPLOAD_CLI',raising=False)
    asyncio.run(client._send_hello())
    assert 'inbound_upload_v1' not in client._send.await_args.args[0]['capabilities']


def test_linux_cli_capability_requires_valid_pairing(tmp_path,monkeypatch):
    client=object.__new__(RelayClient)
    client._send=AsyncMock()
    client._event_epoch='epoch'
    client.cfg=type('Cfg',(),{'allowed_roots':[tmp_path]})()
    monkeypatch.setenv('MCPTOAI_INBOUND_UPLOAD_CLI','1')
    with patch('mcptoai_agent.relay_client.sys.platform','linux'),patch('os.path.exists',return_value=True),patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('owner','device')):
        asyncio.run(client._send_hello())
    assert 'inbound_upload_v1' in client._send.await_args.args[0]['capabilities']
