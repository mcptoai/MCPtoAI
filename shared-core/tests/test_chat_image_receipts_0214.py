from pathlib import Path
import hashlib
import uuid
import pytest
from mcptoai_core.chat_image_receipts import SavedChatImageReceipts


def ident(): return 'user', 'device'
def uid(): return str(uuid.uuid4())


def fixture(tmp_path):
    now=[0]
    r=SavedChatImageReceipts(clock=lambda:now[0])
    sid,turn,tid=uid(),uid(),uid()
    p=tmp_path/'image.png';p.write_bytes(b'\x89PNG'+b'payload')
    sha=hashlib.sha256(p.read_bytes()).hexdigest()
    r.add(transfer_id=tid,session_id=sid,turn_id=turn,path=str(p),sha256=sha,paired_identity=ident())
    def consume(ids=None,**kwargs):
        return r.consume(ids if ids is not None else [tid],session_id=kwargs.get('session_id',sid),
                         turn_id=kwargs.get('turn_id',turn),paired_identity=kwargs.get('paired_identity',ident()),
                         allowed_roots=kwargs.get('allowed_roots',[tmp_path]))
    return r,p,tid,sid,turn,consume,now


def test_one_use_explicit_saved_image(tmp_path):
    r,p,tid,sid,turn,consume,now=fixture(tmp_path)
    assert consume()==[str(p)]
    with pytest.raises(PermissionError):consume()

@pytest.mark.parametrize('change', ['turn','session','identity','root','content','symlink','expired'])
def test_denied_wrong_scope_or_changed_content(tmp_path,change):
    r,p,tid,sid,turn,consume,now=fixture(tmp_path)
    if change=='turn':args={'turn_id':uid()}
    elif change=='session':args={'session_id':uid()}
    elif change=='identity':args={'paired_identity':('user','other-device')}
    elif change=='root':
        wrong=tmp_path.parent/'other-root';wrong.mkdir(exist_ok=True);args={'allowed_roots':[wrong]}
    elif change=='content':p.write_bytes(b'other');args={}
    elif change=='symlink':
        out=tmp_path.parent/'another-image';out.write_bytes(p.read_bytes());p.unlink();p.symlink_to(out);args={}
    else:now[0]=121;args={}
    with pytest.raises(PermissionError):consume(**args)


def test_multi_image_atomic_and_replay(tmp_path):
    r,p,tid,sid,turn,consume,now=fixture(tmp_path)
    other=tmp_path/'next.jpg';other.write_bytes(b'\xff\xd8\xffpayload')
    next_id=uid()
    r.add(transfer_id=next_id,session_id=sid,turn_id=turn,path=str(other),
          sha256=hashlib.sha256(other.read_bytes()).hexdigest(),paired_identity=ident())
    assert consume([tid,next_id])==[str(p),str(other)]
    with pytest.raises(PermissionError):consume([tid,next_id])


def test_different_turn_keeps_own_receipt(tmp_path):
    r,p,tid,sid,turn,consume,now=fixture(tmp_path)
    another=uid();other=tmp_path/'other.jpg';other.write_bytes(b'sample')
    next_id=uid()
    r.add(transfer_id=next_id,session_id=sid,turn_id=another,path=str(other),
          sha256=hashlib.sha256(other.read_bytes()).hexdigest(),paired_identity=ident())
    with pytest.raises(PermissionError):consume([next_id])
    assert consume()==[str(p)]


def test_clear_on_disconnect(tmp_path):
    r,p,tid,sid,turn,consume,now=fixture(tmp_path)
    r.clear()
    with pytest.raises(PermissionError):consume()


def test_saved_image_requires_individual_tool_approval_even_for_nested_commands():
    from mcptoai_core.chat_image_receipts import needs_saved_image_tool_confirmation
    path='/approved/image.png'
    assert needs_saved_image_tool_confirmation({'path':path},[path])
    assert needs_saved_image_tool_confirmation({'cmd':['convert',path,'-resize','50%']},[path])
    assert needs_saved_image_tool_confirmation({'args':{'input':path}},[path])
    assert not needs_saved_image_tool_confirmation({'path':'/other/image.png'},[path])
    assert not needs_saved_image_tool_confirmation({'path':path},[])
