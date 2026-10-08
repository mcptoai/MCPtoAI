"""Kimlik kasası, süreçler arası kilit, token yenileme ve cihaz kimliği testleri.

Hiçbir test gerçek Keychain'e dokunmaz (conftest.py gerçek keyring'i engeller).
Çok süreçli testler gerçek alt süreçler ve gerçek dosya kilidi kullanır.
"""
from __future__ import annotations

import asyncio
import json
import re
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from mcptoai_linux import secret_store as ss
from mcptoai_linux.credential_lock import (
    LOCK, CredentialLockBusy, CredentialLockTimeout, async_credential_lock, credential_lock,
)

HERE = Path(__file__).parent
WORKER = HERE / "vault_worker.py"


# ---------------------------------------------------------------- yardımcılar
def _doc(secrets: dict, v: int = 1) -> str:
    return json.dumps({"v": v, "secrets": secrets}, sort_keys=True, separators=(",", ":"))


def _worker(backend_dir, *args, timeout=60):
    env = dict(os.environ)  # HOME conftest'ten gelir → ortak kilit dosyası
    return subprocess.Popen([sys.executable, str(WORKER), str(backend_dir), *map(str, args)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)


def _run_worker(backend_dir, *args):
    p = _worker(backend_dir, *args)
    out, err = p.communicate(timeout=120)
    assert p.returncode == 0, err[-2000:]
    return out.strip()


@pytest.fixture
def file_backend(tmp_path):
    from vault_backends import FileBackend
    b = FileBackend(tmp_path / "kc")
    prev = ss.set_backend(b)
    yield b
    ss.set_backend(prev)


@pytest.fixture
def cfg():
    from mcptoai_linux.config import settings
    return replace(settings, auth0_domain="auth.test", auth0_device_client_id="cid", auth0_audience="aud")


# ---------------------------------------------------------------- 1-2 temel kasa
def test_01_clean_vault_creation(isolated_vault):
    assert ss.read_vault() is None and ss.vault_status() == "absent"
    ss.set_secret("a", "1")
    assert json.loads(isolated_vault.data["vault"]) == {"v": 1, "secrets": {"a": "1"}}
    assert "vault.next" not in isolated_vault.data          # geçici kayıt temizlendi
    assert ss.vault_status() == "ok"


def test_02_read_write_delete_and_single_item(isolated_vault):
    ss.set_secret("a", "1"); ss.set_secrets({"b": "2", "c": "3"}); ss.delete_secret("b")
    assert ss.read_vault() == {"a": "1", "c": "3"}
    assert ss.get_secret("a") == "1" and ss.get_secret("b") is None
    assert ss.get_secrets(["a", "c", "zz"]) == {"a": "1", "c": "3"}
    assert set(isolated_vault.data) == {"vault"}            # tek anahtarlık kaydı


def test_02b_no_process_cache_reads_are_fresh(isolated_vault):
    ss.set_secret("k", "old")
    assert ss.get_secret("k") == "old"
    isolated_vault.data["vault"] = _doc({"k": "new"})       # başka süreç yazmış gibi
    assert ss.get_secret("k") == "new"


# ---------------------------------------------------------------- 3-7 bozulma/hata
@pytest.mark.parametrize("raw", ["{not json", "[]", '{"v":1}', '{"v":1,"secrets":[]}',
                                 '{"v":"1","secrets":{}}', '{"v":1,"secrets":{"a":1}}',
                                 '{"v":1,"secrets":{},"x":1}'])
def test_03_corrupt_vault_is_error_and_never_overwritten(isolated_vault, raw):
    isolated_vault.data["vault"] = raw
    with pytest.raises(ss.VaultCorruptError):
        ss.read_vault()
    with pytest.raises(ss.VaultCorruptError):
        ss.set_secret("a", "1")
    assert isolated_vault.data["vault"] == raw              # dokunulmadı
    assert ss.vault_status() in {"corrupt", "unsupported"}


def test_03b_corrupt_error_does_not_leak_content(isolated_vault):
    isolated_vault.data["vault"] = '{"v":1,"secrets":{"api_key:x":"SUPERSECRET"'
    with pytest.raises(ss.VaultCorruptError) as ei:
        ss.read_vault()
    assert "SUPERSECRET" not in str(ei.value) and ei.value.__cause__ is None and ei.value.__suppress_context__


def test_04_unsupported_schema(isolated_vault):
    isolated_vault.data["vault"] = _doc({"a": "1"}, v=2)
    with pytest.raises(ss.VaultUnsupportedVersionError):
        ss.get_secret("a")
    with pytest.raises(ss.VaultUnsupportedVersionError):
        ss.set_secret("a", "2")
    assert json.loads(isolated_vault.data["vault"])["v"] == 2
    assert ss.vault_status() == "unsupported"


def test_05_keychain_read_failure_is_not_empty(isolated_vault):
    isolated_vault.data["vault"] = _doc({"a": "1"})
    isolated_vault.fail_get.add("vault")
    with pytest.raises(ss.CredentialBackendError):
        ss.get_secret("a")
    with pytest.raises(ss.CredentialBackendError):
        ss.set_secret("b", "2")
    isolated_vault.fail_get.clear()
    assert ss.read_vault() == {"a": "1"}


def test_06_keychain_write_failure_keeps_old_vault(isolated_vault):
    ss.set_secret("a", "1")
    isolated_vault.fail_set.add("vault.next")
    with pytest.raises(ss.CredentialBackendError):
        ss.set_secret("a", "2")
    isolated_vault.fail_set.clear()
    assert ss.get_secret("a") == "1"


def test_06b_crash_between_delete_and_add_recovers_from_staging(isolated_vault):
    ss.set_secret("a", "1")
    isolated_vault.fail_add_after_delete.add("vault")       # vault silindi, eklenemedi
    with pytest.raises(ss.CredentialBackendError):
        ss.set_secret("a", "2")
    assert "vault" not in isolated_vault.data
    assert ss.vault_status() == "recovering"
    assert ss.get_secret("a") == "2"                         # doğrulanmış vault.next okunur
    isolated_vault.fail_add_after_delete.clear()
    ss.set_secret("b", "3")                                  # sonraki değişiklik onarır
    assert ss.read_vault() == {"a": "2", "b": "3"} and ss.vault_status() == "ok"
    assert set(isolated_vault.data) == {"vault"}


def test_06c_vault_absent_and_staging_corrupt_is_error(isolated_vault):
    isolated_vault.data["vault.next"] = "garbage"
    with pytest.raises(ss.VaultCorruptError):
        ss.read_vault()


def test_07_verification_failure_after_write(isolated_vault):
    ss.set_secret("a", "1")
    isolated_vault.corrupt_after_set.add("vault.next")
    with pytest.raises(ss.VaultVerifyError):
        ss.set_secret("a", "2")
    isolated_vault.corrupt_after_set.clear()
    assert isolated_vault.data["vault"] == _doc({"a": "1"})  # asıl kasa korunur


def test_07b_mutation_requires_lock(isolated_vault):
    with pytest.raises(RuntimeError):
        ss._mutate_locked(lambda s: None)


# ---------------------------------------------------------------- 8-9 çok süreç
def test_08_09_concurrent_multiprocess_writes_no_lost_updates(file_backend, tmp_path):
    procs = [_worker(file_backend.root, "inc", 25, w) for w in range(5)]
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err[-2000:]
    vault = ss.read_vault()
    assert vault["counter"] == str(5 * 25)                   # kayıp güncelleme yok
    assert sum(1 for k in vault if k.startswith("w")) == 5 * 25


def test_lock_reentrant_in_same_task_and_thread(isolated_vault):
    with credential_lock():
        with credential_lock():
            ss.set_secret("a", "1")                           # mutate de kilidi yeniden alır
    async def go():
        async with async_credential_lock():
            await ss.aset_secret("b", "2")
            ss.set_secret("c", "3")                           # aynı görevde senkron çağrı
    asyncio.run(go())
    assert ss.read_vault() == {"a": "1", "b": "2", "c": "3"}


def test_lock_sync_in_event_loop_while_other_task_holds_is_busy_not_deadlock(isolated_vault):
    async def go():
        held = asyncio.Event(); release = asyncio.Event()
        async def holder():
            async with async_credential_lock():
                held.set(); await release.wait()
        t = asyncio.create_task(holder())
        await held.wait()
        with pytest.raises(CredentialLockBusy):
            ss.set_secret("x", "1")
        release.set(); await t
        ss.set_secret("x", "1")
    asyncio.run(go())
    assert ss.get_secret("x") == "1"


def test_lock_timeout_and_cancellation_release_gate(isolated_vault):
    async def go():
        held = asyncio.Event(); release = asyncio.Event()
        async def holder():
            async with async_credential_lock():
                held.set(); await release.wait()
        t = asyncio.create_task(holder()); await held.wait()
        with pytest.raises(CredentialLockTimeout):
            await LOCK.aacquire(timeout=0.2)
        waiter = asyncio.create_task(LOCK.aacquire(timeout=5)); await asyncio.sleep(0.1)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        release.set(); await t
        async with async_credential_lock(timeout=1):         # kapı sızmadı
            pass
    asyncio.run(go())


def test_lock_file_permissions(isolated_vault):
    with credential_lock():
        pass
    from mcptoai_linux.paths import config_dir
    p = config_dir() / "vault.lock"
    assert p.exists()
    # POSIX mode bits are meaningful on macOS/Linux; Windows uses ACLs instead.
    if os.name != "nt":
        assert (p.stat().st_mode & 0o777) == 0o600
        assert (p.parent.stat().st_mode & 0o777) == 0o700


# ---------------------------------------------------------------- 10-11 Auth0 refresh
def _seed_auth(**extra):
    from mcptoai_linux.auth import DEVICE_AUTH_KEY
    bundle = {"owner_sub": "auth0|me", "device_id": "dev-1", "refresh_token": "rt0", **extra}
    ss.set_secret(DEVICE_AUTH_KEY, json.dumps(bundle))


def test_10_concurrent_refresh_in_process_single_network_call(isolated_vault, cfg, tmp_path, monkeypatch):
    from fake_auth0 import handler_for, init_state, read_state
    from mcptoai_linux import auth
    state = str(tmp_path / "auth0.json"); init_state(state); _seed_auth()
    real = httpx.AsyncClient
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler_for(state)), **kw))
    async def go():
        return await asyncio.gather(*[auth.get_access_token(cfg) for _ in range(10)])
    tokens = asyncio.run(go())
    st = read_state(state)
    assert st["reuse"] == 0 and st["refreshes"] == 1 and set(tokens) == {"at1"}
    assert auth._auth_bundle()["refresh_token"] == "rt1"


