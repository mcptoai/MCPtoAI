import pytest
from mcptoai_agent.activity_redaction import (
    HIDDEN, render_command, render_file, render_url, render_mcp, render_target
)

@pytest.mark.parametrize("cmd,expected", [
    ('curl -H "Authorization: Bearer sk-abcdefghijk" https://example.com', "curl"),
    ('curl -u user:pass --password=secret --token secret https://example.com', "curl"),
    ('API_KEY=secret OPENAI_API_KEY=sk-abcdefghi curl https://example.com', "curl"),
    ('git clone https://user:ghp_abcdefgh@github.com/org/repo', "git clone"),
    ('git clone postgres://user:pass@host/db', "git clone"),
    ('curl redis://:pass@host', "curl"),
    ('curl -H "Authorization: Bearer AKIAABCDEFGHIJKLMNOP"', "curl"),
    ('curl -H "Authorization: Bearer eyJabcdefghijklm.eyJabcdefghijklm.signature"', "curl"),
    ('curl --data "-----BEGIN RSA PRIVATE KEY----- secret"', "curl"),
    ('curl "https://example.com/?token=secret&key=secret&sig=secret&X-Amz-Signature=secret"', "curl"),
    ('curl --token sk-abcdefghij', "curl"),
    ('curl --token sk-abc\u200bdefghijk', "curl"),
    ('curl -H "Authorization: Bearer sk-abc\u200bdefghijk"', "curl"),
    ('curl --token ' + 'A'*100, "curl"),
    ('git status', "git status"),
])
def test_command_never_exposes_secrets(cmd, expected):
    result = render_command(cmd)
    assert result.startswith(expected)
    for secret in ("user:pass", "secret", "ghp_", "AKIA", "eyJ", "sk-", "abcdefghijk", "OPENAI_API_KEY"):
        assert secret not in result

@pytest.mark.parametrize("cmd", [
    'echo "sk-abcdefghijk" | base64',
    'curl https://example.com\n--token secret',
    'curl https://example.com; echo secret',
    'echo ' + 'A'*90 + ' | base64 -d',
    'UNKNOWN_TOOL --token secret',
])
def test_complex_and_unknown_commands_hidden(cmd):
    assert render_command(cmd) == HIDDEN

@pytest.mark.parametrize("url,expected", [
    ("https://user:ghp_abcdefgh@github.com/org/repo?token=secret", "https://github.com/org/repo"),
    ("postgres://user:pass@host/db", "postgres://host/db"),
    ("redis://:pass@host", "redis://host"),
    ("https://example.com/path?key=x&sig=y&X-Amz-Signature=z", "https://example.com/path"),
])
def test_url_safe_without_credentials_or_query(url, expected):
    assert render_url(url) == expected

@pytest.mark.parametrize("path", ["/Users/alice/.env", "/Users/alice/.ssh/id_rsa", "/Users/alice/certs/client.pem"])
def test_home_path_hidden_username(path):
    rendered = render_file(path, home="/Users/alice")
    assert rendered.startswith("~/")
    assert "alice" not in rendered
    assert rendered.endswith(path.split("/")[-1])

def test_unknown_user_home_hidden():
    assert render_file("/Users/bob/.env", home="/Users/alice") == HIDDEN

def test_mcp_never_displays_arguments():
    assert render_mcp("github", "create_issue", {"token": "sk-abcdefgh", "file_content": "secret"}) == "github / create_issue"
    assert render_target("unknown", "sk-abcdefgh") == HIDDEN

def test_redaction_before_truncation_and_exception_fail_closed(monkeypatch):
    from mcptoai_agent import activity_redaction as module
    assert "secret" not in render_command("curl --token " + "x"*10000)
    def explode(_):
        raise RuntimeError("secret")
    monkeypatch.setattr(module, "_normalize", explode)
    assert module.render_command("curl secret") == HIDDEN
    assert module.render_file("/Users/alice/.env", home="/Users/alice") == HIDDEN
    assert module.render_url("https://example.com/?token=secret") == HIDDEN
    assert module.render_mcp("github", "list_files") == HIDDEN
