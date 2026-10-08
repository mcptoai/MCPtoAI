import io

import mcptoai_agent.__main__ as cli


def test_set_key_reads_secret_from_piped_stdin(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli.sys, 'stdin', io.StringIO('dummy-value\n'))
    monkeypatch.setattr(cli, 'set_secret', lambda name, value: captured.update(name=name, value=value))

    cli._set_key('openai', from_stdin=True)

    assert captured == {'name': 'api_key:openai', 'value': 'dummy-value'}
