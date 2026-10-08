"""MCP OAuth depolaması ve süreçler arası güvenli token yenileme.

- Token'lar (access + refresh) kasada tutulur: `mcp:<id>:oauth_tokens`.
  Kayıt biçimi: {"token": <OAuthToken>, "expires_at": <unix zamanı|null>}
- Herkese açık istemci bilgisi (client_info) diskte, 0600 izinli dosyada durur.
- Önbellek yoktur: her okuma kasadan tazedir; bir sürecin yenilediği token
  diğer süreçlere hemen görünür.
- SafeOAuthClientProvider, token yenilemesini süreçler arası kilit altına alır:
  kilit → kasadan taze oku → (başka süreç yenilediyse) yenisini kullan, ağ
  isteği yok → değilse en güncel refresh token ile yenile → yaz/doğrula → bırak.
"""
from __future__ import annotations

import json
import logging
import os
import time
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from .credential_lock import CredentialLock, CredentialLockError
from .paths import config_dir
import threading
from .secret_store import CredentialStoreError, amutate, delete_secrets, get_secret

logger = logging.getLogger(__name__)

_oauth_locks: dict[str, CredentialLock] = {}
_oauth_locks_guard = threading.Lock()

def _oauth_lock(server_id: str) -> CredentialLock:
    # Refresh serialization must be separate from the vault mutation lock.
    # The MCP SDK may call token storage from a child asyncio task; holding the
    # vault lock across the network flow would deadlock that child on set_tokens.
    safe = "".join(c for c in str(server_id) if c.isalnum() or c in "-_")[:128] or "default"
    with _oauth_locks_guard:
        lock = _oauth_locks.get(safe)
        if lock is None:
            lock = _oauth_locks[safe] = CredentialLock(lambda s=safe: config_dir() / f"oauth-{s}.lock")
        return lock


def _root():
    return config_dir() / "oauth"


class FileTokenStorage:
    """MCP OAuth deposu: token'lar kasada, istemci bilgisi diskte."""

    def __init__(self, server_id: str):
        self.server_id = server_id
        self.token_key = f"mcp:{server_id}:oauth_tokens"
        self.client_secret_key = f"mcp:{server_id}:oauth:client_secret"
        self.last_expires_at: float | None = None

    @property
    def path(self):
        return _root() / f"{self.server_id}.json"

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        data.pop("tokens", None)  # eski düz metin token'lar asla kullanılmaz; sonraki yazımda silinir
        return data

    def _write(self, data: dict) -> None:
        root = _root()
        root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    async def get_tokens(self) -> OAuthToken | None:
        raw = get_secret(self.token_key)   # taze okuma
        if not raw:
            self.last_expires_at = None
            return None
        try:
            doc = json.loads(raw)
            token = OAuthToken.model_validate(doc["token"])
            exp = doc.get("expires_at")
        except (ValueError, TypeError, KeyError):
            raise CredentialStoreError("Stored MCP OAuth token is corrupt") from None
        self.last_expires_at = float(exp) if isinstance(exp, (int, float)) else None
        return token

    async def set_tokens(self, tokens: OAuthToken) -> None:
        exp = time.time() + tokens.expires_in if tokens.expires_in else None
        value = json.dumps({"token": tokens.model_dump(mode="json"), "expires_at": exp}, separators=(",", ":"))
        await amutate(lambda s: s.__setitem__(self.token_key, value))
        self.last_expires_at = exp

    async def get_client_info(self):
        v = self._read().get("client_info")
        if not v:
            return None
        v = dict(v)
        secret = get_secret(self.client_secret_key)
        if secret:
            v["client_secret"] = secret
        return OAuthClientInformationFull.model_validate(v)

    async def set_client_info(self, client_info):
        d = self._read()
        public = client_info.model_dump(mode="json")
        secret = public.pop("client_secret", None)
        d["client_info"] = public
        self._write(d)
        await amutate(lambda store: store.__setitem__(self.client_secret_key, secret) if secret else store.pop(self.client_secret_key, None))


