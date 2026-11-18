import asyncio
import base64
import hashlib
import uuid
import pytest
from mcptoai_core.chat_attachments import ChatAttachments
from mcptoai_core.documents import DocumentError


def offer(data=b'hello', **kw):
    return dict(type='file_offer', purpose='chat', transfer_id=str(uuid.uuid4()),
                session_id=str(uuid.uuid4()), turn_id=str(uuid.uuid4()), name='notes.txt',
                size=len(data), sha256=hashlib.sha256(data).hexdigest()) | kw


async def complete(receiver, o, data=b'hello'):
    assert (await receiver.handle(o))['status'] == 'ready'
    ack = await receiver.handle(dict(type='file_chunk', transfer_id=o['transfer_id'], index=0, data=base64.b64encode(data).decode()))
    assert ack == dict(type='file_ack', transfer_id=o['transfer_id'], index=0)
    return await receiver.handle(dict(type='file_finish', transfer_id=o['transfer_id']))


def test_round_trip_atomic_consumption_and_cleanup():
    async def run():
        r=ChatAttachments(); o=offer()
        assert await complete(r,o) == dict(type='file_result', transfer_id=o['transfer_id'], status='completed', attachment_id=o['transfer_id'], sha256=o['sha256'])
        stream=r.entries[o['transfer_id']]['file']
        files=r.consume([o['transfer_id']],o['session_id'],o['turn_id'])
        assert base64.b64decode(files['files'][0]['data_base64']) == b'hello'
        assert stream.closed and not r.entries
        with pytest.raises(DocumentError): r.consume([o['transfer_id']],o['session_id'],o['turn_id'])
    asyncio.run(run())


@pytest.mark.parametrize('failure',['session','turn','missing','duplicate','expired','disconnect','incomplete'])
def test_references_fail_closed(failure):
    async def run():
        r=ChatAttachments(); o=offer(); await complete(r,o)
        ids=[o['transfer_id']]; sid=o['session_id']; turn=o['turn_id']
        if failure=='session': sid=str(uuid.uuid4())
        if failure=='turn': turn=str(uuid.uuid4())
        if failure=='missing': ids.append(str(uuid.uuid4()))
        if failure=='duplicate': ids*=2
        if failure=='expired': r.entries[ids[0]]['expires']=0
        if failure=='disconnect': r.close()
        if failure=='incomplete': r.entries[ids[0]]['completed']=False
        with pytest.raises(DocumentError): r.consume(ids,sid,turn)
        r.close()
    asyncio.run(run())


def test_concurrent_quota_cancel_and_retry():
    async def run():
        r=ChatAttachments(); first=offer(); offers=[first]+[offer(session_id=first['session_id'],turn_id=first['turn_id']) for _ in range(4)]
        for o in offers[:4]: assert (await r.handle(o))['status']=='ready'
        assert (await r.handle(offers[4]))['reason']=='attachment_quota'
        await r.handle(dict(type='file_cancel', transfer_id=first['transfer_id']))
        assert (await r.handle(offers[4]))['status']=='ready'
        r.close()
        for _ in range(2): assert (await r.handle(offer(size=10*1024**2,session_id=first['session_id'],turn_id=first['turn_id'])))['status']=='ready'
        assert (await r.handle(first))['reason']=='attachment_quota'
        r.close()
    asyncio.run(run())


@pytest.mark.parametrize('mutation',[{'index':1},{'index':True},{'data':'!!!'},{'data':base64.b64encode(b'x'*131073).decode()}])
def test_bad_chunks_delete_staging(mutation):
    async def run():
        r=ChatAttachments(); o=offer(); await r.handle(o)
        frame=dict(type='file_chunk',transfer_id=o['transfer_id'],index=0,data='aGVsbG8=')|mutation
        assert (await r.handle(frame))['status']=='failed'
        assert not r.entries
    asyncio.run(run())


@pytest.mark.parametrize('data,name',[(b'MZprogram','safe.txt'),(b'\xff\xfeh\x00','safe.txt'),(b'%PDF-1.4\n%%EOF','fake.pdf'),(b'\x89PNG\r\n\x1a\n','fake.png'),(b'hello','old.doc'),(b'a\x7fb','safe.txt')])
def test_completion_validates_full_bytes(data,name):
    async def run():
        r=ChatAttachments(); o=offer(data,name=name)
        result=await complete(r,o,data)
        assert result['status']=='failed' and not r.entries
        assert set(result)=={'type','transfer_id','status','reason'}
    asyncio.run(run())


def test_digest_mismatch_and_workspace_not_intercepted():
    async def run():
        r=ChatAttachments(); o=offer(sha256='0'*64)
        assert (await complete(r,o))['status']=='failed'
        workspace=offer(); workspace.pop('purpose'); workspace['workspace']='/chosen'
        assert await r.handle(workspace) is None
        assert not r.entries
    asyncio.run(run())
