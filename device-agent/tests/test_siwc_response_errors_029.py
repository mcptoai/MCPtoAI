"""SIWC Responses akış hatalarının ayrıştırılması ve kullanıcı mesajları."""
import json
import pytest
from mcptoai_agent.providers.siwc_responses import parse_events, SiwcResponseError
from mcptoai_agent.provider_errors import friendly_provider_error


def event(kind, **kwargs):
    return 'data: '+json.dumps({'type': kind, **kwargs})


def _error(lines):
    with pytest.raises(SiwcResponseError) as info:
        parse_events(lines)
    return info.value


def test_usage_limit_is_reported_with_manage_usage():
    err = _error([event('response.failed', response={'error': {'code': 'usage_limit_reached', 'message': 'You have hit your plan limit'}})])
    assert err.is_usage_limit and err.status_code == 429 and err.code == 'usage_limit_reached'
    text = friendly_provider_error('chatgpt', err)
    assert 'usage limit' in text and 'Manage usage' in text


def test_rate_limit_code_counts_as_limit():
    err = _error([event('response.failed', response={'error': {'code': 'rate_limit_exceeded'}})])
    assert err.is_usage_limit


def test_incomplete_reason_is_explained():
    err = _error([event('response.incomplete', response={'incomplete_details': {'reason': 'max_output_tokens'}})])
    assert err.kind == 'incomplete' and 'cut off' in friendly_provider_error('chatgpt', err)


def test_stream_error_event_is_not_ignored():
    err = _error([event('error', code='server_error', message='boom')])
    assert 'Model request failed (server_error)' in friendly_provider_error('chatgpt', err)


def test_unsafe_code_and_raw_message_never_reach_the_screen():
    err = _error([event('response.failed', response={'error': {'code': 'bad code https://x.y/?t=secret', 'message': 'secret-token-123 leaked'}})])
    assert err.code is None
    text = friendly_provider_error('chatgpt', err)
    assert 'secret' not in text and 'http' not in text
    # Ayrıntı yalnızca istisna metninde (cihaz logu) bulunur.
    assert 'secret-token-123' in str(err)


def test_failed_without_details_still_fails_closed():
    err = _error([event('response.failed')])
    assert err.code is None and friendly_provider_error('chatgpt', err).endswith('Model request failed')