OAUTH_CALLBACK_URL = "https://app.mcptoai.com/api/mcp/oauth/callback"

def oauth_metadata_for(server: dict) -> OAuthClientMetadata:
    oauth = server.get("oauth") or {}
    method = str(oauth.get("token_endpoint_auth_method") or ("client_secret_post" if oauth.get("client_id") else "none"))
    return OAuthClientMetadata(
        client_name="MCPtoAI",
        redirect_uris=[OAUTH_CALLBACK_URL],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method=method,
        scope=None,
    )

async def prepare_oauth_storage(server: dict) -> FileTokenStorage:
    """Return storage and seed a user-provided static OAuth client locally.

    The client secret comes from the OS credential vault via mcp_config.custom_servers()
    and is never written to mcp-tools.json or sent to MCPtoAI servers.
    """
    storage = FileTokenStorage(server["id"])
    oauth = server.get("oauth") or {}
    client_id = str(oauth.get("client_id") or "").strip()
    client_secret = str(oauth.get("client_secret") or "")
    if client_id:
        method = str(oauth.get("token_endpoint_auth_method") or "client_secret_post")
        if not client_secret and method != "none":
            raise CredentialStoreError("OAuth client secret is missing")
        info = OAuthClientInformationFull(
            client_id=client_id, client_secret=client_secret or None,
            redirect_uris=[OAUTH_CALLBACK_URL],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"], token_endpoint_auth_method=method,
            client_name="MCPtoAI",
            scope=None,
        )
        current = await storage.get_client_info()
        if not current or current.client_id != client_id or (current.client_secret or "") != client_secret or current.token_endpoint_auth_method != method:
            await storage.set_client_info(info)
    return storage


class SafeOAuthClientProvider(OAuthClientProvider):
    """Token yenilemesini süreçler arası kilitle koruyan OAuthClientProvider.

    Not: SDK'nın iç alanlarına (`_initialized`, `context.token_expiry_time`,
    `_auth_flow`) dayanır; testler bu alanların varlığını doğrular.
    """

    async def _reload_from_storage(self) -> None:
        storage = self.context.storage
        self.context.current_tokens = await storage.get_tokens()
        self.context.token_expiry_time = getattr(storage, "last_expires_at", None)

    async def _initialize(self) -> None:
        await super()._initialize()
        # SDK süreyi saklamaz; kasadaki mutlak bitiş zamanını geri yükle.
        self.context.token_expiry_time = getattr(self.context.storage, "last_expires_at", None)

    async def _auth_flow(self, request):
        held = False
        try:
            if not self._initialized:
                await self._initialize()
            if not self.context.is_token_valid() and self.context.can_refresh_token():
                refresh_lock = _oauth_lock(getattr(self.context.storage, "server_id", "default"))
                await refresh_lock.aacquire()
                held = True
                await self._reload_from_storage()          # refresh kilidi altında taze
                if self.context.is_token_valid():
                    refresh_lock.release(); held = False    # başka süreç yeniledi
            flow = super()._auth_flow(request)
            try:
                outgoing = await flow.__anext__()
                while True:
                    response = yield outgoing
                    outgoing = await flow.asend(response)
            except StopAsyncIteration:
                return
            finally:
                await flow.aclose()
        finally:
            if held:
                try:
                    refresh_lock.release()
                except CredentialLockError:
                    logger.error("MCP OAuth refresh lock could not be released by its owner")



def oauth_provider_for(server: dict, metadata, storage, redirect_handler, callback_handler):
    return SafeOAuthClientProvider(server["url"], metadata, storage, redirect_handler, callback_handler)


def delete_oauth_storage(server_id: str) -> None:
    storage = FileTokenStorage(server_id)
    delete_secrets([storage.token_key, storage.client_secret_key])
    try:
        storage.path.unlink()
    except FileNotFoundError:
        pass
