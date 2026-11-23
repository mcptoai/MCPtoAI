from dataclasses import replace
from uuid import uuid4
import pytest
from mcptoai_core.chat_image_save_policy import ChatImageSaveProposal, inspect_save_proposal

S, T, X = [str(uuid4()) for _ in range(3)]
BASE = ChatImageSaveProposal(transfer_id=X, session_id=S, turn_id=T,
    owner_device_id='paired-device',name='photo.jpg',media_type='image/jpeg',
    size=123,sha256='a'*64,destination_workspace='/allowed',trusted_local_confirmation=True)


def check(p):
    return inspect_save_proposal(p, active_session_id=S, active_turn_id=T,
        paired_device_id='paired-device',allowed_roots={'/allowed'})


def test_preflight_never_grants_execution_or_device_tools():
    result = check(BASE)
    assert result['executable'] == 'false' and result['tool_access'] == 'false'
    assert 'photo.jpg' not in str(result) and BASE.sha256 not in str(result)


@pytest.mark.parametrize('changes', [
    {'trusted_local_confirmation':False}, {'session_id':str(uuid4())},
    {'turn_id':str(uuid4())}, {'transfer_id':str(uuid4())+'fake'},
    {'owner_device_id':'other-device'}, {'destination_workspace':'/other'},
    {'media_type':'image/gif'}, {'media_type':'application/x-msdownload'},
    {'name':'../../photo.jpg'}, {'name':'program.exe'}, {'name':'photo.png'},
    {'size':0}, {'size':10*1024*1024+1}, {'sha256':'fake'},
])
def test_denied_changes(changes):
    with pytest.raises((PermissionError, ValueError)):
        check(replace(BASE, **changes))


def test_identity_and_content_binding_changes_digest():
    a = check(BASE)['proposal_sha256']
    assert check(replace(BASE,sha256='b'*64))['proposal_sha256'] != a
    assert check(replace(BASE,destination_workspace='/allowed',name='next.jpg'))['proposal_sha256'] != a
