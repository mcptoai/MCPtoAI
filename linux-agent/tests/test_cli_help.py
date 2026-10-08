import pytest
from mcptoai_linux.cli import build_parser


def _help(*args):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args([*args, '--help'])
    assert exc.value.code == 0


def test_all_top_level_help_pages_render(capsys):
    for command in ('login','logout','status','doctor','workspace','keys','models','use','mcp','shell','jobs','chat','service','update','reset','connect'):
        _help(command)
    out = capsys.readouterr().out
    assert 'Security:' in out
    assert 'Examples:' in out or 'Example:' in out


def test_root_help_has_quick_start(capsys):
    _help()
    out = capsys.readouterr().out
    assert 'Quick start:' in out
    assert 'mcptoai <command> --help' in out


def test_mcp_help_documents_cloudflare_and_local_risk(capsys):
    _help('mcp')
    out = capsys.readouterr().out
    assert 'https://mcp.cloudflare.com/mcp' in out
    assert 'Local stdio MCP servers execute code' in out


def test_shell_help_documents_local_only_enable(capsys):
    _help('shell')
    out = capsys.readouterr().out
    assert 'off by default' in out
    assert 'only be enabled locally' in out


def test_reset_help_distinguishes_local_and_account_data(capsys):
    _help('reset')
    out = capsys.readouterr().out
    assert 'does not delete your MCPtoAI account' in out


def test_mcp_add_http_uses_streamable_http(monkeypatch):
    import argparse
    import mcptoai_linux.mcp_config as mcp_config
    import mcptoai_linux.discover_cli as discover_cli
    import mcptoai_linux.cli as cli

    seen = {}
    def fake_add_server(name, **kwargs):
        seen.update(name=name, **kwargs)
        return {'id': 'mcp-test'}

    monkeypatch.setattr(mcp_config, 'add_server', fake_add_server)
    monkeypatch.setattr(discover_cli, 'run', lambda _server_id: 0)
    monkeypatch.setattr(cli, '_restart_service_if_running', lambda: None)
    cli.cmd_mcp(argparse.Namespace(action='add-http', name='Cloudflare', url='https://mcp.cloudflare.com/mcp'))
    assert seen['transport'] == 'streamable-http'
    assert seen['url'] == 'https://mcp.cloudflare.com/mcp'



def test_connect_is_public_command(capsys):
    from mcptoai_linux.cli import build_parser
    parser = build_parser()
    parser.print_help()
    out = capsys.readouterr().out
    assert "connect" in out
    args = parser.parse_args(["connect"])
    assert args.cmd == "connect"
    assert callable(args.fn)


def test_run_is_not_a_public_command():
    import pytest
    from mcptoai_linux.cli import build_parser
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run"])
