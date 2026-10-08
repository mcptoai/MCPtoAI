import asyncio

import pytest
from urllib.parse import urlencode

from mcptoai_agent import google_drive_integration as g


def test_google_drive_uses_drive_file_and_no_token_broker():
    assert g.SCOPE == "https://www.googleapis.com/auth/drive.file"
    assert "drive.readonly" not in g.SCOPE
    # Token aracısı (broker) yok: token alışverişi ve yenileme doğrudan Google'la.
    assert not hasattr(g, "MANAGED_TOKEN_URL")
    assert not hasattr(g, "CALLBACK_URL")
    assert g.GOOGLE_TOKEN_URL.startswith("https://oauth2.googleapis.com/")
    # Sunucudan yalnızca herkese açık masaüstü client bilgisi alınır.
    assert g.DESKTOP_CLIENT_CONFIG_PATH == "/api/integrations/google-drive/config/"


VALID_CONFIG = {
    "enabled": True, "client_id": "123-abc.apps.googleusercontent.com", "client_secret": "GOCSPX-test",
    "scope": "https://www.googleapis.com/auth/drive.file", "mode": "drive-file-picker-desktop", "redirect_mode": "loopback",
}


def _mock_http(monkeypatch, handler):
    """httpx.AsyncClient'ı ağsız sahte taşıyıcıyla değiştirir; istekleri kaydeder."""
    import httpx
    seen = []
    real = httpx.AsyncClient

    def wrapped(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(g.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(wrapped), **{k: v for k, v in kw.items() if k != "transport"}))
    return seen


def _no_env(monkeypatch):
    monkeypatch.setattr(g, "MANAGED_CLIENT_ID", "")
    monkeypatch.delenv("MCPTOAI_GOOGLE_DESKTOP_CLIENT_ID", raising=False)
    monkeypatch.delenv("MCPTOAI_GOOGLE_DESKTOP_CLIENT_SECRET", raising=False)


def test_managed_client_sunucudan_id_ve_secret_alir(monkeypatch):
    import httpx
    _no_env(monkeypatch)
    seen = _mock_http(monkeypatch, lambda r: httpx.Response(200, json=VALID_CONFIG))
    assert asyncio.run(g._managed_client()) == ("123-abc.apps.googleusercontent.com", "GOCSPX-test")
    assert len(seen) == 1 and seen[0].method == "GET"
    assert seen[0].url.path == "/api/integrations/google-drive/config/"
    assert "authorization" not in {k.lower() for k in seen[0].headers}


def test_eski_web_client_yapilandirmasi_reddedilir(monkeypatch):
    import httpx
    _no_env(monkeypatch)
    for bad in ({**VALID_CONFIG, "mode": "drive-file-picker"}, {**VALID_CONFIG, "redirect_mode": "https"},
                {**VALID_CONFIG, "scope": "https://www.googleapis.com/auth/drive.readonly"},
                {**VALID_CONFIG, "client_id": "evil.example.com"}, {**VALID_CONFIG, "enabled": False}):
        _mock_http(monkeypatch, lambda r, bad=bad: httpx.Response(200, json=bad))
        with pytest.raises(RuntimeError, match="not available"):
            asyncio.run(g._managed_client())


def test_ortam_degiskeni_varsa_sunucuya_gidilmez(monkeypatch):
    import httpx
    monkeypatch.setattr(g, "MANAGED_CLIENT_ID", "")
    monkeypatch.setenv("MCPTOAI_GOOGLE_DESKTOP_CLIENT_ID", "local.apps.googleusercontent.com")
    monkeypatch.setenv("MCPTOAI_GOOGLE_DESKTOP_CLIENT_SECRET", "local-secret")
    seen = _mock_http(monkeypatch, lambda r: httpx.Response(500))
    assert asyncio.run(g._managed_client()) == ("local.apps.googleusercontent.com", "local-secret")
    assert seen == []


def test_sunucuya_ulasilamazsa_anlasilir_hata(monkeypatch):
    import httpx
    _no_env(monkeypatch)

    def boom(request):
        raise httpx.ConnectError("down", request=request)
    _mock_http(monkeypatch, boom)
    with pytest.raises(RuntimeError, match="Could not reach MCPtoAI"):
        asyncio.run(g._managed_client())


def test_token_alisverisi_dogrudan_googlea_secret_ile(monkeypatch):
    import httpx
    from urllib.parse import parse_qs
    seen = _mock_http(monkeypatch, lambda r: httpx.Response(200, json={"access_token": "a", "expires_in": 3600}))
    asyncio.run(g._exchange_direct({"grant_type": "authorization_code", "code": "c", "code_verifier": "v"}, "GOCSPX-test"))
    assert seen[0].url.host == "oauth2.googleapis.com"
    assert "mcptoai" not in str(seen[0].url)
    assert parse_qs(seen[0].content.decode())["client_secret"] == ["GOCSPX-test"]


def test_loopback_callback_validates_state_and_collects_picker_ids():
    async def run():
        state = "expected-state"
        server, future, redirect = await g._start_loopback(state)
        try:
            from urllib.parse import urlsplit
            u = urlsplit(redirect)
            reader, writer = await asyncio.open_connection(u.hostname, u.port)
            q = urlencode({"state": state, "code": "abc", "picked_file_ids": "file1,file2"})
            writer.write(f"GET /?{q} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode())
            await writer.drain()
            response = await reader.read()
            writer.close(); await writer.wait_closed()
            result = await asyncio.wait_for(future, 2)
            assert result["code"] == "abc"
            assert result["picked_file_ids"] == ["file1", "file2"]
            assert b"Google Drive files selected" in response
        finally:
            server.close(); await server.wait_closed()
    asyncio.run(run())
