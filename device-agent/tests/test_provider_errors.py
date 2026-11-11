from mcptoai_agent.provider_errors import friendly_provider_error


def test_status_messages_hide_raw_data():
    for code, expected in [(401,'API key invalid (401)'), (403,'Access denied (403)'), (404,'Model or endpoint not found (404)'), (429,'Rate limit reached (429)'), (503,'Provider server error (5xx)')]:
        raw=f'AuthenticationError {code} {{"error": "SECRET-API-KEY", "provider_id": "custom-internal"}}'
        msg=friendly_provider_error('custom-abc',RuntimeError(raw),{'custom-abc':{'name':'TEST-LLMGATE','base_url':'https://secret.example/v1'}})
        assert msg == f'TEST-LLMGATE: {expected}'
        assert 'SECRET' not in msg and 'custom-abc' not in msg


def test_unknown_error_is_generic():
    assert friendly_provider_error('openai',RuntimeError('password=secret')) == 'OpenAI: Connection or model request failed'
