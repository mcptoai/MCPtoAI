#!/usr/bin/env python3
"""Production relay end-to-end smoke test using the web role."""
from __future__ import annotations
import asyncio, json, os, uuid
import websockets
from mcptoai_agent.auth import get_access_token, _auth_bundle
from mcptoai_agent.config import Settings

async def main():
    cfg = Settings()
    device_id = _auth_bundle().get("device_id")  # cihaz kimliği device_auth paketinde
    if not device_id:
        raise SystemExit("Kayıtlı device_id yok. Önce mcptoai-agent login/connect çalıştırın.")
    token = await get_access_token(cfg)
    base = cfg.server_url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/")
    url = f"{base}/ws/web/{device_id}/"
    sid = str(uuid.uuid4())
    prompt = os.getenv("MCPTOAI_TEST_MESSAGE", "Masaüstündeki klasörlerin sadece isimlerini listele.")
    print(f"Device: {device_id}")
    print(f"Connecting: {url}")
    async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {token}"}, ping_interval=20, ping_timeout=20) as ws:
        print("Web relay connected")
        await ws.send(json.dumps({"type":"hello","role":"web","protocol":1}))
        await ws.send(json.dumps({"type":"message","session_id":sid,"message":prompt}, ensure_ascii=False))
        print("Sent:", prompt)
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=120)
            msg = json.loads(raw)
            if msg.get("type") == "presence":
                print("presence:", msg.get("role"), msg.get("status"))
                continue
            if msg.get("type") != "event" or msg.get("session_id") != sid:
                print("other:", json.dumps(msg, ensure_ascii=False))
                continue
            event = msg.get("event") or {}
            print("event:", json.dumps(event, ensure_ascii=False))
            if event.get("type") == "approval_required":
                await ws.send(json.dumps({"type":"approval","approval_id":event["approval_id"],"approve":True}))
                print("approval: approved for smoke test")
            if event.get("type") in {"done", "error"}:
                break

if __name__ == "__main__":
    asyncio.run(main())
