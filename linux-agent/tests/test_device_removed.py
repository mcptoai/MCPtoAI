import asyncio
import pytest
import httpx
from mcptoai_linux import auth
from mcptoai_linux.auth import DeviceRemovedError
from mcptoai_linux.config import Settings

class Response:
    def __init__(self,status_code=404,body=None,content_type="application/json"):
        self.status_code=status_code; self._body=body; self.headers={"content-type":content_type}
    def json(self):
        if isinstance(self._body,Exception): raise self._body
        return self._body
    def raise_for_status(self):
        req=httpx.Request("PUT","https://api.example/x"); resp=httpx.Response(self.status_code,request=req)
        raise httpx.HTTPStatusError("http error",request=req,response=resp)
class Http:
    def __init__(self,response): self.response=response
    async def __aenter__(self): return self
    async def __aexit__(self,*args): return False
    async def put(self,*args,**kwargs): return self.response
def run_sync(tmp_path,monkeypatch,response):
    monkeypatch.setattr(auth,"config_dir",lambda:tmp_path)
    monkeypatch.setattr(auth,"_device_public_key_b64",lambda create=False:"pub")
    monkeypatch.setattr(auth.httpx,"AsyncClient",lambda **kwargs:Http(response))
    return asyncio.run(auth.ensure_device_public_key(Settings(server_url="https://api.example"),"token","dev-123"))
def test_machine_code_404_marks_removed(tmp_path,monkeypatch):
    with pytest.raises(DeviceRemovedError): run_sync(tmp_path,monkeypatch,Response(body={"code":"device_not_found","detail":"Device not found"}))
    assert auth.device_removed_state()["device_id"] == "dev-123"
def test_exact_legacy_json_404_marks_removed(tmp_path,monkeypatch):
    with pytest.raises(DeviceRemovedError): run_sync(tmp_path,monkeypatch,Response(body={"detail":"Device not found"}))
    assert auth.device_removed_state()["device_id"] == "dev-123"
@pytest.mark.parametrize("response",[Response(body=ValueError("html"),content_type="text/html"),Response(body={"code":"route_not_found"}),Response(body={"detail":"Device not found","extra":True}),Response(status_code=500,body={"detail":"temporary"})])
def test_other_errors_do_not_mark_removed(tmp_path,monkeypatch,response):
    with pytest.raises(Exception) as exc: run_sync(tmp_path,monkeypatch,response)
    assert not isinstance(exc.value,DeviceRemovedError)
    assert auth.device_removed_state() == {}
def test_tombstoned_registration_refuses_without_network(tmp_path,monkeypatch):
    monkeypatch.setattr(auth,"config_dir",lambda:tmp_path)
    monkeypatch.setattr(auth,"_auth_bundle",lambda:{"device_id":"dev-123"})
    auth._mark_device_removed("dev-123")
    with pytest.raises(DeviceRemovedError): asyncio.run(auth.register_device(Settings(server_url="https://api.example"),"token"))
