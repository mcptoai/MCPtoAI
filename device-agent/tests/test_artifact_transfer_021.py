"""Cross-platform artifact behavior: user approval, private workspace, relay event."""
import asyncio
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from mcptoai_agent.agent import AgentSession
from mcptoai_agent.config import settings
from mcptoai_agent.policy import ToolPolicy, Decision
from mcptoai_agent.providers.base import AssistantTurn, Provider, ToolCall
from mcptoai_agent.tools import build_server
from mcptoai_agent import artifact_transfer


class ArtifactProvider(Provider):
    name = "fake"
    def __init__(self, file_path):
        super().__init__("unused", "fake")
        self.file_path = str(file_path)
        self.step = 0
    async def complete(self, system, messages, tools):
        self.step += 1
        if self.step == 1:
            assert any(t.name == "send_artifact" for t in tools)
            return AssistantTurn(tool_calls=[ToolCall("1", "send_artifact", {"path": self.file_path})])
        return AssistantTurn(text="Attached")


def invoke(tmp_path, monkeypatch, approved):
    target=tmp_path/"video.mp4"
    target.write_bytes(b"safe preview")
    sid=str(uuid.uuid4())
    cfg=replace(settings, allowed_roots=[tmp_path.resolve()])
    seen=[]
    async def fake_upload(config, file_path, *, session_id=None):
        seen.append((file_path, session_id))
        return {"id":str(uuid.uuid4()),"filename":file_path.name,
                "mime":"video/mp4","size":file_path.stat().st_size,
                "sha256":"a"*64,"expires_at":"2026-10-27T00:00:00Z"}
    monkeypatch.setattr(artifact_transfer, "upload_artifact", fake_upload)
    session=AgentSession(cfg, ArtifactProvider(target),
                         build_server(cfg,artifact_session_id=sid))
    events=[]
    async def emit(event): events.append(event)
    async def approver(tool,args):
        assert tool=="send_artifact"
        return approved
    result=asyncio.run(session.run("Send my video",approver,emit))
    return seen,events,result,sid


def test_user_approved_artifact_emits_replayable_metadata(tmp_path, monkeypatch):
    seen,events,result,sid=invoke(tmp_path,monkeypatch,True)
    assert len(seen)==1 and seen[0][1]==sid
    assert seen[0][0].name=="video.mp4"
    artifacts=[event["artifact"] for event in events if event["type"]=="artifact"]
    assert len(artifacts)==1 and artifacts[0]["mime"]=="video/mp4"
    assert result=="Attached"


def test_rejected_transfer_cannot_upload_or_emit(tmp_path,monkeypatch):
    seen,events,result,sid=invoke(tmp_path,monkeypatch,False)
    assert seen==[]
    assert not any(e.get("type")=="artifact" for e in events)
    assert any(e.get("type")=="done" for e in events)


def test_force_confirm_prevents_stale_auto_permission(tmp_path):
    async def approver(tool,args):
        assert tool=="send_artifact"
        return False
    policy=ToolPolicy(rules={"send_artifact":Decision.AUTO})
    result=asyncio.run(policy.authorize("send_artifact",{"path":str(tmp_path)},approver))
    assert result==(False,"user_denied")


def test_symlink_cannot_export_outside_workspace(tmp_path, monkeypatch):
    allowed=tmp_path/"workspace"
    allowed.mkdir()
    secret=tmp_path/"secret.txt"
    secret.write_text("not for upload")
    (allowed/"escape.txt").symlink_to(secret)
    cfg=replace(settings, allowed_roots=[allowed.resolve()])
    session=AgentSession(cfg, ArtifactProvider(allowed/"escape.txt"),build_server(cfg))
    events=[]
    async def emit(e): events.append(e)
    async def approve(*_): return True
    result=asyncio.run(session.run("Send escape",approve,emit))
    assert not any(e.get("type")=="artifact" for e in events)
    assert secret.read_text()=="not for upload"
def test_chunked_upload_integrity_without_relay_base64(tmp_path, monkeypatch):
    import hashlib
    import json
    import mcptoai_agent.artifact_transfer as module

    source=tmp_path/"lesson.mp4"
    original=b"V"*(4*1024*1024)+b"audio+video"
    source.write_bytes(original)
    cfg=replace(settings, allowed_roots=[tmp_path.resolve()])
    seen=[]; allbytes=bytearray()
    class FakeResponse:
        def __init__(self, code, data): self.status_code,self._data=code,data
        def raise_for_status(self): assert self.status_code < 400, self._data
        def json(self): return self._data
    class FakeClient:
        def __init__(self, *args, **kwargs):
            assert kwargs.get("follow_redirects") is False
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def post(self, url, *, headers, json=None, content=None):
            assert headers["Authorization"]=="Bearer fake-test-only"
            if url.endswith("/api/artifacts/"):
                assert json["size"]==len(original)
                assert json["sha256"]==hashlib.sha256(original).hexdigest()
                assert json["session_id"]==session_id
                return FakeResponse(201,{"id":artifact_id,"chunk_size":4*1024*1024})
            if "/chunk/" in url:
                idx=int(url.rstrip("/").rsplit("/",1)[1])
                seen.append(idx)
                assert headers["Content-Type"]=="application/octet-stream"
                allbytes.extend(content)
                return FakeResponse(200,{"received":len(allbytes)})
            assert url.endswith("/complete/")
            assert bytes(allbytes)==original
            return FakeResponse(200,{"id":artifact_id,"ready":True,"filename":source.name,
                 "mime":"video/mp4","sha256":hashlib.sha256(original).hexdigest(),
                 "size":len(original),"expires_at":"2026-10-27T00:00:00Z"})
    async def fake_token(_): return "fake-test-only"
    artifact_id=str(uuid.uuid4())
    session_id=str(uuid.uuid4())
    monkeypatch.setattr(module,"get_access_token",fake_token)
    monkeypatch.setattr(module,"_auth_bundle",lambda:{"device_id":str(uuid.uuid4())})
    monkeypatch.setattr(module.httpx,"AsyncClient",FakeClient)
    result=asyncio.run(module.upload_artifact(cfg,source,session_id=session_id))
    assert result["id"]==artifact_id
    assert seen==[0,1]
    assert bytes(allbytes)==original
