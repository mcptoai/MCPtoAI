"""_run_message koruyucusu: beklenmedik hata web'i "Çalışıyor…" durumunda bırakmaz."""
import asyncio
import zlib

import pytest

from mcptoai_agent.relay_client import RelayClient, _is_stale_bundle_error


def _client(inner):
    client = object.__new__(RelayClient)
    client._turn_state = {}
    client.sent = []
    client.restarts = 0

    async def send_event(sid, event, turn_id=None):
        client.sent.append((sid, event))

    def restart():
        client.restarts += 1

    client._send_event = send_event
    client._restart_for_replaced_bundle = restart
    client._run_message_inner = inner.__get__(client)
    return client


def test_unexpected_error_sends_error_and_clears_turn():
    async def inner(self, msg):
        self._turn_state['s1'] = {'id': 't1', 'active': True}
        raise ValueError('boom')

    client = _client(inner)
    asyncio.run(client._run_message({'session_id': 's1', 'message': 'hi'}))
    assert client.sent == [('s1', {'type': 'error', 'code': 'agent_error', 'message': 'The device agent hit an unexpected error. Please try again.'})]
    assert client._turn_state['s1']['active'] is False
    assert client.restarts == 0


def test_replaced_bundle_error_restarts_agent():
    async def inner(self, msg):
        raise zlib.error('Error -3 while decompressing data: incorrect header check')

    client = _client(inner)
    asyncio.run(client._run_message({'session_id': 's1', 'message': 'hi'}))
    assert client.sent[0][1]['code'] == 'agent_updated'
    assert client.restarts == 1


def test_previous_active_turn_is_not_touched():
    async def inner(self, msg):
        raise ValueError('rejected before starting a turn')

    client = _client(inner)
    other = {'id': 'running', 'active': True}
    client._turn_state['s1'] = other
    asyncio.run(client._run_message({'session_id': 's1', 'message': 'hi'}))
    assert other['active'] is True


def test_cancellation_is_not_swallowed():
    async def inner(self, msg):
        raise asyncio.CancelledError()

    client = _client(inner)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(client._run_message({'session_id': 's1', 'message': 'hi'}))
    assert client.sent == []


def test_stale_bundle_detection_follows_exception_chain():
    try:
        try:
            raise zlib.error('Error -3 while decompressing data')
        except zlib.error as inner:
            raise RuntimeError('import failed') from inner
    except RuntimeError as exc:
        assert _is_stale_bundle_error(exc)
    assert not _is_stale_bundle_error(ValueError('ordinary'))
