"""Outbound WebSocket client for MCPtoAI relay. No inbound port is opened."""
from __future__ import annotations
from .paths import config_dir
import asyncio, collections, json, logging, random, uuid, os, time
from urllib.parse import urlparse, parse_qs
import websockets
import os
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from .mcp_oauth import OAUTH_CALLBACK_URL, oauth_metadata_for, oauth_provider_for, prepare_oauth_storage
import httpx
from .agent import AgentSession
from .auth import DeviceRemovedError, get_access_token, mark_device_removed, register_device, device_ws_proof
from .config import Settings
from .providers import make_provider, ToolSpec
from .tools import build_server
from .mcp_config import load_rules, save_rules, state as mcp_state, custom_servers, add_server, update_server, remove_server
from .policy import ToolPolicy, Decision
logger=logging.getLogger("mcptoai.relay_client")

from .cloud_chat import handle_cloud_chat_request
from .history import selected_history_provider_name

class RelayClient:
    def __init__(self,cfg:Settings):
        self.cfg=cfg; self.sessions={}; self._session_last_used={}; self.pending_approvals={}; self.ws=None; self._mcp_discovery_task=None; self._remote_tool_specs={}; self._remote_tool_map={}; self._mcp_discovered=None; self._mcp_discovered_at=0.0; self._ipc_server=None; self._stdio_runtimes={}
        # Bağlantı yokken üretilen sohbet olayları (ilerleme, onay isteği, son yanıt) burada
        # bekler ve yeniden bağlanınca sırayla gönderilir; en eskiler taşarsa düşer.
        self._outbox=collections.deque(maxlen=500)
        # Görev izleyicisi: web'e gönderilen son durumların imzası (yalnızca değişenler gider).
        self._job_sig={}; self._job_watch_task=None
        # Web'e en son bildirilen geçmiş tercihi; Desktop'tan değiştirilince yeniden bildirilir.
        self._history_sent=None
    async def _start_local_ipc(self):
        if os.name == "nt" or self._ipc_server: return
        from .paths import config_dir
        sock=config_dir()/"agent.sock"; sock.parent.mkdir(parents=True,exist_ok=True)
        try: sock.unlink()
        except FileNotFoundError: pass
        async def handle(reader,writer):
            try:
                raw=await asyncio.wait_for(reader.readline(),timeout=5)
                if len(raw)>4096: return
                req=json.loads(raw)
                out=await handle_cloud_chat_request(self.cfg, req)
                payload=json.dumps(out,ensure_ascii=False,default=str).encode()
                if len(payload)>4*1024*1024: payload=json.dumps({"ok":False,"error":"response_too_large"}).encode()
                writer.write(payload+b"\n"); await writer.drain()
            except Exception as exc:
                try: writer.write(json.dumps({"ok":False,"error":f"{type(exc).__name__}: {exc}"}).encode()+b"\n"); await writer.drain()
                except Exception: pass
            finally:
                writer.close(); await writer.wait_closed()
        self._ipc_server=await asyncio.start_unix_server(handle,path=str(sock)); os.chmod(sock,0o600)

    async def run_forever(self):
        await self._start_local_ipc()
        delay=1
        while True:
            try:
                token=await get_access_token(self.cfg)
                device_id=await register_device(self.cfg, token)
                relay_url=self.cfg.relay_url or self.cfg.server_url.replace("https://","wss://").replace("http://","ws://").rstrip("/")+f"/ws/device/{device_id}/"
                headers={"Authorization":f"Bearer {token}",**device_ws_proof(device_id)}
                async with websockets.connect(relay_url, additional_headers=headers, ping_interval=20, ping_timeout=20, max_size=2**20) as ws:
                    self.ws=ws; delay=1
                    await self._send({"type":"hello","role":"device","protocol":1})
                    logger.info("Relay connected: %s",relay_url)
                    await self._flush_outbox()
                    await self._send_jobs_snapshot()
                    # Web sormadan önce de geçmiş tercihini bildir (web bilmeden kaydetmesin).
                    await self._send_history_status()
                    if self._job_watch_task is None or self._job_watch_task.done():
                        self._job_watch_task=asyncio.create_task(self._watch_jobs())
                    asyncio.create_task(self._send_mcp_state())
                    async for raw in ws:
                        await self._handle(json.loads(raw))
            except asyncio.CancelledError: raise
            except DeviceRemovedError as exc:
                self.ws=None
                logger.error("Device was removed server-side; reconnect loop stopped until explicit re-pair: %s",exc)
                # Remain idle and generate zero network traffic. Explicit pairing/restart wakes us.
                await asyncio.Event().wait()
            except websockets.exceptions.ConnectionClosed as exc:
                self.ws=None
                if getattr(exc,"code",None)==4404:
                    try:
                        bundle=__import__("mcptoai_agent.auth",fromlist=["_auth_bundle"])._auth_bundle()
                        device_id=str(bundle.get("device_id") or "")
                        if device_id: mark_device_removed(device_id)
                    except Exception:
                        logger.exception("Could not persist removed-device state")
                    logger.error("Relay confirmed this device was removed; reconnect loop stopped until explicit re-pair")
                    await asyncio.Event().wait()
                logger.warning("Relay disconnected: %s",exc)
                await asyncio.sleep(delay+random.random()); delay=min(delay*2,self.cfg.reconnect_max_seconds)
            except Exception as exc:
                self.ws=None; logger.warning("Relay disconnected: %s",exc)
                await asyncio.sleep(delay+random.random()); delay=min(delay*2,self.cfg.reconnect_max_seconds)
    async def _send(self,event):
        data=json.dumps(event,ensure_ascii=False,default=str)
        if self.ws:
            try:
                await self.ws.send(data); return
            except Exception as exc:
                logger.warning("Relay gönderimi başarısız, olay bekletiliyor: %s",exc)
        # Yalnızca sohbet olayları bekletilir; hello/mcp_state bağlantıda yeniden üretilir.
        if event.get("type")=="event": self._outbox.append(data)
    # --- uzun süreli görevler: web'e canlı durum ----------------------------------
    @staticmethod
    def _job_signature(view):
        return (view.get("status"),view.get("exit_code"),json.dumps(view.get("progress") or {},sort_keys=True),(view.get("output_tail") or "")[-500:])
    def _job_views(self):
        from .jobs import default_manager
        mgr=default_manager(); return [mgr.view(j["id"],20) for j in mgr.list()]
    async def _send_jobs_snapshot(self):
        try:
            views=await asyncio.to_thread(self._job_views)
            self._job_sig={v["id"]:self._job_signature(v) for v in views}
            await self._send({"type":"jobs_snapshot","jobs":views})
        except Exception:
            logger.exception("Görev anlık görüntüsü gönderilemedi")
    async def _watch_jobs(self):
        """Her 5 sn'de görevleri tarar; yalnızca değişenleri web'e gönderir."""
        while True:
            await asyncio.sleep(5)
            if not self.ws: continue
            try:
                # Geçmiş tercihi Desktop'tan değiştirildiyse açık web oturumlarına bildir; aksi halde
                # açık bir sekme sayfa yenilenene kadar eski tercihle kaydetmeye devam ederdi.
                if await asyncio.to_thread(selected_history_provider_name,self.cfg)!=self._history_sent:
                    await self._send_history_status()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Geçmiş tercihi bildirilemedi")
            try:
                views=await asyncio.to_thread(self._job_views)
                ids={v["id"] for v in views}
                if set(self._job_sig)-ids:
                    await self._send_jobs_snapshot(); continue  # silinen görev: tam liste
                for v in views:
                    sig=self._job_signature(v)
                    if self._job_sig.get(v["id"])!=sig:
                        self._job_sig[v["id"]]=sig; await self._send({"type":"job_update","job":v})
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Görev izleyicisi hatası")
    async def _stop_job(self,msg):
        """Web'deki Durdur düğmesi (kullanıcının doğrudan eylemi)."""
        from .jobs import JOB_ID_RE, JobError, default_manager
        job_id=str(msg.get("job_id") or "")
        if not JOB_ID_RE.match(job_id): return
        try:
            view=await asyncio.to_thread(default_manager().stop,job_id)
            self._job_sig[job_id]=self._job_signature(view)
            await self._send({"type":"job_update","job":view})
        except JobError as exc:
            logger.warning("Görev durdurulamadı: %s",exc)
    async def _flush_outbox(self):
        """Bekleyen olayları sırayla gönderir. Sunucu 10 sn'de 100 mesaj kabul ettiği için
        saniyede 8 mesajla sınırlanır; canlı trafiğe pay kalır."""
        sent=0
        while self._outbox and self.ws:
            data=self._outbox.popleft()
            try: await self.ws.send(data)
            except Exception:
                self._outbox.appendleft(data); raise
            sent+=1; await asyncio.sleep(0.125)
        if sent: logger.info("Bağlantı kopukken biriken %d olay gönderildi",sent)
    async def _send_history_status(self):
        provider = selected_history_provider_name(self.cfg)
        self._history_sent = provider
        await self._send({
            "type": "history_status",
            "provider": provider,
            "options": [
                {"id": "mcptoai", "available": True},
                {"id": "local", "available": True},
                {"id": "remote", "available": False, "coming_soon": True, "enterprise": True},
            ],
        })

    async def _handle_history_request(self, msg):
        request_id = str(msg.get("request_id") or "")
        request = msg.get("request")
        if not request_id or len(request_id) > 80 or not isinstance(request, dict):
            return
        result = await handle_cloud_chat_request(self.cfg, request)
        await self._send({"type": "history_response", "request_id": request_id, "result": result})

    async def _handle(self,msg):
        typ=msg.get("type")
        if typ=="message": asyncio.create_task(self._run_message(msg)); return
        if typ=="job_stop": asyncio.create_task(self._stop_job(msg)); return
        if typ=="providers_request": asyncio.create_task(self._send_providers()); return
        if typ=="models_request": asyncio.create_task(self._send_models(msg.get("provider"))); return
        if typ=="media_settings_request": asyncio.create_task(self._send_media_settings()); return
        if typ=="history_status_request": asyncio.create_task(self._send_history_status()); return
        if typ=="history_request": asyncio.create_task(self._handle_history_request(msg)); return
        if typ=="media_settings_update": asyncio.create_task(self._update_media_settings(msg)); return
        if typ=="mcp_state_request":
            asyncio.create_task(self._send_mcp_state(force=msg.get("refresh") is True)); return
        if typ=="mcp_config": asyncio.create_task(self._update_mcp_config(msg)); return
        if typ=="mcp_server_add": asyncio.create_task(self._add_mcp_server(msg)); return
        if typ=="mcp_server_update": asyncio.create_task(self._update_mcp_server(msg)); return
        if typ=="mcp_server_remove": asyncio.create_task(self._remove_mcp_server(msg)); return
        if typ=="approval":
            aid=msg.get("approval_id"); entry=self.pending_approvals.get(aid)
            if entry:
                fut, expected_sid = entry
                if msg.get("session_id") != expected_sid:
                    logger.warning("Rejected approval with mismatched session: %s", aid)
                    return
                if not fut.done(): fut.set_result(msg.get("approve") is True)
    async def _stdio_session(self, server):
        sid=str(server.get("id") or "")
        if not sid: raise ValueError("MCP server id is missing")
        fingerprint=(str(server.get("command") or ""),tuple(server.get("args") or []),tuple(sorted((server.get("env") or {}).items())))
        existing=self._stdio_runtimes.get(sid)
        if existing and existing.get("fingerprint")==fingerprint:
            return existing["session"]
        if existing:
            await self._close_stdio(sid)
        params=StdioServerParameters(command=server["command"],args=server.get("args") or [],env={**os.environ,**(server.get("env") or {})})
        transport_cm=stdio_client(params)
        streams=await transport_cm.__aenter__()
        session_cm=ClientSession(*streams)
        try:
            session=await session_cm.__aenter__()
            await session.initialize()
        except Exception:
            try: await session_cm.__aexit__(*__import__('sys').exc_info())
            except Exception: pass
            try: await transport_cm.__aexit__(*__import__('sys').exc_info())
            except Exception: pass
            raise
        self._stdio_runtimes[sid]={"fingerprint":fingerprint,"transport_cm":transport_cm,"session_cm":session_cm,"session":session}
        return session

    async def _close_stdio(self, server_id=None):
        ids=[server_id] if server_id else list(self._stdio_runtimes)
        for sid in ids:
            runtime=self._stdio_runtimes.pop(sid,None)
            if not runtime: continue
            try: await runtime["session_cm"].__aexit__(None,None,None)
            except Exception as exc: logger.debug("MCP stdio session close failed for %s: %s",sid,exc)
            try: await runtime["transport_cm"].__aexit__(None,None,None)
            except Exception as exc: logger.debug("MCP stdio transport close failed for %s: %s",sid,exc)

    async def _discover_mcp_tools(self, allow_oauth_prompt=False):
        found={}
        active_ids={s.get("id") for s in custom_servers() if s.get("enabled",True)}
        for sid in list(self._stdio_runtimes):
            if sid not in active_ids:
                await self._close_stdio(sid)
        for public,(srv,_) in list(self._remote_tool_map.items()):
            if srv.get("id") not in active_ids:
                self._remote_tool_map.pop(public,None); self._remote_tool_specs.pop(public,None)
        for server in custom_servers():
            if not server.get("enabled",True): continue
            for public,(srv,_) in list(self._remote_tool_map.items()):
                if srv.get("id")==server.get("id"):
                    self._remote_tool_map.pop(public,None); self._remote_tool_specs.pop(public,None)
            try:
                if server.get("transport")=="streamable-http":
                    headers=server.get("headers") or {}
                    oauth_state={"value":None}
                    async def redirect_handler(url):
                        if not allow_oauth_prompt:
                            raise RuntimeError("MCP authorization expired; reconnect this MCP server from the MCP settings.")
                        oauth_state["value"]=(parse_qs(urlparse(url).query).get("state") or [None])[0]
                        await self._send({"type":"mcp_oauth_required","server_id":server["id"],"server_name":server.get("name"),"authorization_url":url})
                    async def callback_handler():
                        state=oauth_state.get("value")
                        if not state: raise RuntimeError("OAuth state missing")
                        endpoint=OAUTH_CALLBACK_URL
                        deadline=asyncio.get_running_loop().time()+120
                        async with httpx.AsyncClient(timeout=10) as client:
                            register=await client.post(endpoint,json={"state":state})
                            register.raise_for_status()
                            while asyncio.get_running_loop().time()<deadline:
                                r=await client.get(endpoint,params={"state":state})
                                if r.status_code==200:
                                    data=r.json()
                                    if data.get("error"): raise RuntimeError(data["error"])
                                    if data.get("code"): return data["code"],data.get("state")
                                await asyncio.sleep(1)
                        raise TimeoutError("OAuth callback timed out")
                    metadata=oauth_metadata_for(server)
                    storage=await prepare_oauth_storage(server)
                    auth=oauth_provider_for(server,metadata,storage,redirect_handler,callback_handler)
                    async with streamablehttp_client(server["url"],headers=headers,timeout=20,auth=auth) as streams:
                        async with ClientSession(streams[0],streams[1]) as session:
                            await session.initialize()
                            result=await session.list_tools()
                            found[server["id"]]=[t.name for t in result.tools]
                            self._cache_remote_tools(server,result.tools)
                else:
                    session=await self._stdio_session(server)
                    result=await session.list_tools()
                    found[server["id"]]=[t.name for t in result.tools]
                    self._cache_remote_tools(server,result.tools)
            except Exception as exc:
                logger.warning("MCP discovery failed for %s: %s",server.get("name"),exc)
                found[server["id"]]=[]
        try:
            from pathlib import Path
            snapshot=config_dir()/'mcp-discovery.json'
            snapshot.parent.mkdir(parents=True,exist_ok=True)
            tmp=snapshot.with_suffix('.tmp')
            tmp.write_text(json.dumps({"version":1,"servers":found},indent=2))
            tmp.replace(snapshot)
        except Exception as exc:
            logger.warning("Could not write MCP discovery snapshot: %s",exc)
        return found

    @staticmethod
    def _slug(value):
        import re
        return re.sub(r"[^a-z0-9]+","_",str(value).casefold()).strip("_") or "mcp"

    def _cache_remote_tools(self,server,tools):
        prefix=self._slug(server.get("name") or server.get("id"))
        for t in tools:
            public=f"mcp__{prefix}__{t.name}"
            desc=f"[MCP server: {server.get('name')}] {t.description or ''}".strip()
            self._remote_tool_specs[public]=ToolSpec(public,desc,t.inputSchema)
            self._remote_tool_map[public]=(server,t.name)

    def _server_aliases(self):
        aliases={}
        for server in custom_servers():
            if not server.get("enabled",True): continue
            name=str(server.get("name") or "").strip()
            vals={name.casefold()}
            url=str(server.get("url") or "")
            try:
                host=urlparse(url).hostname or ""
                vals.add(host.casefold())
                if host.startswith("www."): vals.add(host[4:].casefold())
            except Exception: pass
            aliases[name or server.get("id")]={"id":server.get("id"),"aliases":sorted(v for v in vals if v)}
        return aliases

    async def _call_remote_tool(self,public_name,args):
        entry=self._remote_tool_map.get(public_name)
        if not entry: return "Remote MCP tool is no longer available.",True
        server,remote_name=entry
        try:
            if server.get("transport")=="streamable-http":
                metadata=oauth_metadata_for(server)
                async def no_redirect(url): raise RuntimeError("MCP authorization expired; reconnect this MCP server.")
                async def no_callback(): raise RuntimeError("MCP authorization required.")
                storage=await prepare_oauth_storage(server)
                auth=oauth_provider_for(server,metadata,storage,no_redirect,no_callback)
                async with streamablehttp_client(server["url"],headers=server.get("headers") or {},timeout=30,auth=auth) as streams:
                    async with ClientSession(streams[0],streams[1]) as session:
                        await session.initialize()
                        result=await session.call_tool(remote_name,args or {})
            else:
                session=await self._stdio_session(server)
                try:
                    result=await session.call_tool(remote_name,args or {})
                except Exception:
                    # If a child MCP process died, discard it so the next call can restart cleanly.
                    await self._close_stdio(server.get("id"))
                    raise
            content="\n".join(getattr(c,"text",str(c)) for c in result.content) or "(empty result)"
            return content,bool(result.isError)
        except Exception as exc:
            logger.warning("Remote MCP tool failed %s: %s",public_name,exc)
            return f"{type(exc).__name__}: {exc}",True

    def _refresh_session_remote_tools(self):
        """Refresh MCP tool snapshots on already-open chat sessions.

        Remote MCP discovery is asynchronous. A chat session may therefore be
        created before discovery finishes. Keep existing conversation history,
        but replace the session's remote tool/policy snapshot once discovery
        learns (or changes) the available tools.
        """
        base_rules=load_rules()
        remote_rules={
            name: Decision((self._remote_tool_map[name][0].get("tools") or {}).get(self._remote_tool_map[name][1], "confirm"))
            for name in self._remote_tool_specs
            if name in self._remote_tool_map
        }
        specs=list(self._remote_tool_specs.values())
        aliases=self._server_aliases()
        for session in self.sessions.values():
            session.remote_tools=list(specs)
            session.policy=ToolPolicy(rules={**base_rules, **remote_rules})
            session.server_aliases=aliases

    async def _send_mcp_state(self, force=False):
        # Render configured servers immediately. Discovery is cached so opening
        # pages or reconnecting the relay does not repeatedly handshake every MCP.
        await self._send({"type":"mcp_state",**mcp_state(self._mcp_discovered)})
        now=asyncio.get_running_loop().time()
        if not force and self._mcp_discovered is not None and now-self._mcp_discovered_at < 300:
            return
        if self._mcp_discovery_task is None or self._mcp_discovery_task.done():
            self._mcp_discovery_task=asyncio.create_task(self._discover_mcp_tools(allow_oauth_prompt=False))
        try:
            discovered=await self._mcp_discovery_task
            self._mcp_discovered=discovered; self._mcp_discovered_at=asyncio.get_running_loop().time()
            self._refresh_session_remote_tools()
            await self._send({"type":"mcp_state",**mcp_state(discovered)})
        except Exception as exc:
            logger.warning("MCP discovery task failed: %s",exc)
        finally:
            if self._mcp_discovery_task and self._mcp_discovery_task.done():
                self._mcp_discovery_task=None

    async def _add_mcp_server(self,msg):
        try:
            # SECURITY: remote/web control plane may not create local stdio
            # processes. Stdio MCPs must be installed from the local Desktop app.
            if (msg.get("transport") or "stdio") == "stdio":
                raise PermissionError("Local stdio MCP servers must be added on this device.")
            # Kasa yazımı kilit bekleyebilir; olay döngüsünü bloklamamak için thread'de çalışır.
            await asyncio.to_thread(add_server,msg.get("name") or "",msg.get("command") or "",msg.get("args") or [],msg.get("env") or {},msg.get("transport") or "streamable-http",msg.get("url") or "",msg.get("headers") or {})
            self.sessions.clear(); await self._send_mcp_state()
        except Exception as exc:
            await self._send({"type":"mcp_state","error":f"{type(exc).__name__}: {exc}",**mcp_state()})

    async def _update_mcp_server(self,msg):
        server_id=msg.get("server_id") or ""
        patch=dict(msg)
        server=next((x for x in custom_servers() if x.get("id")==server_id),None)
        # SECURITY: a remote client may disable a local stdio server, but it may
        # not enable one or change its executable configuration.
        if server and server.get("transport")=="stdio":
            if patch.get("enabled") is True and not server.get("enabled",True):
                patch.pop("enabled",None)
            for key in ("command","args","env","transport"):
                patch.pop(key,None)
        await asyncio.to_thread(update_server,server_id,patch)
        await self._close_stdio(server_id)
        self.sessions.clear(); await self._send_mcp_state()

    async def _remove_mcp_server(self,msg):
        server_id=msg.get("server_id") or ""
        server=next((x for x in custom_servers() if x.get("id")==server_id),None)
        if server and server.get("transport")=="stdio":
            await self._send({"type":"mcp_state","error":"PermissionError: Local stdio MCP servers must be removed on this device.",**mcp_state()}); return
        await asyncio.to_thread(remove_server,server_id)
        await self._close_stdio(server_id)
        self.sessions.clear(); await self._send_mcp_state()

    async def _update_mcp_config(self,msg):
        server_id=msg.get("server_id")
        try:
            requested=msg.get("tools") or {}
            # SECURITY: web/relay may make policy stricter, never weaker.
            # Only the local Desktop app may grant AUTO.
            if server_id=="local-device":
                current=load_rules()
                safe={}
                for name,value in requested.items():
                    old=current.get(name)
                    if value=="auto" and (old is None or old.value!="auto"):
                        continue
                    if value in ("deny","confirm","auto"):
                        safe[name]=value
                save_rules(safe)
            else:
                server=next((x for x in custom_servers() if x.get("id")==server_id),None)
                current=(server or {}).get("tools") or {}
                safe={}
                for name,value in requested.items():
                    old=current.get(name,"confirm")
                    if value=="auto" and old!="auto":
                        continue
                    if value in ("deny","confirm","auto"):
                        safe[name]=value
                await asyncio.to_thread(update_server,server_id,{"tools":safe})
            self.sessions.clear()
            await self._send_mcp_state()
        except Exception as exc:
            await self._send({"type":"mcp_state","error":f"{type(exc).__name__}: {exc}",**mcp_state()})

    async def _send_media_settings(self):
        # The single versioned vault is already the credential authority. Reading
        # one provider flag does not enumerate legacy Keychain records.
        from .secret_store import get_secret, api_key_name
        configured = bool(get_secret(api_key_name("replicate")))
        await self._send({"type":"media_settings","replicate":{"configured":configured,"image_model":self.cfg.user_settings.get("replicate_image_model") or "black-forest-labs/flux-1.1-pro"}})

    async def _update_media_settings(self,msg):
        import re
        model=str(msg.get("replicate_image_model") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+",model) or len(model)>160:
            await self._send({"type":"media_settings","error":"Invalid Replicate model slug"}); return
        from .config import save_user_settings
        current=dict(self.cfg.user_settings or {}); current["replicate_image_model"]=model; save_user_settings(current)
        self.cfg.user_settings=current
        await self._send_media_settings()

    async def _send_providers(self):
        from .provider_registry import registry
        items=[]
        for pid,info in registry(self.cfg.user_settings.get("custom_providers") or {}).items():
            if info.get("chat") is False: continue
            # Provider listing is metadata-only. Never enumerate Keychain here;
            # the selected provider credential is checked lazily on use.
            items.append({"id":pid,"name":info.get("name",pid),"current":pid==self.cfg.provider})
        await self._send({"type":"providers","providers":items,"current_provider":self.cfg.provider})

    def _chat_provider_cfg(self, provider_id=None):
        from dataclasses import replace
        from .provider_registry import registry
        from .secret_store import get_secret, api_key_name
        pid=str(provider_id or self.cfg.provider).strip()
        info=registry(self.cfg.user_settings.get("custom_providers") or {}).get(pid)
        if not info or info.get("chat") is False:
            raise ValueError("Unsupported chat provider")
        if info.get("key",True) and not get_secret(api_key_name(pid)):
            raise RuntimeError("Provider API key is not configured")
        return replace(self.cfg,provider=pid,openai_base_url=info.get("base_url") or (self.cfg.openai_base_url if pid==self.cfg.provider else None))

    async def _send_models(self, provider_id=None):
        try:
            cfg=self._chat_provider_cfg(provider_id); provider=make_provider(cfg)
            models=await provider.list_models()
            await self._send({"type":"models","provider":cfg.provider,"current_model":cfg.model if cfg.provider==self.cfg.provider else "","models":models})
        except Exception as exc:
            logger.exception("Model discovery failed")
            await self._send({"type":"models","provider":str(provider_id or self.cfg.provider),"current_model":"","models":[],"error":f"{type(exc).__name__}: {exc}"})

    async def _run_message(self,msg):
        sid=str(msg.get("session_id") or str(uuid.uuid4()))
        if len(sid)>128: return
        text=str(msg.get("message") or "").strip()
        if not text or len(text.encode("utf-8"))>256*1024: return
        requested_provider=str(msg.get("provider") or self.cfg.provider).strip()
        try: provider_cfg=self._chat_provider_cfg(requested_provider)
        except Exception as exc:
            await self._send({"type":"event","session_id":sid,"event":{"type":"error","message":f"{type(exc).__name__}: {exc}"}}); return
        requested_model=str(msg.get("model") or provider_cfg.model).strip()
        if not requested_model or len(requested_model)>160 or any(ord(c)<32 for c in requested_model):
            requested_model=provider_cfg.model
        images=msg.get("images") or []; context=msg.get("context") or []; preferred=msg.get("preferred_mcp_server_ids") or []
        if not isinstance(images,list) or len(images)>8 or not isinstance(context,list) or len(context)>100 or not isinstance(preferred,list) or len(preferred)>32: return
        logger.info("Selected provider/model for session %s: %s/%s", sid, requested_provider, requested_model)
        # Bound long-lived agent memory: expire idle sessions and cap the cache.
        now=time.monotonic()
        for key,last in list(self._session_last_used.items()):
            if now-last>3600:
                self.sessions.pop(key,None); self._session_last_used.pop(key,None)
        # Anahtar parmak izi: Desktop anahtarı değiştirirse uzun ömürlü süreç eski anahtarlı oturumu kullanmaz.
        from .secret_store import provider_key_fingerprint
        session_key=f"{sid}:{requested_provider}:{requested_model}:{provider_key_fingerprint(requested_provider)}"
        session=self.sessions.get(session_key)
        if session is None and len(self.sessions)>=50:
            oldest=min(self._session_last_used,key=self._session_last_used.get)
            self.sessions.pop(oldest,None); self._session_last_used.pop(oldest,None)
        if session is None:
            provider=make_provider(provider_cfg)
            provider.model=requested_model
            session=self.sessions[session_key]=AgentSession(provider_cfg,provider,build_server(provider_cfg),policy=ToolPolicy(rules={**load_rules(),**{name:Decision((self._remote_tool_map[name][0].get("tools") or {}).get(self._remote_tool_map[name][1],"confirm")) for name in self._remote_tool_specs}}),remote_tools=list(self._remote_tool_specs.values()),remote_caller=self._call_remote_tool,server_aliases=self._server_aliases())
        self._session_last_used[session_key]=now
        # Images are data URLs; keep decoded payload bounded even if transport limits change.
        total_image_chars=0
        for image in images:
            if not isinstance(image,dict) or not isinstance(image.get("data_url"),str): return
            data_url=image["data_url"]
            if not data_url.startswith("data:image/") or ";base64," not in data_url: return
            total_image_chars += len(data_url)
        if total_image_chars>384*1024: return
        async def emit(event): await self._send({"type":"event","session_id":sid,"event":event})
        async def approver(tool,args):
            aid=str(uuid.uuid4()); fut=asyncio.get_running_loop().create_future(); self.pending_approvals[aid]=(fut,sid)
            await self._send({"type":"event","session_id":sid,"event":{"type":"approval_required","approval_id":aid,"tool":tool,"arguments":args}})
            try: return await asyncio.wait_for(fut,timeout=self.cfg.approval_timeout_seconds)
            except asyncio.TimeoutError: return False
            finally: self.pending_approvals.pop(aid,None)
        capability=str(msg.get("capability") or "").strip().casefold()
        try:
            if capability: await session.run_capability(capability,text,approver,emit)
            else: await session.run(text,approver,emit,images=images,language=msg.get("language"),context=context,preferred_mcp_server_ids=preferred)
        except Exception as exc:
            logger.exception("Agent session failed"); await emit({"type":"error","message":f"{type(exc).__name__}: {exc}"})

async def run_relay_client(cfg:Settings): await RelayClient(cfg).run_forever()
