"""Yerel HTTP uç noktası: yalnızca 127.0.0.1 üzerinde dinler (geliştirme ve yerel entegrasyon).

Uzak erişim bu modülden değil, cihazın dışarıya doğru açtığı WebSocket bağlantısıyla
(relay_client.py) sağlanır; cihazda gelen bağlantı için port açılmaz.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from .agent import AgentSession
from .auth import TokenVerifier
from .config import Settings
from .providers import make_provider
from .tools import build_server

logger = logging.getLogger("mcptoai.relay")

APPROVAL_TIMEOUT = 120  # sn; yanıt gelmezse reddedilmiş sayılır


def create_app(cfg: Settings) -> Starlette:
    verifier = TokenVerifier(cfg)
    server = build_server(cfg)
    sessions: dict[str, AgentSession] = {}
    pending: dict[str, tuple[asyncio.Future, AgentSession, str]] = {}

    def _auth(request: Request) -> dict:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise PermissionError("Bearer token gerekli")
        return verifier.verify(header[7:])

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "provider": cfg.provider, "model": cfg.model})

    async def chat(request: Request):
        try:
            _auth(request)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=401)

        body = await request.json()
        message = (body.get("message") or "").strip()
        if not message:
            return JSONResponse({"error": "message boş"}, status_code=400)
        sid = body.get("session_id") or str(uuid.uuid4())
        session = sessions.get(sid)
        if session is None:
            session = sessions[sid] = AgentSession(cfg, make_provider(cfg), server)

        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        async def emit(event: dict) -> None:
            await queue.put(event)

        async def approver(tool: str, args: dict) -> bool:
            # Kullanıcı uzakta: onay isteği web arayüzüne gider
            approval_id = str(uuid.uuid4())
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            pending[approval_id] = (fut, session, tool)
            await emit({"type": "approval_required", "approval_id": approval_id, "tool": tool, "arguments": args})
            try:
                return await asyncio.wait_for(fut, timeout=cfg.approval_timeout_seconds)
            except asyncio.TimeoutError:
                return False
            finally:
                pending.pop(approval_id, None)

        async def worker() -> None:
            try:
                await session.run(message, approver, emit)
            except Exception as exc:
                logger.exception("Agent hatası")
                await emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            finally:
                await queue.put(None)

        async def stream():
            yield f"event: session\ndata: {json.dumps({'session_id': sid})}\n\n"
            task = asyncio.create_task(worker())
            try:
                while (event := await queue.get()) is not None:
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            finally:
                if not task.done():
                    task.cancel()

        return StreamingResponse(stream(), media_type="text/event-stream")

    async def approve(request: Request) -> JSONResponse:
        try:
            _auth(request)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=401)
        entry = pending.get(request.path_params["approval_id"])
        if entry is None:
            return JSONResponse({"error": "Onay bulunamadı veya süresi doldu"}, status_code=404)
        fut, session, tool = entry
        body = await request.json()
        ok = bool(body.get("approve"))
        if ok and body.get("remember"):
            session.policy.session_grants.add(tool)
        if not fut.done():
            fut.set_result(ok)
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[
            Route("/health", health),
            Route("/v1/chat", chat, methods=["POST"]),
            Route("/v1/approvals/{approval_id}", approve, methods=["POST"]),
        ],
        middleware=[Middleware(
            CORSMiddleware, allow_origins=[cfg.web_origin],
            allow_methods=["GET", "POST"], allow_headers=["authorization", "content-type"],
        )],
    )
