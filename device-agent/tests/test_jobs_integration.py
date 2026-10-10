"""Görevlerin agent, izinler ve relay ile entegrasyonu."""
import asyncio
import json
import sys
import time
from dataclasses import replace

import pytest
from fastmcp import Client

import mcptoai_agent.jobs as jobs_mod
from mcptoai_agent.agent import AgentSession
from mcptoai_agent.config import settings
from mcptoai_agent.policy import FORCE_CONFIRM_TOOLS, Decision, ToolPolicy
from mcptoai_agent.providers.base import AssistantTurn, Provider
from mcptoai_agent.tools import build_server

PY = f'"{sys.executable}"'


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    # Görev kökü testlere özel; gerçek ~/.config/mcptoai/jobs'a dokunulmaz.
    monkeypatch.setattr(jobs_mod, "_default", jobs_mod.JobManager(root=tmp_path / "jobs"))
    return replace(settings, enable_shell=True, allowed_roots=[tmp_path.resolve()])


def _text(result):
    return " ".join(getattr(c, "text", "") for c in result.content)


def test_gorev_araclari_uctan_uca(cfg):
    async def run():
        async with Client(build_server(cfg)) as c:
            names = {t.name for t in await c.list_tools()}
            assert {"job_start", "job_status", "job_list", "job_stop"} <= names
            job = json.loads(_text(await c.call_tool("job_start", {"command": f'{PY} -c "print(42)"', "name": "kısa"})))
            for _ in range(100):
                st = json.loads(_text(await c.call_tool("job_status", {"job_id": job["id"]})))
                if st["status"] != "running":
                    break
                await asyncio.sleep(0.1)
            assert st["status"] == "finished" and st["exit_code"] == 0 and "42" in st["output_tail"]
            assert any(j["id"] == job["id"] for j in json.loads(_text(await c.call_tool("job_list", {}))))
            long = json.loads(_text(await c.call_tool("job_start", {"command": f'{PY} -c "import time;time.sleep(60)"'})))
            stopped = json.loads(_text(await c.call_tool("job_stop", {"job_id": long["id"]})))
            assert stopped["status"] == "stopped"
            bad = _text(await c.call_tool("job_start", {"command": "su" + "do ls"}, raise_on_error=False))
            assert "ERROR" in bad
    asyncio.run(run())


def test_shell_kapaliyken_gorev_araclari_yok(cfg):
    async def run():
        async with Client(build_server(replace(cfg, enable_shell=False))) as c:
            assert not ({"job_start", "job_stop"} & {t.name for t in await c.list_tools()})
    asyncio.run(run())


def test_izinler_baslatma_durdurma_daima_onayli_okuma_onaysiz():
    assert {"job_start", "job_stop"} <= FORCE_CONFIRM_TOOLS
    asked = []

    async def approver(tool, args):
        asked.append(tool); return True

    async def run():
        # Bozuk/eski bir yapılandırma AUTO dese bile başlatma onaysız çalışmaz.
        p = ToolPolicy(rules={"job_start": Decision.AUTO})
        assert (await p.authorize("job_start", {}, approver))[0] and asked == ["job_start"]
        asked.clear()
        p.session_grants.add("job_stop")
        await p.authorize("job_stop", {}, approver)
        assert asked == ["job_stop"], "oturum izni zorunlu onayı atlatmamalı"
        asked.clear()
        await ToolPolicy().authorize("job_status", {}, approver)
        assert asked == []
    asyncio.run(run())


class RecordingProvider(Provider):
    name = "kayit"

    def __init__(self, model):
        super().__init__("x", model)
        self.system = ""

    async def complete(self, system, messages, tools):
        self.system = system
        return AssistantTurn(text="tamam")


def test_model_degisince_yeni_model_gorevleri_gorur(cfg):
    job = jobs_mod._default.start(f'{PY} -c "import time;time.sleep(30)"', name="fine-tune")
    try:
        async def ask(provider):
            session = AgentSession(cfg, provider, build_server(cfg))

            async def emit(e): pass

            async def approver(t, a): return False
            await session.run("durum ne", approver, emit)
            return provider.system
        first = asyncio.run(ask(RecordingProvider("model-a")))
        second = asyncio.run(ask(RecordingProvider("model-b")))  # model değişti
        for system in (first, second):
            assert job["id"] in system and "fine-tune" in system and "çalışıyor" in system
    finally:
        jobs_mod._default.stop(job["id"])


def test_biten_gorev_icin_devam_sorusu_kurali(cfg):
    job = jobs_mod._default.start(f'{PY} -c "print(1)"', name="adım-1")
    end = time.time() + 15
    while jobs_mod._default._exit_code(job["id"]) is None and time.time() < end:
        time.sleep(0.1)
    provider = RecordingProvider("model-c")

    async def run():
        async def emit(e): pass

        async def approver(t, a): return False
        await AgentSession(cfg, provider, build_server(cfg)).run("bitti mi", approver, emit)
    asyncio.run(run())
    assert "henüz bildirilmedi" in provider.system and "Devam edeyim mi?" in provider.system


# --- relay: bağlantı kopukken olaylar kaybolmaz ---------------------------------

class FakeWS:
    def __init__(self, fail_after=None):
        self.sent, self.fail_after = [], fail_after

    async def send(self, data):
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            raise ConnectionError("koptu")
        self.sent.append(json.loads(data))


