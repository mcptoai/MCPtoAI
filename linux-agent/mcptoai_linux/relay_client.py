"""Outbound WebSocket client for MCPtoAI relay. No inbound port is opened."""
from __future__ import annotations
from .paths import config_dir
import asyncio, collections, json, logging, random, uuid, os, time
from .event_journal import EventJournal
from .answer_sync import answer_sync_loop
from urllib.parse import urlparse, parse_qs
import websockets
import os
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from .mcp_streamable_compat import streamablehttp_client, _tool_result_is_error
from .stdio_runtime import StdioRuntime as _StdioRuntime
STDIO_START_TIMEOUT = 120
from .mcp_oauth import OAUTH_CALLBACK_URL, oauth_metadata_for, oauth_provider_for, prepare_oauth_storage
import httpx
from .agent import AgentSession
from .auth import DeviceRemovedError, get_access_token, mark_device_removed, register_device, device_ws_proof
from .config import Settings
from .providers import make_provider, ToolSpec
from .tools import build_server
from .mcp_config import load_rules, save_rules, state as mcp_state, custom_servers, add_server, update_server, remove_server
from .reliability import MessageReceiptStore
logger=logging.getLogger("mcptoai.relay_client")

async def handle_cloud_chat_request(cfg: Settings, req: dict) -> dict:
    action=req.get("action")
    if action not in {"cloud_chats_list","cloud_chat_get","cloud_chat_create","cloud_chat_add_message","cloud_chat_delete","cloud_chat_update"}:
        return {"ok":False,"error":"unsupported_action"}
    token=await get_access_token(cfg)
    base=cfg.server_url.rstrip("/")+"/api/chats/"
    if action=="cloud_chats_list" and req.get("archived") is True:
        base+="?archived=1"
    method="GET"; body=None
    if action in {"cloud_chat_get","cloud_chat_add_message","cloud_chat_delete","cloud_chat_update"}:
        cid=str(req.get("session_id") or "")
        try:
            uuid.UUID(cid)
        except (ValueError,TypeError):
            raise ValueError("invalid chat id")
        base+=cid+("/messages/" if action=="cloud_chat_add_message" else "/")
    if action=="cloud_chat_delete":
        method="DELETE"
    elif action=="cloud_chat_update":
        method="PATCH"; body={k:req[k] for k in ("title","is_pinned","is_archived") if k in req}
    elif action=="cloud_chat_create":
        method="POST"; body={"title":str(req.get("title") or "New chat")[:160],"provider":str(req.get("provider") or "")[:80],"model":str(req.get("model") or "")[:120]}
    elif action=="cloud_chat_add_message":
        method="POST"; body={"role":str(req.get("role") or ""),"content":str(req.get("content") or ""),"model":str(req.get("model") or "")[:120],"tool_name":str(req.get("tool_name") or "")[:160],"tool_data":req.get("tool_data")}
    async with httpx.AsyncClient(timeout=15) as http:
        r=await http.request(method,base,headers={"Authorization":f"Bearer {token}"},json=body if method in {"POST","PATCH"} else None)
        r.raise_for_status()
        return {"ok":True,"data":(r.json() if r.content else None)}

from mcptoai_core.reconnect import reconnect_delay as _reconnect_delay

from mcptoai_core.replay import parse_replay_request as _parse_replay_request
from mcptoai_core.replay import replay_completion as _replay_completion

from mcptoai_core.events import event_envelope as _event_envelope

from mcptoai_core.replay_transport import send_replay_events as _send_replay_events

from mcptoai_core.session_state import prune_session_state as _prune_session_state

from mcptoai_core.relay_transport import (receive_messages as _receive_messages,
    relay_url as _relay_url, open_relay as _open_relay)

from mcptoai_core.session_state import (expire_idle_sessions as _expire_idle_sessions,
    evict_session_if_full as _evict_session_if_full,
    begin_turn as _begin_turn, finish_turn as _finish_turn, turn_is_busy as _turn_is_busy)

