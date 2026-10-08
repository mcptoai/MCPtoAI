from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse

import httpx
from fastmcp import FastMCP

from .paths import config_dir
from .secret_store import get_secret, aset_secret, adelete_secret

MANAGED_CLIENT_ID = os.environ.get("MCPTOAI_GOOGLE_DESKTOP_CLIENT_ID", "").strip()
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DRIVE_API = "https://www.googleapis.com/drive/v3"
SCOPE = "https://www.googleapis.com/auth/drive.file"
TOKEN_KEY = "google_drive:oauth_tokens"
CLIENT_SECRET_KEY = "google_drive:desktop_client_secret"
CONFIG_PATH = config_dir() / "google-drive.json"


def _load_config() -> dict:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_config(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG_PATH)


def _selected_ids() -> list[str]:
    values = _load_config().get("selected_file_ids") or []
    if not isinstance(values, list):
        return []
    out = []
    for value in values:
        value = str(value)
        if value and len(value) <= 256 and value not in out:
            out.append(value)
    return out[:500]


def _assert_selected(file_id: str) -> str:
    value = str(file_id or "").strip()
    if value not in set(_selected_ids()):
        raise PermissionError("This Google Drive file was not selected with Google Picker")
    return value


def _load_tokens() -> dict:
    raw = get_secret(TOKEN_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


async def _save_tokens(payload: dict, previous: dict | None = None) -> None:
    previous = previous or {}
    expires_in = payload.get("expires_in")
    try:
        expires_at = time.time() + max(0, int(expires_in))
    except Exception:
        expires_at = time.time() + 300
    data = {
        "access_token": str(payload.get("access_token") or ""),
        "refresh_token": str(payload.get("refresh_token") or previous.get("refresh_token") or ""),
        "token_type": str(payload.get("token_type") or previous.get("token_type") or "Bearer"),
        "scope": str(payload.get("scope") or previous.get("scope") or SCOPE),
        "expires_at": expires_at,
    }
    if not data["access_token"]:
        raise RuntimeError("Google did not return an access token")
    await aset_secret(TOKEN_KEY, json.dumps(data, separators=(",", ":")))


# Sunucudan yalnızca herkese açık masaüstü client bilgisi alınır (ID ve Google'ın
# gizli saymadığı Desktop client secret'ı). Google token'ları bu adrese ASLA
# gönderilmez; alışveriş ve yenileme doğrudan Google ile yapılır.
DESKTOP_CLIENT_CONFIG_PATH = "/api/integrations/google-drive/config/"
DESKTOP_CLIENT_MODE = "drive-file-picker-desktop"


def _desktop_client_config_url() -> str:
    from .config import settings
    return settings.server_url.rstrip("/") + DESKTOP_CLIENT_CONFIG_PATH


async def _managed_client() -> tuple[str, str]:
    """MCPtoAI'nin Google Desktop OAuth client'ını döndürür: (client_id, client_secret).

    Öncelik yerel ortam değişkenlerindedir (geliştirme/özel derleme). Yoksa bilgi
    MCPtoAI sunucusundan alınır; böylece client değiştiğinde uygulamayı yeniden
    derlemek gerekmez. Google, Desktop client'larda PKCE kullanılsa bile token
    alışverişinde client_secret istediği için secret de döndürülür.
    """
    env_id = MANAGED_CLIENT_ID or os.environ.get("MCPTOAI_GOOGLE_DESKTOP_CLIENT_ID", "").strip()
    if env_id:
        return env_id, os.environ.get("MCPTOAI_GOOGLE_DESKTOP_CLIENT_SECRET", "").strip()
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.get(_desktop_client_config_url(), headers={"Accept": "application/json"})
        data = response.json() if response.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        raise RuntimeError("Could not reach MCPtoAI to start Google sign-in. Check your connection and try again.") from None
    client_id = str(data.get("client_id") or "").strip() if isinstance(data, dict) else ""
    client_secret = str(data.get("client_secret") or "").strip() if isinstance(data, dict) else ""
    # Yanıtın gerçekten masaüstü/drive.file yapılandırması olduğunu doğrula; eski web
    # client yapılandırması ya da beklenmedik bir yanıt asla kullanılmaz.
    valid = (
        isinstance(data, dict)
        and data.get("enabled") is True
        and data.get("mode") == DESKTOP_CLIENT_MODE
        and data.get("redirect_mode") == "loopback"
        and data.get("scope") == SCOPE
        and client_id.endswith(".apps.googleusercontent.com")
        and len(client_id) <= 256
        and len(client_secret) <= 256
    )
    if not valid:
        raise RuntimeError("MCPtoAI Google Drive sign-in is not available right now. Try again later or use your own OAuth app.")
    return client_id, client_secret


async def _exchange_direct(fields: dict, client_secret: str = "") -> dict:
    payload = dict(fields)
    if client_secret:
        payload["client_secret"] = client_secret
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(GOOGLE_TOKEN_URL, data=payload, headers={"Accept": "application/json"})
    data = response.json() if response.content else {}
    if response.status_code >= 400:
        raise RuntimeError(str(data.get("error_description") or data.get("error") or f"Google token exchange failed ({response.status_code})"))
    return data


async def _start_loopback(expected_state: str):
    loop = asyncio.get_running_loop()
    result = loop.create_future()

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            line = (await asyncio.wait_for(reader.readline(), timeout=5)).decode("latin-1", errors="replace").strip()
            parts = line.split(" ")
            target = parts[1] if len(parts) >= 2 else "/"
            while True:
                header = await asyncio.wait_for(reader.readline(), timeout=5)
                if header in {b"\r\n", b"\n", b""}:
                    break
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(target).query)
            state = (q.get("state") or [""])[0]
            code = (q.get("code") or [""])[0]
            error = (q.get("error") or q.get("error_description") or [""])[0]
            picked_raw = (q.get("picked_file_ids") or [""])[0]
            picked = [x.strip() for x in picked_raw.split(",") if x.strip() and len(x.strip()) <= 256][:500]
            valid = secrets.compare_digest(state, expected_state)
            ok = valid and bool(code) and not error
            if valid and not result.done():
                result.set_result({"code": code, "error": error, "picked_file_ids": picked, "state": state})
            if not valid:
                status, message = "400 Bad Request", "Invalid OAuth state. You can close this window."
            elif error:
                status, message = "400 Bad Request", "Google authorization failed. You can return to MCPtoAI."
            elif picked:
                status, message = "200 OK", "Google Drive files selected. You can return to MCPtoAI."
            else:
                status, message = "200 OK", "Authorization complete. You can return to MCPtoAI."
            body = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
                    "<title>MCPtoAI</title></head><body style='margin:0;background:#080c12;color:#e8edf5;font-family:system-ui;"
                    "display:grid;place-items:center;min-height:100vh'><main style='padding:32px;border:1px solid #303a49;"
                    "border-radius:16px;background:#111720;max-width:520px'><h1>MCPtoAI</h1><p>" + message + "</p></main></body></html>").encode()
            writer.write((f"HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\n"
                          f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode() + body)
            await writer.drain()
        except Exception as exc:
            if not result.done():
                result.set_exception(exc)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = int(server.sockets[0].getsockname()[1])
    return server, result, f"http://127.0.0.1:{port}"


async def authorize(draft: dict) -> dict:
    mode = str(draft.get("mode") or "managed")
    if mode not in {"managed", "byo"}:
        raise ValueError("Unsupported Google Drive connection mode")
    append = bool(draft.get("append"))
    if mode == "managed":
        client_id, client_secret = await _managed_client()
    else:
        client_id = str(draft.get("client_id") or "").strip()
        client_secret = str(draft.get("client_secret") or "")
        if not client_id or len(client_id) > 512 or len(client_secret.encode()) > 8192:
            raise ValueError("Desktop OAuth Client ID is required")

    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(32)
    server, future, redirect_uri = await _start_loopback(state)
    try:
        params = {
            "client_id": client_id,
            "scope": SCOPE,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
            "trigger_onepick": "true",
            "allow_multiple": "true",
            "include_granted_scopes": "false",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        auth_url = GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)
        print("AUTH_URL " + auth_url, flush=True)
        result = await asyncio.wait_for(future, timeout=600)
    finally:
        server.close()
        await server.wait_closed()

    if result.get("error"):
        raise RuntimeError(str(result.get("error")))
    if not result.get("code"):
        raise RuntimeError("Google authorization did not return a code")
    picked = [str(x) for x in (result.get("picked_file_ids") or []) if isinstance(x, str) and 0 < len(x) <= 256][:500]
    if not picked:
        raise RuntimeError("No Google Drive files were selected")

    fields = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": str(result["code"]),
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
    }
    token_data = await _exchange_direct(fields, client_secret)
    await _save_tokens(token_data, _load_tokens())
    if client_secret:
        await aset_secret(CLIENT_SECRET_KEY, client_secret)
    else:
        await adelete_secret(CLIENT_SECRET_KEY)

    previous = _selected_ids() if append else []
    merged = list(previous)
    for file_id in picked:
        if file_id not in merged:
            merged.append(file_id)
    _write_config({
        "version": 2,
        "mode": mode,
        "client_id": client_id,
        "redirect_mode": "loopback",
        "scope": SCOPE,
        "selected_file_ids": merged[:500],
        "updated_at": int(time.time()),
    })
    return {"ok": True, "mode": mode, "selected": len(merged), "added": len([x for x in picked if x not in previous])}


