"""Mac-only local approval boundaries for #126; no real user prompt triggered."""
import asyncio
import base64
import hashlib
from io import BytesIO
from PIL import Image

def real_png():
    f=BytesIO()
    Image.new('RGB',(16,16),(10,20,30)).save(f,format='PNG')
    return f.getvalue()

from pathlib import Path
import sys
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from mcptoai_agent.inbound_manager import InboundManager
from mcptoai_agent.inbound_approval import InboundApproval
from mcptoai_agent.inbound_session import InboundSession
from mcptoai_agent.relay_client import RelayClient
from mcptoai_core.chat_image_receipts import SavedChatImageReceipts


@pytest.mark.skipif(sys.platform != 'darwin', reason='Trusted macOS Desktop approval and quarantine')
def test_approved_save_and_one_time_turn_receipt(tmp_path):
    sid,turn,tid = (str(uuid4()) for _ in range(3))
    data=real_png()
    h=hashlib.sha256(data).hexdigest()
    c=object.__new__(RelayClient)
    c.cfg=type('Settings',(),{'allowed_roots':[tmp_path]})()
    c._inbound=InboundManager(allowed_roots=[tmp_path])
    c._inbound_approval=InboundApproval()
    c._inbound_grants={}
    c._saved_chat_pending={}
    c._saved_chat_images=SavedChatImageReceipts()
    c._send=AsyncMock()
    async def activity(*args,**kwargs): return None
    async def check():
        offer={'type':'file_offer','purpose':'chat_image_save','transfer_id':tid,
               'name':'image.png','workspace':str(tmp_path),'size':len(data),'sha256':h,
               'session_id':sid,'turn_id':turn}
        with patch('mcptoai_agent.inbound_approval.desktop_approval_available',return_value=True), \
             patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('user','device')), \
             patch('mcptoai_agent.inbound_approval.local_desktop_prompt',return_value=True) as prompt, \
             patch.object(InboundSession,'record_activity',activity):
            await c._handle_inbound_upload(offer)
            assert c._send.await_args.args[0]['status']=='ready'
            assert prompt.call_args.kwargs['chat_scope']==(sid,turn)
            await c._handle_inbound_upload({'type':'file_chunk','transfer_id':tid,'index':0,
                                            'data':base64.b64encode(data).decode()})
            await c._handle_inbound_upload({'type':'file_finish','transfer_id':tid})
            assert c._send.await_args.args[0]['status']=='completed'
            saved=c._saved_chat_images.consume([tid],session_id=sid,turn_id=turn,
                                               paired_identity=('user','device'),allowed_roots=[tmp_path])
            assert saved==[str(tmp_path/'image.png')]
            assert Path(saved[0]).read_bytes()==data
            with pytest.raises(PermissionError):
                c._saved_chat_images.consume([tid],session_id=sid,turn_id=turn,
                    paired_identity=('user','device'),allowed_roots=[tmp_path])
    asyncio.run(check())


@pytest.mark.skipif(sys.platform != 'darwin', reason='Trusted macOS Desktop approval and quarantine')
def test_denied_save_never_writes_or_grants(tmp_path):
    sid,turn,tid=(str(uuid4()) for _ in range(3))
    data=real_png()
    c=object.__new__(RelayClient)
    c.cfg=type('Settings',(),{'allowed_roots':[tmp_path]})()
    c._inbound=InboundManager(allowed_roots=[tmp_path]);c._inbound_approval=InboundApproval()
    c._inbound_grants={};c._saved_chat_pending={};c._saved_chat_images=SavedChatImageReceipts();c._send=AsyncMock()
    async def activity(*args,**kwargs):return None
    async def check():
        with patch('mcptoai_agent.inbound_approval.desktop_approval_available',return_value=True), \
             patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('user','device')), \
             patch('mcptoai_agent.inbound_approval.local_desktop_prompt',return_value=False), \
             patch.object(InboundSession,'record_activity',activity):
            await c._handle_inbound_upload({'type':'file_offer','purpose':'chat_image_save','transfer_id':tid,
                'name':'image.png','workspace':str(tmp_path),'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                'session_id':sid,'turn_id':turn})
            assert c._send.await_args.args[0]['status']=='denied'
            assert not (tmp_path/'image.png').exists()
            assert not c._saved_chat_images._items
    asyncio.run(check())
