"""Çok süreçli testler için yardımcı süreç.

Kullanım: python vault_worker.py <backend_dir> <mod> [argümanlar...]
HOME ortam değişkeni ana testten gelir (kilit dosyası ortak olsun diye).
Gerçek Keychain her zaman engellenir.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from vault_backends import FileBackend, block_real_keyring  # noqa: E402


class _Patcher:
    def setattr(self, obj, name, value):
        setattr(obj, name, value)


def main() -> None:
    backend_dir, mode, *rest = sys.argv[1:]
    block_real_keyring(_Patcher())
    from mcptoai_linux import secret_store
    secret_store.set_backend(FileBackend(backend_dir))

    if mode == "inc":
        n, wid = int(rest[0]), rest[1]
        for i in range(n):
            def fn(s, i=i):
                s["counter"] = str(int(s.get("counter", "0")) + 1)
                s[f"w{wid}:{i}"] = "x"
            secret_store.mutate(fn)
        print("done")

    elif mode == "keygen":
        from mcptoai_linux.auth import _device_public_key_b64
        print(_device_public_key_b64(create=True))

    elif mode == "pubkey":
        from mcptoai_linux.auth import _device_public_key_b64
        print(_device_public_key_b64(create=False))

    elif mode == "setkey":
        secret_store.set_secret(secret_store.api_key_name(rest[0]), rest[1]); print("ok")

    elif mode == "delkey":
        secret_store.delete_secret(secret_store.api_key_name(rest[0])); print("ok")

    elif mode == "oauth_set":
        from mcp.shared.auth import OAuthToken
        from mcptoai_linux.mcp_oauth import FileTokenStorage
        tok = OAuthToken(access_token=rest[1], refresh_token=rest[2], token_type="Bearer", expires_in=3600)
        asyncio.run(FileTokenStorage(rest[0]).set_tokens(tok)); print("ok")

    elif mode == "refresh":
        duration, state_file = float(rest[0]), rest[1]
        import httpx
        from dataclasses import replace
        from mcptoai_linux import auth
        from mcptoai_linux.config import settings
        sys.path.insert(0, str(Path(__file__).parent))
        from fake_auth0 import handler_for
        real_client = httpx.AsyncClient
        auth.httpx.AsyncClient = lambda **kw: real_client(transport=httpx.MockTransport(handler_for(state_file)), **kw)
        cfg = replace(settings, auth0_domain="auth.test", auth0_device_client_id="cid", auth0_audience="aud")
        errors = calls = 0

        async def run():
            nonlocal errors, calls
            end = time.monotonic() + duration
            while time.monotonic() < end:
                try:
                    await auth.get_access_token(cfg); calls += 1
                except Exception:
                    errors += 1
                await asyncio.sleep(0.005)
        asyncio.run(run())
        print(json.dumps({"errors": errors, "calls": calls}))
    else:
        raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    main()
