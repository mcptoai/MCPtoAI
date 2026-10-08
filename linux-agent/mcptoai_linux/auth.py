"""Auth0 entegrasyonu.

1) Cihaz eşleştirme: OAuth 2.0 Device Authorization Flow (RFC 8628).
   Uygulama bir kod gösterir, kullanıcı web'de giriş yapıp onaylar.
2) Gelen isteklerin doğrulanması: web arayüzünden gelen Bearer JWT,
   Auth0 JWKS ile doğrulanır ve sahibin 'sub' değeriyle eşleşmelidir.
"""

from __future__ import annotations

import asyncio
import time
import platform as platform_module
import socket
import json

import httpx
import jwt

from .config import Settings
from .credential_lock import async_credential_lock, credential_lock
from .paths import config_dir
from .secret_store import (
    CredentialStoreError, amutate, get_secret, mutate, read_vault, set_secret,
)

DEVICE_SIGNING_KEY = "device_signing_ed25519"
DEVICE_AUTH_KEY = "device_auth"
ACCESS_TOKEN_SKEW_SECONDS = 60
REFRESH_HTTP_TIMEOUT = 20


class DeviceIdentityError(CredentialStoreError):
    """Cihaz imza kimliği okunamadı ya da tutarsız; yeniden üretilmez."""


class DeviceRemovedError(RuntimeError):
    """The authenticated server confirmed that this device no longer exists."""


DEVICE_REMOVED_FILE = "device-removed.json"


def device_removed_path():
    return config_dir() / DEVICE_REMOVED_FILE


def device_removed_state() -> dict:
    try:
        data=json.loads(device_removed_path().read_text(encoding="utf-8"))
        return data if isinstance(data,dict) else {}
    except (FileNotFoundError,ValueError,TypeError,OSError):
        return {}


def _mark_device_removed(device_id: str) -> None:
    path=device_removed_path(); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps({"device_id":str(device_id)},separators=(",",":"))+"\n",encoding="utf-8")
    try:
        import os
        os.chmod(tmp,0o600)
    except OSError:
        pass
    tmp.replace(path)


def mark_device_removed(device_id: str) -> None:
    _mark_device_removed(device_id)


def _clear_device_removed() -> None:
    try: device_removed_path().unlink()
    except FileNotFoundError: pass


# --- Cihaz imza kimliği (Ed25519) ---------------------------------------------
# Kural: anahtar YALNIZCA temiz kurulumda, bir kez üretilir. Okuma/yazma hatası,
# bozuk kasa, mevcut identity.pub işareti ya da kayıtlı device_id varken anahtar
# eksikse ASLA yeni anahtar üretilmez; açık hata verilir. Böylece backend'deki
# TOFU bağlı public key korunur.

def identity_marker_path():
    return config_dir() / "identity.pub"


def _decode_private(raw: str):
    import base64
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    try:
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw, validate=True))
    except Exception:
        raise DeviceIdentityError("Device signing key is unreadable; a local reset is required") from None


