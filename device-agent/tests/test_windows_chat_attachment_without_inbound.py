"""Windows chat attachments must work without the separate inbound-upload approval bridge."""
import asyncio
import base64
import hashlib
import io
import uuid
from unittest.mock import AsyncMock,patch

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject,NameObject,DictionaryObject
from mcptoai_agent.relay_client import RelayClient
from mcptoai_agent.inbound_manager import InboundManager
from mcptoai_core.chat_attachments import ChatAttachments


def test_windows_chat_pdf_without_inbound_upload_capability(tmp_path):
    pdf=io.BytesIO();writer=PdfWriter();page=writer.add_blank_page(width=612,height=792)
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 10 10 Td (Windows PDF attachment) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    writer.write(pdf)
    payload=pdf.getvalue();tid=str(uuid.uuid4());sid=str(uuid.uuid4());turn=str(uuid.uuid4())
    client=object.__new__(RelayClient)
    client.cfg=type('Config',(),{'allowed_roots':[]})()
    client._event_epoch='fixed-test-epoch'
    client._chat_attachments=ChatAttachments()
    client._inbound=InboundManager(allowed_roots=[])
    client._send=AsyncMock()
    async def run():
        with patch('mcptoai_agent.relay_client.sys.platform','win32'):
            await client._send_hello()
            capabilities=client._send.await_args_list[-1].args[0]['capabilities']
            assert 'chat_attachments_v1' in capabilities
            assert 'inbound_upload_v1' not in capabilities
            client._send.reset_mock()
        # Dispatch is platform-neutral. Keep the host Python platform real so
        # document parser dependencies do not mistake this Mac CI host for Windows.
        await client._handle({'type':'file_offer','purpose':'chat','transfer_id':tid,
             'session_id':sid,'turn_id':turn,'name':'example.pdf','size':len(payload),
             'sha256':hashlib.sha256(payload).hexdigest()})
        assert client._send.await_args_list[-1].args[0]=={'type':'file_ready','transfer_id':tid,'status':'ready'}
        await client._handle({'type':'file_chunk','transfer_id':tid,'index':0,
            'data':base64.b64encode(payload).decode('ascii')})
        assert client._send.await_args_list[-1].args[0]=={'type':'file_ack','transfer_id':tid,'index':0}
        await client._handle({'type':'file_finish','transfer_id':tid})
        response=client._send.await_args_list[-1].args[0]
        assert response['type']=='file_result' and response['status']=='completed', response
        assert response['attachment_id']==tid
        assert client._chat_attachments.consume([tid],sid,turn)['files'][0]['data_base64']==base64.b64encode(payload).decode('ascii')
        assert len(client._send.await_args_list)==3
        client._chat_attachments.close()
    asyncio.run(run())


def test_chat_file_ready_control_not_silently_lost_on_disconnected_socket(caplog):
    import logging
    client=object.__new__(RelayClient)
    client.ws=None
    client._outbox=[]
    tid=str(uuid.uuid4())
    async def run():
        with caplog.at_level(logging.WARNING,logger='mcptoai.relay_client'):
            await client._send({'type':'file_ready','transfer_id':tid,'status':'ready'})
    asyncio.run(run())
    assert 'file_control_not_sent' in caplog.text
    assert tid in caplog.text
    assert client._outbox==[]  # Never replay frame onto a different socket.