def test_10b_11_concurrent_refresh_across_processes_no_stale_reuse(file_backend, tmp_path):
    from fake_auth0 import init_state, read_state
    state = str(tmp_path / "auth0.json"); init_state(state); _seed_auth()
    procs = [_worker(file_backend.root, "refresh", 3.0, state) for _ in range(4)]
    results = []
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err[-2000:]
        results.append(json.loads(out.strip().splitlines()[-1]))
    st = read_state(state)
    assert st["reuse"] == 0, st                               # eski refresh token hiç kullanılmadı
    assert all(r["errors"] == 0 for r in results), results
    assert st["refreshes"] >= 2                               # rotasyon gerçekten çalıştı
    from mcptoai_linux.auth import _auth_bundle
    assert _auth_bundle()["refresh_token"] == st["current"]  # kasada en güncel token


def test_11b_refresh_uses_token_written_by_other_process(isolated_vault, cfg, tmp_path, monkeypatch):
    """Bellekte eski token tutulmaz: başka süreç döndürdüyse yenisi kullanılır."""
    from fake_auth0 import handler_for, init_state, read_state
    from mcptoai_linux import auth
    state = str(tmp_path / "auth0.json"); init_state(state, first_refresh="rt5"); _seed_auth()
    real = httpx.AsyncClient
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler_for(state)), **kw))
    _seed_auth(refresh_token="rt5")                           # "başka süreç" döndürdü
    assert asyncio.run(auth.get_access_token(cfg)) == "at1"
    assert read_state(state)["reuse"] == 0


