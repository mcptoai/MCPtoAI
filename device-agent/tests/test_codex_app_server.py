from mcptoai_agent.codex_app_server import CODEX_ARGS, CodexAppServer


def test_requires_token():
    try:
        CodexAppServer('')
    except ValueError:
        pass
    else:
        raise AssertionError('Missing token must fail')


def test_uses_official_responses_provider():
    args = ' '.join(CODEX_ARGS)
    assert 'wire_api="responses"' in args
    assert 'env_key="ACCESS_TOKEN"' in args
    assert 'requires_openai_auth=false' in args
    assert 'api.openai.com/v1' in args