def _public_b64(private) -> str:
    import base64
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    return base64.b64encode(private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode("ascii")


def _write_marker(public_b64: str) -> None:
    import os, secrets
    path = identity_marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Multiple processes may observe a freshly-created signing key before the
    # marker exists. Use a unique temp file so concurrent identical writes do
    # not fight over one identity.tmp on Windows.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        tmp.write_text(public_b64 + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _check_marker(public_b64: str) -> None:
    path = identity_marker_path()
    if path.exists():
        if path.read_text(encoding="utf-8").strip() != public_b64:
            raise DeviceIdentityError("Device signing key does not match identity.pub; a local reset is required")
        return
    # A freshly-created key can become visible to another process before the
    # marker write finishes. Serialize marker creation with the same process
    # lock used by the vault; the lock is re-entrant when already held.
    with credential_lock():
        if path.exists():
            if path.read_text(encoding="utf-8").strip() != public_b64:
                raise DeviceIdentityError("Device signing key does not match identity.pub; a local reset is required")
            return
        _write_marker(public_b64)


def _bundle_from(secrets: dict | None) -> dict:
    raw = (secrets or {}).get(DEVICE_AUTH_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise CredentialStoreError("Stored device authentication is corrupt") from None
    if not isinstance(data, dict):
        raise CredentialStoreError("Stored device authentication is corrupt")
    return data


def load_device_signing_key(create: bool = False):
    """Ed25519 özel anahtarını döndürür; `create=True` yalnız ilk kayıtta kullanılır."""
    raw = get_secret(DEVICE_SIGNING_KEY)          # bozuk kasa burada hata fırlatır
    if raw:
        private = _decode_private(raw)
        _check_marker(_public_b64(private))
        return private
    if not create:
        raise DeviceIdentityError("Device signing key is missing; pair this device again")
    with credential_lock():
        secrets = read_vault() or {}              # kilit altında taze okuma
        raw = secrets.get(DEVICE_SIGNING_KEY)
        if raw:                                   # başka süreç az önce üretti
            private = _decode_private(raw)
            _check_marker(_public_b64(private))
            return private
        if identity_marker_path().exists():
            raise DeviceIdentityError("identity.pub exists but the signing key is missing; refusing to create a new identity")
        if _bundle_from(secrets).get("device_id"):
            raise DeviceIdentityError("Device is registered but the signing key is missing; refusing to create a new identity")
        import base64
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
        private = Ed25519PrivateKey.generate()
        raw = base64.b64encode(private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode("ascii")
        set_secret(DEVICE_SIGNING_KEY, raw)       # kilit yeniden girilir; yazma doğrulanır
        if get_secret(DEVICE_SIGNING_KEY) != raw:
            raise DeviceIdentityError("Device signing key verification failed")
        _write_marker(_public_b64(private))
        return private


def _device_public_key_b64(create: bool = False) -> str:
    return _public_b64(load_device_signing_key(create=create))


def device_ws_proof(device_id: str) -> dict[str,str]:
    import base64, secrets as pysecrets, time as pytime
    private=load_device_signing_key(create=False)
    ts=str(int(pytime.time()))
    nonce=pysecrets.token_urlsafe(24)
    payload=f"{device_id}:{ts}:{nonce}".encode()
    signature=base64.b64encode(private.sign(payload)).decode("ascii")
    return {
        "X-MCPtoAI-Device-Timestamp":ts,
        "X-MCPtoAI-Device-Nonce":nonce,
        "X-MCPtoAI-Device-Signature":signature,
    }

async def ensure_device_public_key(cfg: Settings, access_token: str, device_id: str) -> None:
    key=_device_public_key_b64(create=False)
    async with httpx.AsyncClient(timeout=20) as http:
        r=await http.put(f"{cfg.server_url.rstrip('/')}/api/devices/{device_id}/public-key/",headers={"Authorization":f"Bearer {access_token}"},json={"public_key":key})
        if r.status_code == 404:
            removed=False
            try:
                ctype=str(r.headers.get("content-type") or "").split(";",1)[0].strip().lower()
                body=r.json() if ctype == "application/json" else None
                if isinstance(body,dict):
                    if body.get("code") == "device_not_found":
                        removed=True
                    elif body == {"detail":"Device not found"}:
                        removed=True
            except Exception:
                removed=False
            if removed:
                _mark_device_removed(device_id)
                raise DeviceRemovedError("This device was removed from MCPtoAI. Sign in again to pair it.")
        r.raise_for_status()


# --- Cihaz oturumu (device_auth) ----------------------------------------------
# Önbellek yok: her çağrı anahtarlıktan taze okur. Dönen (rotating) refresh
# token'ın eski bir kopyası hiçbir süreçte bellekte tutulmaz.

def _auth_bundle() -> dict:
    return _bundle_from(read_vault())


def _merge_auth(updates: dict):
    clean = {k: v for k, v in updates.items() if v is not None}
    def fn(secrets: dict) -> None:
        current = _bundle_from(secrets)             # kilit altındaki taze içerik
        current.update(clean)
        secrets[DEVICE_AUTH_KEY] = json.dumps(current, separators=(",", ":"), sort_keys=True)
    return fn


def _save_auth(**updates) -> dict:
    return _bundle_from(mutate(_merge_auth(updates)))


async def _asave_auth(**updates) -> dict:
    return _bundle_from(await amutate(_merge_auth(updates)))


def _access_token_valid(bundle: dict) -> bool:
    token = bundle.get("access_token")
    exp = bundle.get("access_expires_at")
    return bool(token) and isinstance(exp, (int, float)) and exp - ACCESS_TOKEN_SKEW_SECONDS > time.time()


async def device_login(cfg: Settings) -> str:
    """Cihazı kullanıcının hesabına bağlar ve sahibin 'sub' değerini döndürür."""
    if not (cfg.auth0_domain and cfg.auth0_device_client_id and cfg.auth0_audience):
        raise RuntimeError("AUTH0_DOMAIN / AUTH0_DEVICE_CLIENT_ID / AUTH0_AUDIENCE eksik")

    base = f"https://{cfg.auth0_domain}"
    async with httpx.AsyncClient(timeout=20) as http:
        r = await http.post(f"{base}/oauth/device/code", data={
            "client_id": cfg.auth0_device_client_id,
            "scope": "openid profile offline_access",
            "audience": cfg.auth0_audience,
        })
        r.raise_for_status()
        code = r.json()

        print("\nCihazı hesabınıza bağlamak için şu adresi açın:")
        print(f"  {code.get('verification_uri_complete') or code['verification_uri']}", flush=True)
        print(f"Kod: {code['user_code']}\n")

        interval = int(code.get("interval", 5))
        deadline = time.monotonic() + int(code.get("expires_in", 900))
        while time.monotonic() < deadline:
            await asyncio.sleep(interval)
            t = await http.post(f"{base}/oauth/token", data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": code["device_code"],
                "client_id": cfg.auth0_device_client_id,
            })
            body = t.json()
            if t.status_code == 200:
                claims = jwt.decode(body["access_token"], options={"verify_signature": False})
                sub = claims["sub"]
                if device_removed_state():
                    def clear_removed_device_id(secrets: dict) -> None:
                        current=_bundle_from(secrets)
                        current.pop("device_id",None)
                        secrets[DEVICE_AUTH_KEY]=json.dumps(current,separators=(",",":"),sort_keys=True)
                    await amutate(clear_removed_device_id)
                    _clear_device_removed()
                expires_in = body.get("expires_in")
                expires_in = int(expires_in) if isinstance(expires_in, (int, float)) and expires_in > 0 else 300
                await _asave_auth(owner_sub=sub, refresh_token=body.get("refresh_token"),
                                  access_token=body["access_token"], access_expires_at=time.time() + expires_in)
                await register_device(cfg, body["access_token"])
                return sub
            err = body.get("error")
            if err == "slow_down":
                interval += 5
            elif err != "authorization_pending":
                raise RuntimeError(f"Eşleştirme başarısız: {err} {body.get('error_description', '')}")
    raise TimeoutError("Eşleştirme kodunun süresi doldu")


async def register_device(cfg: Settings, access_token: str | None = None) -> str:
    existing = _auth_bundle().get("device_id")
    token = access_token or await get_access_token(cfg)
    if existing:
        removed=device_removed_state()
        if removed.get("device_id") == existing:
            raise DeviceRemovedError("This device was removed from MCPtoAI. Sign in again to pair it.")
        try:
            await ensure_device_public_key(cfg,token,existing)
        except DeviceRemovedError:
            raise
        except Exception:
            pass
        return existing
    system = platform_module.system().lower()
    platform_name = {"darwin": "macos", "windows": "windows", "linux": "linux"}.get(system, "linux")
    async with httpx.AsyncClient(timeout=20) as http:
        r = await http.post(
            f"{cfg.server_url.rstrip('/')}/api/devices/register/",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": socket.gethostname(), "platform": platform_name, "public_key": _device_public_key_b64(create=True)},
        )
        r.raise_for_status()
        device_id = r.json()["device_id"]
        await _asave_auth(device_id=device_id)
        await ensure_device_public_key(cfg,token,device_id)
        return device_id


async def get_access_token(cfg: Settings) -> str:
    """Geçerli bir access token döndürür; gerekirse kilit altında yeniler.

    Akış: kilidi al → kasayı taze oku → (başka süreç yenilediyse) geçerli token'ı
    kullan → değilse güncel refresh token ile Auth0'a git → dönen yeni refresh
    token'ı yaz ve doğrula → kilidi bırak. Ağ isteği bilinçli olarak kilit
    içindedir: refresh token rotation/reuse detection'da doğruluk önceliklidir.
    """
    bundle = _auth_bundle()
    if _access_token_valid(bundle):
        return bundle["access_token"]
    async with async_credential_lock():
        bundle = _auth_bundle()
        if _access_token_valid(bundle):
            return bundle["access_token"]
        refresh_token = bundle.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("Cihaz henüz eşleştirilmedi. Önce: mcptoai login")
        async with httpx.AsyncClient(timeout=REFRESH_HTTP_TIMEOUT) as http:
            r = await http.post(f"https://{cfg.auth0_domain}/oauth/token", data={
                "grant_type": "refresh_token", "client_id": cfg.auth0_device_client_id,
                "refresh_token": refresh_token, "audience": cfg.auth0_audience,
            })
        r.raise_for_status(); body=r.json()
        access_token = body["access_token"]
        expires_in = body.get("expires_in")
        expires_in = int(expires_in) if isinstance(expires_in, (int, float)) and expires_in > 0 else 300
        await _asave_auth(
            access_token=access_token,
            access_expires_at=time.time() + expires_in,
            refresh_token=body.get("refresh_token") or refresh_token,
        )
        return access_token


class TokenVerifier:
    """Web'den gelen access token'ları doğrular ve sadece cihaz sahibine izin verir."""

    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.issuer = f"https://{cfg.auth0_domain}/"
        self.jwks = jwt.PyJWKClient(f"{self.issuer}.well-known/jwks.json", cache_keys=True)

    def verify(self, token: str) -> dict:
        key = self.jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, key, algorithms=["RS256"],
            audience=self.cfg.auth0_audience, issuer=self.issuer,
        )
        owner = _auth_bundle().get("owner_sub")
        if not owner:
            raise PermissionError("Cihaz henüz eşleştirilmedi (mcptoai-agent login)")
        if claims.get("sub") != owner:
            raise PermissionError("Bu cihaz başka bir hesaba ait")
        return claims


async def disconnect_device(cfg: Settings) -> None:
    device_id=_auth_bundle().get("device_id")
    try:
        if device_id:
            token=await get_access_token(cfg)
            async with httpx.AsyncClient(timeout=20) as http:
                r=await http.delete(f"{cfg.server_url.rstrip('/')}/api/devices/{device_id}/",headers={"Authorization":f"Bearer {token}"})
                if r.status_code not in {204,404}:
                    r.raise_for_status()
    finally:
        # Yalnız oturum silinir; imza kimliği ve provider anahtarları korunur.
        await amutate(lambda s: s.pop(DEVICE_AUTH_KEY, None))
        _clear_device_removed()