def test_refresh_skipped_when_valid_access_token_exists(isolated_vault, cfg, monkeypatch):
    from mcptoai_linux import auth
    _seed_auth(access_token="AT", access_expires_at=time.time() + 3600)
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kw: (_ for _ in ()).throw(AssertionError("no network")))
    assert asyncio.run(auth.get_access_token(cfg)) == "AT"


def test_failed_refresh_keeps_existing_refresh_token(isolated_vault, cfg, monkeypatch):
    from mcptoai_linux import auth
    _seed_auth()
    real = httpx.AsyncClient
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(500)), **kw))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(auth.get_access_token(cfg))
    assert auth._auth_bundle()["refresh_token"] == "rt0"


# ---------------------------------------------------------------- 12 MCP OAuth
def test_sdk_internals_used_by_safe_provider_exist():
    from mcp.client.auth import OAuthClientProvider
    from mcp.client.auth.oauth2 import OAuthContext
    for name in ("_auth_flow", "_initialize", "_refresh_token", "_handle_refresh_response"):
        assert hasattr(OAuthClientProvider, name)
    assert "token_expiry_time" in OAuthContext.__dataclass_fields__
    assert "current_tokens" in OAuthContext.__dataclass_fields__


def _provider(server_id, token_url):
    from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthMetadata
    from mcptoai_linux.mcp_oauth import FileTokenStorage, SafeOAuthClientProvider
    meta = OAuthClientMetadata(client_name="t", redirect_uris=["https://app.example/cb"])
    p = SafeOAuthClientProvider("https://mcp.example/mcp", meta, FileTokenStorage(server_id))
    p.context.oauth_metadata = OAuthMetadata(issuer="https://mcp.example", authorization_endpoint="https://mcp.example/authorize",
                                             token_endpoint=token_url)
    return p