def test_relay_kopukken_olaylari_biriktirir_ve_sirayla_gonderir(monkeypatch):
    from mcptoai_agent import relay_client as rc

    async def no_sleep(_): pass
    monkeypatch.setattr(rc.asyncio, "sleep", no_sleep)

    async def run():
        client = rc.RelayClient(settings)
        client.ws = None
        for i in range(3):
            await client._send({"type": "event", "session_id": "s", "event": {"n": i}})
        await client._send({"type": "hello"})  # bağlantıda yeniden üretilir, bekletilmez
        assert len(client._outbox) == 3
        client.ws = FakeWS(fail_after=1)  # ikinci gönderimde tekrar koptu
        with pytest.raises(ConnectionError):
            await client._flush_outbox()
        assert [m["event"]["n"] for m in client.ws.sent] == [0]
        assert len(client._outbox) == 2, "gönderilemeyen olaylar kaybolmamalı"
        client.ws = FakeWS()
        await client._flush_outbox()
        assert [m["event"]["n"] for m in client.ws.sent] == [1, 2] and not client._outbox
    asyncio.run(run())


def test_relay_gonderim_hatasinda_olay_bekletilir():
    from mcptoai_agent import relay_client as rc

    async def run():
        client = rc.RelayClient(settings)
        client.ws = FakeWS(fail_after=0)
        await client._send({"type": "event", "session_id": "s", "event": {"type": "approval_required"}})
        assert len(client._outbox) == 1
    asyncio.run(run())


def test_onay_suresi_en_fazla_on_bes_dakika():
    assert settings.approval_timeout_seconds == 900


# --- B1: web'e canlı görev durumu ----------------------------------------------

def _wait_exit(mgr, job_id, timeout=15):
    end = time.time() + timeout
    while mgr._exit_code(job_id) is None and time.time() < end:
        time.sleep(0.05)


def test_web_izleyicisi_gorevi_bildirildi_olarak_isaretlemez(cfg):
    mgr = jobs_mod._default
    job = mgr.start(f'{PY} -c "print(1)"', name="adım")
    _wait_exit(mgr, job["id"])
    assert mgr.view(job["id"])["status"] == "finished"
    assert job["id"] in mgr.prompt_summary(), "izleyici okuması modelin göreceği özeti silmemeli"
    mgr.status(job["id"])  # model okudu
    assert mgr.prompt_summary() == ""


def test_bitis_zamani_sorgu_ani_degil_gercek_bitis(cfg):
    mgr = jobs_mod._default
    job = mgr.start(f'{PY} -c "print(1)"')
    _wait_exit(mgr, job["id"])
    time.sleep(2.5)
    assert mgr.view(job["id"])["elapsed_seconds"] < 2.0


def test_canlilik_kontrolu_onbelleklenir(cfg, monkeypatch):
    mgr = jobs_mod._default
    job = mgr.start(f'{PY} -c "import time;time.sleep(30)"')
    mgr._procs.clear()  # başka süreçte başlatılmış gibi (connect süreci)
    calls = []
    real = mgr._alive_uncached
    monkeypatch.setattr(mgr, "_alive_uncached", lambda j, p: calls.append(j) or real(j, p))
    for _ in range(5):
        assert mgr.view(job["id"])["status"] == "running"
    assert len(calls) == 1, f"canlılık 5 okumada {len(calls)} kez kontrol edildi"
    mgr.stop(job["id"])


def test_relay_anlik_goruntu_sadece_degisenler_ve_web_durdur(cfg, monkeypatch):
    from mcptoai_agent import relay_client as rc
    mgr = jobs_mod._default
    long = mgr.start(f'{PY} -c "import time;time.sleep(60)"', name="uzun")

    async def run():
        client = rc.RelayClient(settings)
        client.ws = FakeWS()
        await client._send_jobs_snapshot()
        snap = client.ws.sent[-1]
        assert snap["type"] == "jobs_snapshot" and [j["id"] for j in snap["jobs"]] == [long["id"]]
        # İzleyici: değişiklik yokken hiçbir şey göndermez; yeni görev çıkınca yalnızca onu gönderir.
        ticks = {"n": 0}
        real_sleep = asyncio.sleep

        async def fake_sleep(_):
            ticks["n"] += 1
            if ticks["n"] == 2:
                mgr.start(f'{PY} -c "print(2)"', name="yeni")
            if ticks["n"] > 3:
                raise asyncio.CancelledError
            await real_sleep(0)
        monkeypatch.setattr(rc.asyncio, "sleep", fake_sleep)
        before = len(client.ws.sent)
        with pytest.raises(asyncio.CancelledError):
            await client._watch_jobs()
        updates = [m for m in client.ws.sent[before:] if m["type"] == "job_update"]
        assert [u["job"]["name"] for u in updates] == ["yeni"], updates
        monkeypatch.setattr(rc.asyncio, "sleep", real_sleep)
        # Web'den Durdur: geçersiz kimlik yok sayılır, geçerli olan görevi durdurur.
        n = len(client.ws.sent)
        await client._stop_job({"job_id": "../../etc"})
        assert len(client.ws.sent) == n
        await client._stop_job({"job_id": long["id"]})
        assert client.ws.sent[-1]["type"] == "job_update" and client.ws.sent[-1]["job"]["status"] == "stopped"
    asyncio.run(run())
