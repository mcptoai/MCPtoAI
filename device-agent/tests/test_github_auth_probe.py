"""GitHub MCP yetki kontrolü (probe_stdio_tool) testleri.

Gerçek github-mcp-server yerine, get_me yanıtını FAKE_MODE ile seçen küçük bir
stdio MCP sunucusu kullanılır; ağ ve gerçek token gerekmez.
"""
import asyncio
import json
import sys
import textwrap

import pytest

from mcptoai_agent import discover_cli

FAKE_SERVER = textwrap.dedent('''
    import json, os
    from fastmcp import FastMCP
    mcp = FastMCP("fake-github")

    @mcp.tool()
    def get_me() -> str:
        mode = os.environ.get("FAKE_MODE")
        if mode == "user":
            # Profil metninde "to authorize" geçse bile geçerli kullanıcı yanıtı
            return json.dumps({"login": "octo", "bio": "I help teams to authorize deploys"})
        if mode == "oauth":
            return "To authorize the GitHub MCP Server, open this URL in your browser: https://github.com/login/oauth/authorize?client_id=x"
        if mode == "error":
            raise RuntimeError("failed to get user: 401 Bad credentials")
        return "plain text response"

    mcp.run(transport="stdio", show_banner=False)
''')


@pytest.fixture
def fake_server(tmp_path, monkeypatch):
    script = tmp_path / "fake_github.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")

    def configure(mode, token="github_pat_" + "x" * 40):
        env = {"FAKE_MODE": mode}
        if token:
            env["GITHUB_PERSONAL_ACCESS_TOKEN"] = token
        server = {"id": "mcp-gh", "transport": "stdio", "managed_integration": "github-official",
                  "command": sys.executable, "args": [str(script)], "env": env}
        monkeypatch.setattr(discover_cli, "custom_servers", lambda: [server])
    return configure


def probe():
    return asyncio.run(discover_cli.probe_stdio_tool("mcp-gh", "get_me"))


def test_token_yoksa_sunucu_baslatilmadan_reddedilir(fake_server):
    fake_server("user", token="")
    assert probe() is False


def test_json_login_varsa_profil_metninden_bagimsiz_gecerli(fake_server):
    fake_server("user")
    assert probe() is True


def test_oauth_talimati_basari_sayilmaz(fake_server):
    fake_server("oauth")
    assert probe() is False


def _messages(exc):
    """ExceptionGroup içindeki tüm hata mesajlarını düzleştirir."""
    out = [str(exc)]
    for child in getattr(exc, "exceptions", None) or []:
        out += _messages(child)
    return out


def test_gecersiz_token_hata_verir(fake_server):
    # MCP istemcisi hatayı ExceptionGroup ile sarar; github-auth-status bunu
    # `except Exception` ile yakalayıp not-authorized yazar.
    fake_server("error")
    with pytest.raises(Exception) as excinfo:
        probe()
    assert isinstance(excinfo.value, Exception)
    assert any("Bad credentials" in m for m in _messages(excinfo.value))


def test_yapisal_olmayan_normal_yanit_onceki_gibi_kabul_edilir(fake_server):
    fake_server("plain")
    assert probe() is True