async def _drive(provider, transport):
    """httpx yerine auth akışını elle sürer; yapılan istekleri döndürür."""
    req = httpx.Request("GET", "https://mcp.example/mcp")
    flow = provider.async_auth_flow(req); sent = []
    out = await flow.__anext__()
    try:
        while True:
            sent.append(out)
            resp = transport.handle_request(out) if out is not req else httpx.Response(200)
            resp.request = out
            out = await flow.asend(resp)
    except StopAsyncIteration:
        pass
    return sent


def test_12_mcp_oauth_rotation_two_instances_single_refresh(isolated_vault, tmp_path):
    from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
    from mcptoai_linux.mcp_oauth import FileTokenStorage
    refreshes = {"n": 0, "reuse": 0, "current": "mrt0"}
    def handler(request):
        rt = dict(x.split("=") for x in request.content.decode().split("&"))["refresh_token"]
        if rt != refreshes["current"]:
            refreshes["reuse"] += 1; return httpx.Response(400, json={"error": "invalid_grant"})
        refreshes["n"] += 1; refreshes["current"] = f"mrt{refreshes['n']}"
        return httpx.Response(200, json={"access_token": f"mat{refreshes['n']}", "refresh_token": refreshes["current"],
                                         "token_type": "Bearer", "expires_in": 3600})
    transport = httpx.MockTransport(handler)
    async def go():
        st = FileTokenStorage("srv1")
        await st.set_client_info(OAuthClientInformationFull(client_id="c", redirect_uris=["https://app.example/cb"]))
        await st.set_tokens(OAuthToken(access_token="mat0", refresh_token="mrt0", token_type="Bearer", expires_in=3600))
        a, b = _provider("srv1", "https://mcp.example/token"), _provider("srv1", "https://mcp.example/token")
        await a._initialize(); await b._initialize()
        # İki "süreç" de token'ın süresinin dolduğunu görüyor (bellekte mrt0 var)
        a.context.token_expiry_time = b.context.token_expiry_time = time.time() - 1
        ss.set_secret("mcp:srv1:oauth_tokens", json.dumps({"token": json.loads((await st.get_tokens()).model_dump_json()), "expires_at": time.time() - 1}))
        sent_a = await _drive(a, transport)
        sent_b = await _drive(b, transport)                    # A'nın yazdığını görmeli
        return sent_a, sent_b
    sent_a, sent_b = asyncio.run(go())
    assert refreshes == {"n": 1, "reuse": 0, "current": "mrt1"}
    assert len(sent_a) == 2 and len(sent_b) == 1               # B ağda yenileme yapmadı
    assert sent_b[0].headers["Authorization"] == "Bearer mat1"
    stored = json.loads(ss.get_secret("mcp:srv1:oauth_tokens"))
    assert stored["token"]["refresh_token"] == "mrt1" and stored["expires_at"] > time.time()


def test_12b_mcp_oauth_token_written_by_other_process_is_visible(file_backend):
    _run_worker(file_backend.root, "oauth_set", "srv9", "ACCESS9", "REFRESH9")
    from mcptoai_linux.mcp_oauth import FileTokenStorage
    tok = asyncio.run(FileTokenStorage("srv9").get_tokens())
    assert tok.access_token == "ACCESS9" and tok.refresh_token == "REFRESH9"


def test_12c_corrupt_mcp_token_is_error(isolated_vault):
    from mcptoai_linux.mcp_oauth import FileTokenStorage
    ss.set_secret("mcp:s:oauth_tokens", "{bad")
    with pytest.raises(ss.CredentialStoreError):
        asyncio.run(FileTokenStorage("s").get_tokens())


