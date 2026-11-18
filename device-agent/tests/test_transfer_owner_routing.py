"""#39 device uploads and #40 chat attachments coexist on one relay socket."""
import asyncio
import base64
import hashlib
import io
import logging
import uuid
import zipfile
from unittest.mock import AsyncMock, patch

from mcptoai_agent.relay_client import RelayClient
from mcptoai_agent.inbound_manager import InboundManager
from mcptoai_agent.inbound_approval import InboundApproval
from mcptoai_core.chat_attachments import ChatAttachments


def docx_bytes():
    """A valid non-macro Office container, roughly 39 KiB as in the report."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED) as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>')
        z.writestr('word/media/data.dat', b'a' * 38_000)
    return out.getvalue()


def test_device_docx_and_chat_attachment_share_socket_without_cross_rejection(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv('MCPTOAI_INBOUND_UPLOAD_CLI', '1')
    monkeypatch.setenv('MCPTOAI_ACTIVITY_LOG', '0')
    client = object.__new__(RelayClient)
    client.cfg = type('Cfg', (), {'allowed_roots': [tmp_path]})()
    client._inbound = InboundManager(allowed_roots=[tmp_path])
    client._inbound_approval = InboundApproval()
    client._inbound_grants = {}
    client._chat_attachments = ChatAttachments()
    client._send = AsyncMock()
    device_data, chat_data = docx_bytes(), b'chat attachment text'
    device_tid, chat_tid = str(uuid.uuid4()), str(uuid.uuid4())
    session_id, turn_id = str(uuid.uuid4()), str(uuid.uuid4())
    device_offer = dict(type='file_offer', transfer_id=device_tid, name='report.docx',
                        size=len(device_data), sha256=hashlib.sha256(device_data).hexdigest(), workspace=str(tmp_path))
    chat_offer = dict(type='file_offer', purpose='chat', transfer_id=chat_tid, session_id=session_id,
                      turn_id=turn_id, name='context.txt', size=len(chat_data), sha256=hashlib.sha256(chat_data).hexdigest())

    async def send_frame(frame):
        await client._handle(frame)

    async def test():
        with patch('mcptoai_agent.relay_client.sys.platform', 'linux'), \
             patch('mcptoai_agent.inbound_approval.paired_identity', return_value=('owner', 'device')), \
             patch('mcptoai_agent.inbound_approval.local_headless_prompt', return_value=True):
            await send_frame(device_offer)
            await send_frame(chat_offer)
            # The device offer's trusted local approval is asynchronous.
            for _ in range(300):
                if any(c.args[0].get('type') == 'file_ready' and c.args[0].get('transfer_id') == device_tid for c in client._send.await_args_list):
                    break
                await asyncio.sleep(.01)
            else:
                raise AssertionError('device approval never became ready')
            for tid, data in ((device_tid, device_data), (chat_tid, chat_data)):
                await send_frame(dict(type='file_chunk', transfer_id=tid, index=0, data=base64.b64encode(data).decode()))
                await send_frame(dict(type='file_finish', transfer_id=tid))
            # Unknown frames have no owner and get no response, even if well formed.
            before = client._send.await_count
            await send_frame(dict(type='file_chunk', transfer_id=str(uuid.uuid4()), index=0, data='YQ=='))
            assert client._send.await_count == before
            assert (tmp_path / 'report.docx').read_bytes() == device_data
            assert client._chat_attachments.consume([chat_tid], session_id, turn_id)['files'][0]['data_base64'] == base64.b64encode(chat_data).decode()
            frames = [c.args[0] for c in client._send.await_args_list]
            assert [(f['transfer_id'], f['type']) for f in frames] == [
                (chat_tid, 'file_ready'), (device_tid, 'file_ready'),
                (device_tid, 'file_ack'), (device_tid, 'file_result'),
                (chat_tid, 'file_ack'), (chat_tid, 'file_result')]
            assert all(f.get('status') not in ('failed', 'denied') for f in frames)
    with caplog.at_level(logging.INFO, logger='mcptoai.chat_attachments'):
        asyncio.run(test())
    assert 'chat_attachment_rejected' not in caplog.text
    client._chat_attachments.close()


def test_chat_receiver_never_responds_to_other_transfer_ids(caplog):
    receiver = ChatAttachments()
    async def test():
        for type_ in ('file_chunk', 'file_finish', 'file_cancel'):
            assert await receiver.handle({'type': type_, 'transfer_id': str(uuid.uuid4())}) is None
    with caplog.at_level(logging.INFO, logger='mcptoai.chat_attachments'):
        asyncio.run(test())
    assert 'chat_attachment_rejected' not in caplog.text


def test_malformed_foreign_chunk_does_not_crash_dispatch():
    client = object.__new__(RelayClient)
    client._chat_attachments = ChatAttachments()
    client._inbound = InboundManager(allowed_roots=[])
    client._send = AsyncMock()
    async def run():
        await client._handle({'type':'file_chunk','transfer_id':['unhashable'],'data':'YQ==','index':0})
    asyncio.run(run())
    client._send.assert_not_awaited()
