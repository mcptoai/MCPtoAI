import pytest
from mcptoai_core.action_contract import ActionRequest, DeviceApprovalGate, preview_digest


def req(name='file.write', path='/tmp/report.txt', content='hello'):
    return ActionRequest.parse({'version': 1, 'name': name, 'arguments': {'path': path, 'content': content}})


@pytest.mark.parametrize('payload', [
    {}, {'version': True, 'name': 'file.read', 'arguments': {'path': '/tmp/a'}},
    {'version': 1, 'name': 'run_command', 'arguments': {}},
    {'version': 1, 'name': 'file.read', 'arguments': {'path': '/tmp/a', 'extra': 'x'}},
    {'version': 1, 'name': 'file.read', 'arguments': {'path': 42}},
    {'version': 1, 'name': 'file.read', 'arguments': {'path': 'x\x00y'}},
])
def test_invalid_actions_fail_closed(payload):
    with pytest.raises(ValueError):
        ActionRequest.parse(payload)


def test_digest_deterministic_independent_of_input_key_order():
    a = req()
    b = ActionRequest.parse({'arguments': {'content': 'hello', 'path': '/tmp/report.txt'}, 'name': 'file.write', 'version': 1})
    assert a.digest() == b.digest()
    assert preview_digest(a, 'Write report') == preview_digest(b, 'Write report')


def test_one_use_scoped_approval():
    gate = DeviceApprovalGate(); a = req()
    g = gate.record_local_approval(user_id='u', device_id='d', turn_id='turn', request=a, preview='Write report', now=100)
    assert gate.consume(nonce=g.nonce, user_id='u', device_id='d', turn_id='turn', request=a, preview='Write report', now=101)
    assert not gate.consume(nonce=g.nonce, user_id='u', device_id='d', turn_id='turn', request=a, preview='Write report', now=102)


@pytest.mark.parametrize('change', ['user', 'device', 'args', 'preview', 'expired'])
def test_approval_tampering_consumes_grant(change):
    gate = DeviceApprovalGate(); a = req()
    g = gate.record_local_approval(user_id='u', device_id='d', turn_id='turn', request=a, preview='Write report', now=100)
    params = dict(nonce=g.nonce, user_id='u', device_id='d', turn_id='turn', request=a, preview='Write report', now=101)
    if change == 'user': params['user_id'] = 'other'
    if change == 'device': params['device_id'] = 'other'
    if change == 'args': params['request'] = req(content='changed')
    if change == 'preview': params['preview'] = 'Changed preview'
    if change == 'expired': params['now'] = 160
    assert not gate.consume(**params)
    assert not gate.consume(nonce=g.nonce, user_id='u', device_id='d', turn_id='turn', request=a, preview='Write report', now=101)


def test_turn_mismatch_and_replay_fail_closed():
    gate = DeviceApprovalGate(); action = req()
    grant = gate.record_local_approval(user_id='auth0|real', device_id='paired-1', turn_id='turn-1',
                                       request=action, preview='Local preview', now=100)
    assert not gate.consume(nonce=grant.nonce, user_id='auth0|real', device_id='paired-1',
                            turn_id='turn-2', request=action, preview='Local preview', now=101)
    assert not gate.consume(nonce=grant.nonce, user_id='auth0|real', device_id='paired-1',
                            turn_id='turn-1', request=action, preview='Local preview', now=101)


def test_grant_requires_nonempty_turn_and_real_scope():
    gate = DeviceApprovalGate()
    for user, device, turn in [('', 'device', 'turn'), ('user', '', 'turn'), ('user', 'device', '')]:
        with pytest.raises(ValueError):
            gate.record_local_approval(user_id=user, device_id=device, turn_id=turn,
                                       request=req(), preview='Local preview')