def test_12d_remove_server_deletes_oauth_and_map_secrets(isolated_vault, tmp_path, monkeypatch):
    import mcptoai_linux.mcp_config as mc
    monkeypatch.setattr(mc, "PATH", tmp_path / "mcp.json")
    s = mc.add_server("r", transport="streamable-http", url="https://example.com/mcp", headers={"Authorization": "Bearer H"}, env={"E": "1"})
    ss.set_secret(f"mcp:{s['id']}:oauth_tokens", "{}")
    assert any(k.startswith(f"mcp:{s['id']}:") for k in ss.read_vault())
    mc.remove_server(s["id"])
    assert not any(k.startswith(f"mcp:{s['id']}:") for k in (ss.read_vault() or {}))


# ---------------------------------------------------------------- 13-14 provider anahtarı
def test_13_14_provider_key_replace_and_delete_visible_across_processes(file_backend):
    _run_worker(file_backend.root, "setkey", "evren", "KEY-A")
    fp_a = ss.provider_key_fingerprint("evren")
    assert ss.get_secret("api_key:evren") == "KEY-A"
    _run_worker(file_backend.root, "setkey", "evren", "KEY-B")    # Desktop anahtarı değiştirdi
    assert ss.get_secret("api_key:evren") == "KEY-B"             # uzun ömürlü süreç yenisini görür
    fp_b = ss.provider_key_fingerprint("evren")
    assert fp_a != fp_b and "KEY" not in fp_b                     # oturum anahtarı değişir, sır içermez
    _run_worker(file_backend.root, "delkey", "evren")
    assert ss.get_secret("api_key:evren") is None and ss.provider_key_fingerprint("evren") == "none"


def test_make_provider_reads_current_key(isolated_vault):
    from mcptoai_linux.config import settings
    from mcptoai_linux.providers import make_provider
    cfg = replace(settings, provider="evren")
    ss.set_secret("api_key:evren", "K1"); p1 = make_provider(cfg)
    ss.set_secret("api_key:evren", "K2"); p2 = make_provider(cfg)
    assert p1 is not p2
    ss.delete_secret("api_key:evren")
    with pytest.raises(RuntimeError):
        make_provider(cfg)


# ---------------------------------------------------------------- 15-17 cihaz kimliği
def test_15_signing_key_generated_once_concurrently(file_backend):
    procs = [_worker(file_backend.root, "keygen") for _ in range(4)]
    keys = set()
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err[-2000:]
        keys.add(out.strip())
    assert len(keys) == 1                                      # tek kimlik
    from mcptoai_linux.paths import config_dir
    marker = config_dir() / "identity.pub"
    assert marker.read_text(encoding="utf-8").strip() == keys.pop()


def test_16_identity_unchanged_across_restart_and_processes(file_backend):
    first = _run_worker(file_backend.root, "keygen")
    assert _run_worker(file_backend.root, "pubkey") == first
    assert _run_worker(file_backend.root, "keygen") == first   # create=True da değiştirmez
    from mcptoai_linux.auth import _device_public_key_b64
    assert _device_public_key_b64() == first


def test_17_corrupt_vault_never_generates_new_key(isolated_vault):
    from mcptoai_linux.auth import _device_public_key_b64
    isolated_vault.data["vault"] = "{corrupt"
    with pytest.raises(ss.VaultCorruptError):
        _device_public_key_b64(create=True)
    assert isolated_vault.data == {"vault": "{corrupt"}


def test_17b_read_failure_never_generates_new_key(isolated_vault):
    from mcptoai_linux.auth import _device_public_key_b64
    isolated_vault.fail_get.add("vault")
    with pytest.raises(ss.CredentialBackendError):
        _device_public_key_b64(create=True)
    assert "vault" not in isolated_vault.data


def test_17c_marker_without_key_refuses_new_identity(isolated_vault):
    from mcptoai_linux.auth import DeviceIdentityError, _device_public_key_b64, identity_marker_path
    identity_marker_path().parent.mkdir(parents=True, exist_ok=True)
    identity_marker_path().write_text("OLDPUB\n")
    with pytest.raises(DeviceIdentityError):
        _device_public_key_b64(create=True)
    assert ss.get_secret("device_signing_ed25519") is None


def test_17d_registered_device_without_key_refuses_new_identity(isolated_vault):
    from mcptoai_linux.auth import DeviceIdentityError, _device_public_key_b64
    _seed_auth()
    with pytest.raises(DeviceIdentityError):
        _device_public_key_b64(create=True)


