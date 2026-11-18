import asyncio
import base64
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, patch
from mcptoai_agent.relay_client import RelayClient
from mcptoai_agent.inbound_manager import InboundManager
from mcptoai_agent.inbound_approval import InboundApproval

TID='00000000-0000-4000-8000-000000000001'


def test_linux_tty_approved_offer_chunk_finish(tmp_path, monkeypatch):
    monkeypatch.setenv('MCPTOAI_INBOUND_UPLOAD_CLI','1')
    client=object.__new__(RelayClient)
    client.cfg=type('Cfg',(),{'allowed_roots':[tmp_path]})()
    client._inbound=InboundManager(allowed_roots=[tmp_path])
    client._inbound_approval=InboundApproval()
    client._inbound_grants={}
    client._send=AsyncMock()
    data=b'abc'
    async def scenario():
        with patch('mcptoai_agent.relay_client.sys.platform','linux'), \
             patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('auth0|owner','device-id')), \
             patch('mcptoai_agent.inbound_approval.local_headless_prompt',return_value=True):
            await client._handle_inbound_upload({'type':'file_offer','transfer_id':TID,'name':'invoice.txt',
                'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'workspace':str(tmp_path)})
            await client._handle_inbound_upload({'type':'file_chunk','transfer_id':TID,'index':0,'data':base64.b64encode(data).decode()})
            await client._handle_inbound_upload({'type':'file_finish','transfer_id':TID})
    asyncio.run(scenario())
    assert (tmp_path/'invoice.txt').read_bytes()==data
    assert [call.args[0]['type'] for call in client._send.await_args_list]==['file_ready','file_ack','file_result']