async def _access_token() -> str:
    cfg = _load_config()
    tokens = _load_tokens()
    if tokens.get("access_token") and float(tokens.get("expires_at") or 0) > time.time() + 60:
        return str(tokens["access_token"])
    refresh_token = str(tokens.get("refresh_token") or "")
    client_id = str(cfg.get("client_id") or "")
    if not refresh_token or not client_id:
        raise RuntimeError("Google Drive is not connected")
    fields = {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": refresh_token}
    client_secret = get_secret(CLIENT_SECRET_KEY) or ""
    data = await _exchange_direct(fields, client_secret)
    await _save_tokens(data, tokens)
    return str(data["access_token"])


async def _drive_get(path: str, *, params: dict | None = None) -> httpx.Response:
    token = await _access_token()
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        response = await client.get(
            DRIVE_API + path,
            params=params or {},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
    if response.status_code >= 400:
        detail = response.text[:800]
        try:
            body = response.json()
            detail = body.get("error", {}).get("message") or body.get("error_description") or detail
        except Exception:
            pass
        raise RuntimeError(f"Google Drive API error ({response.status_code}): {detail}")
    return response


async def _metadata(file_id: str) -> dict:
    file_id = _assert_selected(file_id)
    response = await _drive_get(
        "/files/" + urllib.parse.quote(file_id, safe=""),
        params={"fields": "id,name,mimeType,size,modifiedTime,createdTime,webViewLink,iconLink,parents"},
    )
    return response.json()


def build_google_drive_mcp() -> FastMCP:
    mcp = FastMCP("mcptoai-google-drive")

    @mcp.tool(description="List Google Drive files explicitly selected by the user with Google Picker.")
    async def list_selected_files() -> str:
        """List Google Drive files explicitly selected by the user with Google Picker."""
        items = []
        for file_id in _selected_ids():
            try:
                items.append(await _metadata(file_id))
            except Exception as exc:
                items.append({"id": file_id, "error": str(exc)[:300]})
        return json.dumps({"files": items}, ensure_ascii=False)

    @mcp.tool(description="Get metadata for a Google Drive file previously selected by the user.")
    async def get_file_metadata(file_id: str) -> str:
        """Get metadata for a Google Drive file previously selected by the user."""
        return json.dumps(await _metadata(file_id), ensure_ascii=False)

    @mcp.tool(description="Read content from a Google Drive file previously selected by the user.")
    async def read_file_content(file_id: str) -> str:
        """Read content from a Google Drive file previously selected by the user."""
        meta = await _metadata(file_id)
        mime = str(meta.get("mimeType") or "")
        fid = urllib.parse.quote(_assert_selected(file_id), safe="")
        export = {
            "application/vnd.google-apps.document": "text/plain",
            "application/vnd.google-apps.spreadsheet": "text/csv",
            "application/vnd.google-apps.presentation": "text/plain",
        }.get(mime)
        if export:
            response = await _drive_get(f"/files/{fid}/export", params={"mimeType": export})
        else:
            try:
                declared_size = int(meta.get("size") or 0)
            except (TypeError, ValueError):
                declared_size = 0
            if declared_size > 1024 * 1024:
                raise RuntimeError("Selected Google Drive file is larger than the 1 MiB tool response limit")
            textual = mime.startswith("text/") or mime in {
                "application/json", "application/xml", "application/javascript",
                "application/x-yaml", "application/yaml", "text/csv",
            }
            if not textual:
                raise RuntimeError("Binary Google Drive files are not returned as base64. Use a text/document export or a dedicated file transfer workflow.")
            response = await _drive_get(f"/files/{fid}", params={"alt": "media"})
        raw = response.content
        if len(raw) > 1024 * 1024:
            raise RuntimeError("Selected Google Drive file is larger than the 1 MiB tool response limit")
        return raw.decode(response.encoding or "utf-8", errors="replace")

    @mcp.tool(description="Search by name within only the Google Drive files explicitly selected by the user.")
    async def search_selected_files(query: str) -> str:
        """Search by name within only the Google Drive files explicitly selected by the user."""
        q = str(query or "").casefold().strip()
        matches = []
        for file_id in _selected_ids():
            try:
                meta = await _metadata(file_id)
                if not q or q in str(meta.get("name") or "").casefold():
                    matches.append(meta)
            except Exception:
                pass
        return json.dumps({"files": matches}, ensure_ascii=False)

    return mcp


def status() -> dict:
    cfg = _load_config()
    tokens = _load_tokens()
    return {
        "configured": bool(cfg.get("client_id")),
        "authorized": bool(tokens.get("access_token") or tokens.get("refresh_token")),
        "mode": cfg.get("mode") or "",
        "selected": len(_selected_ids()),
        "scope": cfg.get("scope") or "",
    }


async def disconnect() -> None:
    tokens = _load_tokens()
    revoke_token = str(tokens.get("refresh_token") or tokens.get("access_token") or "")
    if revoke_token:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    GOOGLE_REVOKE_URL,
                    params={"token": revoke_token},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
        except Exception:
            # Local disconnect must still complete if Google is temporarily unavailable.
            pass
    await adelete_secret(TOKEN_KEY)
    await adelete_secret(CLIENT_SECRET_KEY)
    try:
        CONFIG_PATH.unlink()
    except FileNotFoundError:
        pass