def test_17e_marker_mismatch_is_error(isolated_vault):
    from mcptoai_linux.auth import DeviceIdentityError, _device_public_key_b64, identity_marker_path
    _device_public_key_b64(create=True)
    identity_marker_path().write_text("SOMETHINGELSE\n")
    with pytest.raises(DeviceIdentityError):
        _device_public_key_b64()


def test_17f_existing_device_never_creates_key(isolated_vault):
    from mcptoai_linux.auth import DeviceIdentityError, device_ws_proof
    with pytest.raises(DeviceIdentityError):
        device_ws_proof("dev-1")
    assert ss.get_secret("device_signing_ed25519") is None


def test_ws_proof_signature_verifies(isolated_vault):
    import base64
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from mcptoai_linux.auth import _device_public_key_b64, device_ws_proof
    pub = _device_public_key_b64(create=True)
    h = device_ws_proof("dev-1")
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(pub))
    key.verify(base64.b64decode(h["X-MCPtoAI-Device-Signature"]),
               f"dev-1:{h['X-MCPtoAI-Device-Timestamp']}:{h['X-MCPtoAI-Device-Nonce']}".encode())


# ---------------------------------------------------------------- 18-19 çıkış / temizlik
def test_18_logout_removes_session_keeps_identity(isolated_vault, cfg, monkeypatch):
    from mcptoai_linux import auth
    pub = auth._device_public_key_b64(create=True)
    _seed_auth(access_token="AT", access_expires_at=time.time() + 3600)
    real = httpx.AsyncClient
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(204)), **kw))
    asyncio.run(auth.disconnect_device(cfg))
    assert auth._auth_bundle() == {}
    assert auth._device_public_key_b64() == pub


def _run_cli(monkeypatch, *argv):
    from mcptoai_linux import __main__ as m
    monkeypatch.setattr(sys, "argv", ["mcptoai", *argv])
    m.main()


def test_19_clear_local_data_removes_everything(isolated_vault, monkeypatch, capsys):
    from mcptoai_linux import auth
    auth._device_public_key_b64(create=True)
    ss.set_secrets({"api_key:evren": "K", "mcp:x:oauth_tokens": "{}"})
    monkeypatch.setattr(auth, "disconnect_device", lambda cfg: asyncio.sleep(0))
    _run_cli(monkeypatch, "reset", "--yes")
    assert isolated_vault.data == {}
    assert not auth.identity_marker_path().exists()


def test_19b_clear_local_data_works_on_corrupt_vault(isolated_vault, monkeypatch):
    from mcptoai_linux import auth
    isolated_vault.data.update({"vault": "{corrupt", "vault.next": "{x"})
    monkeypatch.setattr(auth, "disconnect_device", lambda cfg: asyncio.sleep(0))
    _run_cli(monkeypatch, "reset", "--yes")
    assert isolated_vault.data == {}


def test_19c_failed_vault_delete_keeps_identity_marker(isolated_vault, monkeypatch):
    from mcptoai_linux import auth
    auth._device_public_key_b64(create=True)
    monkeypatch.setattr(auth, "disconnect_device", lambda cfg: asyncio.sleep(0))
    monkeypatch.setattr(isolated_vault, "delete", lambda a: (_ for _ in ()).throw(ss.CredentialBackendError("x")))
    # CLI hatayı tek satır mesaj ve çıkış kodu 1 ile bildirir (Python yığını göstermez).
    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, "reset", "--yes")
    assert exc.value.code == 1
    assert auth.identity_marker_path().exists()                # kimlik koruması sürüyor


def test_cli_keys_set_from_pipe_list_and_remove(isolated_vault, monkeypatch, capsys):
    # read -rs ... | mcptoai keys set <sağlayıcı> kullanımı: anahtar stdin'den (terminal değil) okunur.
    import io
    pipe = io.StringIO("SECRET-KEY\n")
    pipe.isatty = lambda: False
    monkeypatch.setattr(sys, "stdin", pipe)
    _run_cli(monkeypatch, "keys", "set", "evren")
    assert ss.get_secret("api_key:evren") == "SECRET-KEY"
    _run_cli(monkeypatch, "keys", "list")
    assert re.search(r"evren\s.*set", capsys.readouterr().out)
    _run_cli(monkeypatch, "keys", "remove", "evren")
    assert ss.get_secret("api_key:evren") is None
    assert "SECRET-KEY" not in capsys.readouterr().out


