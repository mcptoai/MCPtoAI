import asyncio
from types import SimpleNamespace

import pytest
from pathlib import Path

from mcptoai_agent import auth
from mcptoai_agent.auth import DeviceRemovedError
from mcptoai_agent.config import Settings
from mcptoai_agent.relay_client import RelayClient


class _Response:
    def __init__(self,status_code=404,body=None,content_type="application/json"):
        self.status_code=status_code
        self._body=body
        self.headers={"content-type":content_type}
    def json(self):
        if isinstance(self._body,Exception): raise self._body
        return self._body
    def raise_for_status(self):
        import httpx
        request=httpx.Request("PUT","https://api.example/api/devices/dev-123/public-key/")
        response=httpx.Response(self.status_code,request=request)
        raise httpx.HTTPStatusError("http error",request=request,response=response)


class _Http:
    def __init__(self,response): self.response=response
    async def __aenter__(self): return self
    async def __aexit__(self,*args): return False
    async def put(self,*args,**kwargs): return self.response


def _run_key_sync(tmp_path,monkeypatch,response):
    monkeypatch.setattr(auth,"config_dir",lambda:tmp_path)
    monkeypatch.setattr(auth,"_device_public_key_b64",lambda create=False:"pub")
    monkeypatch.setattr(auth.httpx,"AsyncClient",lambda **kwargs:_Http(response))
    return asyncio.run(auth.ensure_device_public_key(Settings(server_url="https://api.example"),"token","dev-123"))


def test_public_key_device_not_found_code_marks_removed(tmp_path,monkeypatch):
    r=_Response(body={"code":"device_not_found","detail":"Device not found"})
    with pytest.raises(DeviceRemovedError,match="removed"):
        _run_key_sync(tmp_path,monkeypatch,r)
    state=auth.device_removed_state()
    assert state["device_id"]=="dev-123"


def test_public_key_legacy_exact_json_marks_removed(tmp_path,monkeypatch):
    r=_Response(body={"detail":"Device not found"})
    with pytest.raises(DeviceRemovedError,match="removed"):
        _run_key_sync(tmp_path,monkeypatch,r)
    assert auth.device_removed_state()["device_id"]=="dev-123"


def test_public_key_html_404_does_not_mark_removed(tmp_path,monkeypatch):
    r=_Response(body=ValueError("not json"),content_type="text/html")
    with pytest.raises(Exception) as exc:
        _run_key_sync(tmp_path,monkeypatch,r)
    assert not isinstance(exc.value,DeviceRemovedError)
    assert auth.device_removed_state()=={}


def test_public_key_other_json_404_does_not_mark_removed(tmp_path,monkeypatch):
    r=_Response(body={"code":"route_not_found","detail":"Not found"})
    with pytest.raises(Exception) as exc:
        _run_key_sync(tmp_path,monkeypatch,r)
    assert not isinstance(exc.value,DeviceRemovedError)
    assert auth.device_removed_state()=={}


def test_public_key_extra_field_legacy_404_does_not_mark_removed(tmp_path,monkeypatch):
    r=_Response(body={"detail":"Device not found","extra":True})
    with pytest.raises(Exception) as exc:
        _run_key_sync(tmp_path,monkeypatch,r)
    assert not isinstance(exc.value,DeviceRemovedError)
    assert auth.device_removed_state()=={}


def test_register_device_refuses_tombstoned_id_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "config_dir", lambda: tmp_path)
    auth._mark_device_removed("dev-123")
    monkeypatch.setattr(auth, "_auth_bundle", lambda: {"device_id": "dev-123"})
    called = False
    async def should_not_call(*args, **kwargs):
        nonlocal called
        called = True
    monkeypatch.setattr(auth, "ensure_device_public_key", should_not_call)
    with pytest.raises(DeviceRemovedError):
        asyncio.run(auth.register_device(Settings(), "token"))
    assert called is False


def test_relay_stops_retrying_after_device_removed(monkeypatch):
    import mcptoai_agent.relay_client as rc
    calls = 0
    async def token(_cfg): return "token"
    async def removed(_cfg, _token):
        nonlocal calls
        calls += 1
        raise DeviceRemovedError("removed")
    monkeypatch.setattr(rc, "get_access_token", token)
    monkeypatch.setattr(rc, "register_device", removed)
    client = RelayClient(Settings())
    async def no_ipc(): return None
    monkeypatch.setattr(client, "_start_local_ipc", no_ipc)
    async def run():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(client.run_forever(), timeout=0.05)
    asyncio.run(run())
    assert calls == 1


def test_status_and_doctor_message_text_is_stable():
    source=(Path(__file__).parents[1]/"mcptoai_agent"/"__main__.py").read_text()
    assert "This device was removed from your account. Pair it again." in source



def test_public_key_500_does_not_mark_device_removed(tmp_path,monkeypatch):
    r=_Response(status_code=500,body={"detail":"temporary"})
    with pytest.raises(Exception) as exc:
        _run_key_sync(tmp_path,monkeypatch,r)
    assert not isinstance(exc.value,DeviceRemovedError)
    assert auth.device_removed_state()=={}
