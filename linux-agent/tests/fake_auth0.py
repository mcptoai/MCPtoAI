"""Refresh token rotation + reuse detection uygulayan sahte Auth0 token uç noktası.

Durum bir dosyada tutulur ve dosya kilidiyle güncellenir; böylece birden çok
süreç aynı sahte sunucuyu paylaşır. Eski (zaten kullanılmış) bir refresh token
gelirse `reuse` sayacı artar ve 403 invalid_grant döner — gerçek Auth0'da bu
durum tüm token ailesinin iptali demektir.
"""
from __future__ import annotations

import json
import os
from urllib.parse import parse_qs

import httpx


if os.name == "nt":
    import msvcrt

    def _lock_file(f):
        f.seek(0, os.SEEK_END)
        if f.tell() == 0:
            f.write(b"\0")
            f.flush()
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)

    def _unlock_file(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock_file(f):
        fcntl.flock(f, fcntl.LOCK_EX)

    def _unlock_file(f):
        fcntl.flock(f, fcntl.LOCK_UN)

ACCESS_LIFETIME = 61  # agent 60 sn pay bıraktığı için ~1 sn geçerli; sık yenileme zorlanır


def init_state(path: str, first_refresh: str = "rt0") -> None:
    with open(path, "w") as f:
        json.dump({"current": first_refresh, "seq": 0, "refreshes": 0, "reuse": 0}, f)


def read_state(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def handler_for(path: str):
    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        presented = form.get("refresh_token", [""])[0]
        with open(path + ".lock", "a+b") as lf:
            _lock_file(lf)
            try:
                st = read_state(path)
                if presented != st["current"]:
                    st["reuse"] += 1
                    with open(path, "w") as f:
                        json.dump(st, f)
                    return httpx.Response(403, json={"error": "invalid_grant"})
                st["seq"] += 1
                st["refreshes"] += 1
                st["current"] = f"rt{st['seq']}"
                with open(path, "w") as f:
                    json.dump(st, f)
                return httpx.Response(200, json={
                    "access_token": f"at{st['seq']}", "refresh_token": st["current"],
                    "expires_in": ACCESS_LIFETIME, "token_type": "Bearer",
                })
            finally:
                _unlock_file(lf)
    return handler