class RelayClient:
    def __init__(self,cfg:Settings,receipt_store:MessageReceiptStore|None=None):
        self.cfg=cfg; self.sessions={}; self._session_last_used={}; self.pending_approvals={}; self.ws=None; self._mcp_discovery_task=None; self._remote_tool_specs={}; self._remote_tool_map={}; self._mcp_discovered=None; self._mcp_discovered_at=0.0; self._ipc_server=None; self._stdio_runtimes={}
        # Bağlantı yokken üretilen sohbet olayları (ilerleme, onay isteği, son yanıt) burada
        # bekler ve yeniden bağlanınca sırayla gönderilir; en eskiler taşarsa düşer.
        self._outbox=collections.deque(maxlen=500)
        # Görev izleyicisi: web'e gönderilen son durumların imzası (yalnızca değişenler gider).
        self._job_sig={}; self._job_watch_task=None
        # Reconnect-safe turn protocol. Sequence numbers are scoped to this agent
        # process (event_epoch). A bounded per-session journal lets the web ask for
        # events it missed after a socket reconnect without re-running tools.
        self._event_epoch=uuid.uuid4().hex
        self._event_seq={}
        self._event_journal={}
        self._turn_state={}
        self._turn_tasks={}
        self._cancel_requested=set()
        self._turn_events={}
        self._replay_tasks={}
        self._durable_events=EventJournal()
        self._answer_sync_task=None
        for restored_sid, entries in self._durable_events.data.items():
            if not isinstance(entries,list): continue
            valid=[e for e in entries if isinstance(e,dict) and isinstance(e.get('seq'),int) and isinstance(e.get('event'),dict)]
            if not valid: continue
            resolved={e['event'].get('approval_id') for e in valid if e['event'].get('type')=='approval_resolved'}
            valid=[{**e,'event_epoch':self._event_epoch,'event':({'type':'approval_interrupted','approval_id':e['event'].get('approval_id'),'tool':e['event'].get('tool')} if e['event'].get('type')=='approval_interrupted' and e['event'].get('approval_id') not in resolved else e['event'])} for e in valid]
            self._event_journal[restored_sid]=collections.deque(valid[-500:],maxlen=500)
            self._event_seq[restored_sid]=max(e['seq'] for e in valid)
            turns=self._turn_events.setdefault(restored_sid,collections.OrderedDict())
            for entry in valid:
                tid=entry.get('turn_id')
                if tid: turns.setdefault(tid,collections.deque(maxlen=500)).append(entry)
            while len(turns)>2: turns.popitem(last=False)
            if turns: self._turn_state[restored_sid]={'id':next(reversed(turns)),'active':False}
        self._receipts=receipt_store or MessageReceiptStore()
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
                relay_url=_relay_url(self.cfg.relay_url, self.cfg.server_url, device_id)
                headers={"Authorization":f"Bearer {token}",**device_ws_proof(device_id)}
                async with _open_relay(websockets.connect, relay_url, headers) as ws:
                    self.ws=ws; delay=1
                    await self._send_hello()
                    logger.info("Relay connected: %s",relay_url)
                    await self._flush_outbox()
                    if self._answer_sync_task is None or self._answer_sync_task.done():
                        self._answer_sync_task=asyncio.create_task(answer_sync_loop(self.cfg,self._durable_events))
                    await self._send_jobs_snapshot()
                    if self._job_watch_task is None or self._job_watch_task.done():
                        self._job_watch_task=asyncio.create_task(self._watch_jobs())
                    asyncio.create_task(self._send_mcp_state())
                    await _receive_messages(ws, self._handle)
            except asyncio.CancelledError: raise
            except DeviceRemovedError as exc:
                self.ws=None
                logger.error("Device was removed server-side; reconnect loop stopped until explicit re-pair: %s",exc)
                await asyncio.Event().wait()
            except websockets.exceptions.ConnectionClosed as exc:
                self.ws=None
                if getattr(exc,"code",None) == 4404:
                    try:
                        from .auth import _auth_bundle
                        device_id=str(_auth_bundle().get("device_id") or "")
                        if device_id: mark_device_removed(device_id)
                    except Exception:
                        logger.exception("Could not persist removed-device state")
                    logger.error("Relay confirmed this device was removed; reconnect loop stopped until explicit re-pair")
                    await asyncio.Event().wait()
                logger.warning("Relay disconnected: %s",exc)
                sleep_for,delay=_reconnect_delay(delay,self.cfg.reconnect_max_seconds,random.random())
                await asyncio.sleep(sleep_for)
            except Exception as exc:
                self.ws=None; logger.warning("Relay disconnected: %s",exc)
                sleep_for,delay=_reconnect_delay(delay,self.cfg.reconnect_max_seconds,random.random())
                await asyncio.sleep(sleep_for)
    async def _send_hello(self):
        await self._send({"type":"hello","role":"device","protocol":1,"capabilities":["event_replay_v1","message_dedupe_v1","turn_replay_v1","replay_complete_v1","turn_cancel_v1","activity_settings_v1","activity_metadata_v1","activity_list_v1"],"event_epoch":self._event_epoch})
    async def _send_event(self,session_id,event,turn_id=None):
        sid=str(session_id or "")
        seq=self._event_seq.get(sid,0)+1; self._event_seq[sid]=seq
        envelope=_event_envelope(sid,seq,self._event_epoch,event,time.time(),turn_id)
        if turn_id is not None:
            turns=self._turn_events.setdefault(sid,collections.OrderedDict())
            turns.setdefault(turn_id,collections.deque(maxlen=500)).append(envelope)
            while len(turns)>2: turns.popitem(last=False)
            turn=self._turn_state.get(sid)
            if turn and turn['id']==turn_id and event.get('type')=='done': turn['active']=False
        self._event_journal.setdefault(sid,collections.deque(maxlen=500)).append(envelope)
        self._durable_events.append(sid,envelope)
        _prune_session_state(self._event_journal,self._event_seq,self._turn_state,self._turn_events)
        if event.get('type') == 'done' and turn_id is not None:
            current_turn = self._turn_events.get(sid, {}).get(turn_id, ())
            if any(e.get('event', {}).get('type') == 'text' for e in current_turn):
                old = self._event_journal.get(sid)
                if old is not None:
                    self._event_journal[sid] = collections.deque(
                        (e for e in old if not (
                            e.get('event', {}).get('type') == 'error'
                            and e.get('turn_id') != turn_id)), maxlen=500)
                for tid, events in self._turn_events.get(sid, {}).items():
                    if tid != turn_id:
                        self._turn_events[sid][tid] = collections.deque(
                            (e for e in events if e.get('event', {}).get('type') != 'error'), maxlen=500)
        await self._send(envelope)

    async def _handle_event_replay_request(self,msg):
        parsed=_parse_replay_request(msg, reject_turn_cursor=True)
        if parsed is None: return
        sid,mode,after=parsed
        if not any(sid in store for store in (self._event_journal, self._turn_events, self._turn_state)):
            logger.info("Replay requested for unknown local session; returning empty completion")
            if self.ws is not None:
                await self._send({"type":"replay_complete","session_id":sid,"mode":mode,
                                  "turn_id":None,"through_seq":0,"event_epoch":self._event_epoch})
            return
        current=asyncio.current_task(); prior=self._replay_tasks.get(sid)
        if prior is not None and prior is not current and not prior.done(): return
        self._replay_tasks[sid]=current
        turn=self._turn_state.get(sid)
        turn_id=(turn['id'] if turn and (mode=='last_turn' or turn['active']) else None) if mode!='after_seq' else None
        cursor=after if mode=='after_seq' else 0
        socket=self.ws
        try:
            cursor, replay_sent, completed = await _send_replay_events(
                socket, lambda: self.ws is socket, mode, cursor, turn_id,
                self._event_journal, self._turn_events, sid)
            if not completed: return
            if self.ws is socket and socket is not None:
                try: await socket.send(json.dumps(_replay_completion(sid,mode,turn_id,cursor,self._event_epoch)))
                except Exception: return
        finally:
            if self._replay_tasks.get(sid) is current: self._replay_tasks.pop(sid,None)

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
    async def _handle_activity_list(self, msg):
        """Read-only bounded local metadata; no server-side persistence."""
        from .activity_store import ActivityStore
        request_id = msg.get('request_id')
        limit = msg.get('limit', 100)
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 80 or type(limit) is not int or not 1 <= limit <= 100:
            return
        def read_local():
            store = ActivityStore()
            try:
                return [{k: v for k, v in row.items() if k != 'sequence'} for row in store.list_events(limit=limit)]
            finally:
                store.close()
        try:
            items = await asyncio.to_thread(read_local)
            await self._send({'type': 'activity_list_response', 'request_id': request_id, 'items': items})
        except (ValueError, OSError):
            await self._send({'type': 'activity_list_response', 'request_id': request_id, 'items': [], 'error': 'unavailable'})

    async def _handle_activity_settings(self, msg):
        """Device-owned activity controls; only sanitized status/count returned to web."""
        from .config import save_user_settings
        from .activity_store import ActivityStore
        from .activity_recorder import recording_enabled
        request_id = msg.get('request_id')
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 80:
            return
        action = msg.get('action')
        response = {'type': 'activity_settings_response', 'request_id': request_id}
        try:
            if action == 'set_recording':
                if type(msg.get('enabled')) is not bool:
                    raise ValueError('Invalid recording setting')
                settings = dict(self.cfg.user_settings or {})
                settings['activity_recording_enabled'] = msg['enabled']
                await asyncio.to_thread(save_user_settings, settings)
                self.cfg.user_settings = settings
                for session in self.sessions.values():
                    recorder = getattr(session, '_activity', None)
                    if recorder is not None:
                        recorder.enabled = msg['enabled'] and recording_enabled()
            elif action != 'status':
                raise ValueError('Unsupported activity settings action')
            response['enabled'] = self.cfg.user_settings.get('activity_recording_enabled', True) is True and recording_enabled()
        except (ValueError, OSError) as exc:
            response['error'] = type(exc).__name__
        await self._send(response)

    async def _handle(self,msg):
        typ=msg.get("type")
        if typ=="hello": asyncio.create_task(self._send_hello()); return
        if typ=="message": asyncio.create_task(self._run_message(msg)); return
        if typ=="turn_cancel": asyncio.create_task(self._cancel_turn(msg)); return
        if typ=="activity_settings_request": asyncio.create_task(self._handle_activity_settings(msg)); return
        if typ=="activity_list_request": asyncio.create_task(self._handle_activity_list(msg)); return
        if typ=="event_replay_request": asyncio.create_task(self._handle_event_replay_request(msg)); return
        if typ=="job_stop": asyncio.create_task(self._stop_job(msg)); return
        if typ=="providers_request": asyncio.create_task(self._send_providers()); return
        if typ=="models_request": asyncio.create_task(self._send_models(msg.get("provider"))); return
        if typ=="media_settings_request": asyncio.create_task(self._send_media_settings()); return
        if typ=="media_settings_update": asyncio.create_task(self._update_media_settings(msg)); return
        if typ=="mcp_state_request":
            asyncio.create_task(self._send_mcp_state(force=msg.get("refresh") is True)); return
        if typ=="mcp_config": asyncio.create_task(self._update_mcp_config(msg)); return
        if typ=="mcp_server_add": asyncio.create_task(self._add_mcp_server(msg)); return
        if typ=="mcp_server_update": asyncio.create_task(self._update_mcp_server(msg)); return
        if typ=="mcp_server_remove": asyncio.create_task(self._remove_mcp_server(msg)); return
        if typ=="history_status_request":
            mode = "local" if self.cfg.user_settings.get("history_provider") == "local" else "mcptoai"
            asyncio.create_task(self._send({"type":"history_status","provider":mode,"options":["mcptoai","local"]})); return
        if typ=="history_request":
            asyncio.create_task(self._handle_history_request(msg)); return
        if typ=="approval":
            aid=msg.get("approval_id"); entry=self.pending_approvals.get(aid)
            if entry:
                fut, expected_sid = entry
                if msg.get("session_id") != expected_sid:
                    logger.warning("Rejected approval with mismatched session: %s", aid)
                    return
                if not fut.done(): fut.set_result(msg.get("approve") is True)
    async def _handle_history_request(self, msg):
        request_id=str(msg.get("request_id") or "")
        req=msg.get("request") if isinstance(msg.get("request"),dict) else {}
        if self.cfg.user_settings.get("history_provider") != "local":
            result={"ok":False,"error":"Device-only history is not enabled."}
        else:
            from .local_history import LocalHistoryStore
            result=await asyncio.to_thread(LocalHistoryStore().handle,req)
        await self._send({"type":"history_response","request_id":request_id,"result":result})

    async def _stdio_session(self, server):
        sid=str(server.get("id") or "")
        if not sid: raise ValueError("MCP server id is missing")
        fingerprint=(str(server.get("command") or ""),tuple(server.get("args") or []),tuple(sorted((server.get("env") or {}).items())))
        # Aynı sunucu için eşzamanlı çağrılar ikinci bir alt süreç başlatmasın.
        locks=self.__dict__.setdefault("_stdio_locks",{})
        async with locks.setdefault(sid,asyncio.Lock()):
            existing=self._stdio_runtimes.get(sid)
            if existing and existing.fingerprint==fingerprint and existing.alive:
                return existing.session
            if existing:
                await self._close_stdio(sid)
            params=StdioServerParameters(command=server["command"],args=server.get("args") or [],env={**os.environ,**(server.get("env") or {})})
            runtime=_StdioRuntime(sid,params,fingerprint)
            session=await runtime.start(timeout=STDIO_START_TIMEOUT)
            self._stdio_runtimes[sid]=runtime
            return session

    async def _close_stdio(self, server_id=None):
        ids=[server_id] if server_id else list(self._stdio_runtimes)
        for sid in ids:
            runtime=self._stdio_runtimes.pop(sid,None)
            if runtime: await runtime.close()

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
            import os
            import tempfile
            # mkstemp creates 0600 regardless of the process umask. Never
            # reuse a potentially world-readable stale .tmp file.
            fd, temp_path = tempfile.mkstemp(prefix='.mcp-discovery-', suffix='.tmp', dir=snapshot.parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                    json.dump({"version": 1, "servers": found}, handle, indent=2)
                os.replace(temp_path, snapshot)
                os.chmod(snapshot, 0o600)
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
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
            self._remote_tool_specs[public]=ToolSpec(public,desc,t.input_schema)
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
            return content,_tool_result_is_error(result)
        except Exception as exc:
            logger.warning("Remote MCP tool failed %s: %s",public_name,exc)
            return f"{type(exc).__name__}: {exc}",True

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
            # Refresh already-open chat sessions with the newly discovered MCP tool
            # set. Sessions keep conversation history, but must not keep a stale
            # snapshot of remote tools/permissions/aliases after discovery.
            remote_tools=list(self._remote_tool_specs.values())
            aliases=self._server_aliases()
            remote_rules={name:__import__("mcptoai_linux.policy",fromlist=["Decision"]).Decision((self._remote_tool_map[name][0].get("tools") or {}).get(self._remote_tool_map[name][1],"confirm")) for name in self._remote_tool_specs}
            for session in self.sessions.values():
                session.remote_tools=remote_tools
                session.server_aliases=aliases
                session.policy=__import__("mcptoai_linux.policy",fromlist=["ToolPolicy"]).ToolPolicy(rules={**load_rules(),**remote_rules})
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
        providers=registry(self.cfg.user_settings.get("custom_providers") or {})
        if provider_id is None and not __import__('os').getenv('MCPTOAI_PROVIDER') and not self.cfg.user_settings.get('provider'):
            # Only auto-select when the default is unconfigured and exactly one
            # credential-backed chat provider is configured. No key values logged.
            from .secret_store import get_secret, api_key_name
            default=providers.get(pid) or {}
            if default.get('key', True) and not get_secret(api_key_name(pid)):
                available=[name for name, meta in providers.items()
                           if meta.get('chat',True) and meta.get('key',True)
                           and get_secret(api_key_name(name))]
                if len(available)==1:
                    pid=available[0]
        info=providers.get(pid)
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
        except RuntimeError as exc:
            if str(exc)=="Provider API key is not configured":
                logger.info("Model discovery skipped: provider API key is not configured")
                await self._send({"type":"models","provider":str(provider_id or self.cfg.provider),"current_model":"","models":[],"info":"Configure a provider API key to discover models."})
            else:
                logger.exception("Model discovery failed")
                await self._send({"type":"models","provider":str(provider_id or self.cfg.provider),"current_model":"","models":[],"error":f"{type(exc).__name__}: {exc}"})
        except Exception as exc:
            logger.exception("Model discovery failed")
            await self._send({"type":"models","provider":str(provider_id or self.cfg.provider),"current_model":"","models":[],"error":f"{type(exc).__name__}: {exc}"})

    async def _cancel_turn(self,msg):
        sid=str(msg.get("session_id") or ""); requested=str(msg.get("turn_id") or "")
        if not sid or len(sid)>128 or len(requested)>128: return
        entry=self._turn_tasks.get(sid)
        if not entry or entry[1].done() or (requested and requested!=entry[0]):
            await self._send_event(sid,{"type":"cancelled","status":"not_running"})
            return
        turn_id,task=entry
        if turn_id in self._cancel_requested: return
        self._cancel_requested.add(turn_id)
        task.cancel()

    async def _run_message(self,msg):
        sid=str(msg.get("session_id") or str(uuid.uuid4()))
        if len(sid)>128: return
        incoming_id=str(msg.get("message_id") or "").strip()
        if _turn_is_busy(self._turn_state,sid,incoming_id):
            await self._send_event(sid,{"type":"error","code":"turn_in_progress","message":"A turn is already running in this conversation. Wait for it to finish or stop it first."})
            return
        text=str(msg.get("message") or "").strip()
        if not text or len(text.encode("utf-8"))>256*1024: return
        requested_provider=str(msg.get("provider") or self.cfg.provider).strip()
        try: provider_cfg=self._chat_provider_cfg(requested_provider)
        except Exception as exc:
            await self._send_event(sid,{"type":"error","message":f"{type(exc).__name__}: {exc}"}); return
        requested_model=str(msg.get("model") or provider_cfg.model).strip()
        if not requested_model or len(requested_model)>160 or any(ord(c)<32 for c in requested_model):
            requested_model=provider_cfg.model
        images=msg.get("images") or []; context=msg.get("context") or []; preferred=msg.get("preferred_mcp_server_ids") or []
        if not isinstance(images,list) or len(images)>8 or not isinstance(context,list) or len(context)>100 or not isinstance(preferred,list) or len(preferred)>32: return
        logger.info("Selected provider/model for session %s: %s/%s", sid, requested_provider, requested_model)
        # Bound long-lived agent memory: expire idle sessions and cap the cache.
        now=time.monotonic()
        _expire_idle_sessions(self.sessions, self._session_last_used, now)
        # Anahtar parmak izi: Desktop anahtarı değiştirirse uzun ömürlü süreç eski anahtarlı oturumu kullanmaz.
        from .secret_store import provider_key_fingerprint
        session_key=f"{sid}:{requested_provider}:{requested_model}:{provider_key_fingerprint(requested_provider)}"
        session=self.sessions.get(session_key)
        _evict_session_if_full(self.sessions, self._session_last_used, session is not None)
        if session is None:
            provider=make_provider(provider_cfg)
            provider.model=requested_model
            session=self.sessions[session_key]=AgentSession(provider_cfg,provider,build_server(provider_cfg, artifact_session_id=sid),policy=__import__("mcptoai_linux.policy",fromlist=["ToolPolicy"]).ToolPolicy(rules={**load_rules(),**{name:__import__("mcptoai_linux.policy",fromlist=["Decision"]).Decision((self._remote_tool_map[name][0].get("tools") or {}).get(self._remote_tool_map[name][1],"confirm")) for name in self._remote_tool_specs}}),remote_tools=list(self._remote_tool_specs.values()),remote_caller=self._call_remote_tool,server_aliases=self._server_aliases())
        session.activity_session_id=sid
        session.activity_provider=requested_provider
        self._session_last_used[session_key]=now
        # Images are data URLs; keep decoded payload bounded even if transport limits change.
        total_image_chars=0
        for image in images:
            if not isinstance(image,dict) or not isinstance(image.get("data_url"),str): return
            data_url=image["data_url"]
            if not data_url.startswith("data:image/") or ";base64," not in data_url: return
            total_image_chars += len(data_url)
        if total_image_chars>384*1024: return
        message_id=str(msg.get("message_id") or "").strip()
        if message_id:
            try: message_id=str(uuid.UUID(message_id))
            except (ValueError,TypeError,AttributeError): return
            claimed,prior=self._receipts.claim(message_id,sid)
            if not claimed:
                logger.warning("Duplicate message_id suppressed for session %s: %s (%s)",sid,message_id,prior)
                buffered=any(int(x.get("seq") or 0)>0 for x in self._event_journal.get(sid,()))
                if prior=="interrupted":
                    await self._send_event(sid,{"type":"error","message":"This request was interrupted on the device and will not be replayed automatically because its outcome may be unknown."})
                elif buffered:
                    await self._handle_event_replay_request({"session_id":sid,"after_seq":0})
                else:
                    await self._send_event(sid,{"type":"error","message":"This request was already processed on the device and will not be run again. Its previous result is no longer available in the replay buffer."})
                return
        turn_id=message_id or uuid.uuid4().hex
        _begin_turn(self._turn_state, self._turn_events, sid, turn_id)
        self._turn_tasks[sid]=(turn_id,asyncio.current_task())
        async def emit(event): await self._send_event(sid,event,turn_id=turn_id)
        async def approver(tool,args):
            aid=str(uuid.uuid4()); fut=asyncio.get_running_loop().create_future(); self.pending_approvals[aid]=(fut,sid)
            await self._send_event(sid,{"type":"approval_required","approval_id":aid,"tool":tool,"arguments":args},turn_id=turn_id)
            outcome = "expired"
            try:
                allowed = await asyncio.wait_for(fut,timeout=min(900, max(1, self.cfg.approval_timeout_seconds)))
                outcome = "approved" if allowed else "denied"
                return allowed
            except asyncio.TimeoutError:
                return False
            except asyncio.CancelledError:
                outcome = "cancelled"
                raise
            finally:
                self.pending_approvals.pop(aid,None)
                await self._send_event(sid,{"type":"approval_resolved","approval_id":aid,"status":outcome},turn_id=turn_id)
        capability=str(msg.get("capability") or "").strip().casefold()
        try:
            if capability: await session.run_capability(capability,text,approver,emit)
            else: await session.run(text,approver,emit,images=images,language=msg.get("language"),context=context,preferred_mcp_server_ids=preferred)
        except asyncio.CancelledError:
            if turn_id not in self._cancel_requested: raise
            task=asyncio.current_task()
            if task is not None and hasattr(task,"uncancel"): task.uncancel()
            await emit({"type":"cancelled","status":"cancelled","message":"Stopped. Actions that already completed are not undone."})
            if message_id: self._receipts.finish(message_id,"cancelled")
        except Exception as exc:
            logger.exception("Agent session failed"); await emit({"type":"error","message":f"{type(exc).__name__}: {exc}"})
            if message_id: self._receipts.finish(message_id,"failed")
        else:
            if message_id: self._receipts.finish(message_id,"completed")
        finally:
            _finish_turn(self._turn_state, sid, turn_id)
            if self._turn_tasks.get(sid,(None,))[0]==turn_id:
                self._turn_tasks.pop(sid,None)
            self._cancel_requested.discard(turn_id)

async def run_relay_client(cfg:Settings): await RelayClient(cfg).run_forever()
