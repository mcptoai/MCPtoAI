"""Komut satırı: python -m mcptoai_agent <komut>

  set-key <anthropic|openai|evren>  API anahtarını Keychain'e kaydeder
  login                       Cihazı Auth0 hesabına bağlar (Device Flow)
  tools                       Etkin araçları listeler
  chat                        Yerel terminal sohbeti (onaylar terminalden)
  connect                     MCPtoAI relay'ine outbound WSS bağlantısı açar
  doctor                      Yapılandırmayı sırları göstermeden kontrol eder
"""

from __future__ import annotations
from .paths import config_dir

import argparse
import sys
import asyncio
import getpass
import json
import logging
import sys

from .config import settings
from .secret_store import api_key_name, set_secret, get_secret


def _configure_console_encoding():
    import sys
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError, AttributeError):
                pass


def _write_json_stdout(value) -> None:
    """Write one JSON line as UTF-8 bytes, independent of Windows console code pages."""
    payload=(json.dumps(value,ensure_ascii=False,default=str)+"\n").encode("utf-8")
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def _set_key(provider: str, from_stdin: bool = False) -> None:
    from .secret_store import sanitize_api_key
    raw = (sys.stdin.readline() if from_stdin else getpass.getpass(f'{provider} API key: ')).strip()
    key = sanitize_api_key(raw)
    if key != raw:
        print("Removed terminal control characters or spaces from the pasted key (a terminal paste can add escape sequences).", file=sys.stderr)
    if not key:
        raise SystemExit("Anahtar boş")
    set_secret(api_key_name(provider), key)
    print("Kaydedildi (Keychain).")


async def _list_tools() -> None:
    from fastmcp import Client
    from .tools import build_server

    async with Client(build_server(settings)) as c:
        for t in await c.list_tools():
            print(f"- {t.name}: {t.description}")


async def _chat() -> None:
    from .agent import AgentSession
    from .providers import make_provider
    from .tools import build_server

    session = AgentSession(settings, make_provider(settings), build_server(settings))

    async def approver(tool: str, args: dict) -> bool:
        ans = input(f"\n[ONAY] {tool} {json.dumps(args, ensure_ascii=False)} çalıştırılsın mı? (e/h) ")
        return ans.strip().lower() in {"e", "evet", "y", "yes"}

    async def emit(event: dict) -> None:
        if event["type"] == "tool_request":
            print(f"  → {event['name']} {json.dumps(event['arguments'], ensure_ascii=False)}")
        elif event["type"] == "tool_result":
            print(f"  ← {event['name']} {'HATA' if event['is_error'] else 'ok'}")
        elif event["type"] == "text":
            print(f"\n{event['text']}\n")

    print(f"MCPtoAI ({settings.provider}/{settings.model}) — çıkmak için Ctrl+C")
    while True:
        text = input("> ").strip()
        if text:
            await session.run(text, approver, emit)



def _bool_env(name: str) -> bool:
    """Ortam değişkeninin açık olup olmadığı (config._bool ile aynı yorum)."""
    from .config import _bool
    return _bool(name)

def main() -> None:
    _configure_console_encoding()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    if "connect" in sys.argv[1:] or "chatgpt-auth" in sys.argv[1:]:
        from logging.handlers import RotatingFileHandler
        import os
        from pathlib import Path
        logdir = (Path(os.environ.get("LOCALAPPDATA", Path.home()/"AppData"/"Local"))/"MCPtoAI"/"Logs") if os.name == "nt" else (Path.home()/"Library"/"Logs"/"MCPtoAI")
        logdir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(logdir/"agent-error.log", maxBytes=2*1024*1024, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)
    p = argparse.ArgumentParser(prog="mcptoai-agent")
    p.add_argument("--version", action="store_true", help="show version and build commit")
    sub = p.add_subparsers(dest="cmd")
    sk = sub.add_parser("set-key")
    sk.add_argument("provider")
    sk.add_argument("--stdin", action="store_true", help=argparse.SUPPRESS)
    rk = sub.add_parser("remove-key")
    rk.add_argument("provider")
    sub.add_parser("login")
    sub.add_parser("pair-status")
    sub.add_parser("status")
    sub.add_parser("logout")
    sub.add_parser("clear-local-data")
    ks=sub.add_parser("key-status"); ks.add_argument("provider")
    sub.add_parser("provider-registry")
    sw=sub.add_parser("siwc-web"); sw.add_argument("action",choices=["status","on","off"])
    siwc = sub.add_parser("chatgpt-auth")
    siwc.add_argument("action", choices=("status", "login", "logout", "clear-local", "cleanup-unlinked"))
    sub.add_parser("add-mcp-json")
    rm=sub.add_parser("remove-mcp"); rm.add_argument("server_id")
    mas=sub.add_parser("mcp-auth-status"); mas.add_argument("server_id")
    gas=sub.add_parser("github-auth-status"); gas.add_argument("server_id")
    sub.add_parser("google-drive-auth-json")
    sub.add_parser("google-drive-status")
    sub.add_parser("google-drive-disconnect")
    sub.add_parser("google-drive-mcp")
    sub.add_parser("tools")
    sub.add_parser("chat")
    sub.add_parser("chat-once-json")
    sub.add_parser("desktop-chat-jsonl")
    cc=sub.add_parser("cloud-chats"); cc.add_argument("action",choices=["list","get"]); cc.add_argument("session_id",nargs="?")
    sub.add_parser("cloud-ipc-json")
    sub.add_parser("cloud-ipc-jsonl")
    sub.add_parser("connect")
    sub.add_parser("supervise")
    sub.add_parser("activity-list")
    sub.add_parser("activity-status")
    setting=sub.add_parser("activity-recording")
    setting.add_argument("enabled", choices=("on", "off"))
    clear=sub.add_parser("activity-clear")
    clear.add_argument("--confirm", action="store_true")

    ds=sub.add_parser("discover-mcp"); ds.add_argument("server_id")
    sub.add_parser("list-models")
    sub.add_parser("probe-provider")
    shell_access=sub.add_parser("shell-access"); shell_access.add_argument("action",choices=["status","on","off"])
    siwc_preview=sub.add_parser("siwc-preview"); siwc_preview.add_argument("action",choices=["status","on","off"])
    perm=sub.add_parser("permission"); perm.add_argument("action",choices=["status","request"]); perm.add_argument("kind",choices=["screen"])
    sk=sub.add_parser("skills")
    sk_sub=sk.add_subparsers(dest="skills_action",required=True)
    sk_sub.add_parser("list")
    sk_ins=sk_sub.add_parser("inspect");sk_ins.add_argument("source");sk_ins.add_argument("--package",required=True);sk_ins.add_argument("--commit",required=True)
    sk_add=sk_sub.add_parser("add")
    sk_add.add_argument("source",help="Local package directory or https://github.com/<owner>/<repo>")
    sk_add.add_argument("--package",required=True)
    sk_add.add_argument("--commit",required=True,help="40-character pinned Git commit SHA")
    sk_add.add_argument("--approve",action="store_true",help="Confirm reviewed file and SHA list")
    sk_add.add_argument("--expected-digest",help="SHA256 of reviewed package preview")
    sk_rm=sk_sub.add_parser("remove");sk_rm.add_argument("package",help="Installed package name (skills are removed per package)")
    sk_en=sk_sub.add_parser("enable");sk_en.add_argument("name")
    sk_dis=sk_sub.add_parser("disable");sk_dis.add_argument("name")
    sub.add_parser("doctor")
    args = p.parse_args()
    if args.version:
        from . import __version__ as v
        try:
            from importlib.resources import files
            info=json.loads(files("mcptoai_agent").joinpath("build-info.json").read_text())
        except (FileNotFoundError, OSError, ValueError):
            info={}
        print(f"mcptoai-agent {v} commit={info.get('commit','unknown')} date={info.get('date','unknown')} platform={info.get('platform','unknown')} dirty={str(info.get('dirty','unknown')).lower()}")
        return
    if not args.cmd: p.error("a command is required")

    if args.cmd == "skills":
        from . import skills as skill_store
        from pathlib import Path
        if args.skills_action == "inspect":
            from .extension_discovery import inspect_repository
            import tempfile
            if args.source.startswith('https://'):
                with tempfile.TemporaryDirectory() as tmp:
                    root=skill_store.fetch_github(args.source,args.commit,Path(tmp),whole_repository=True)
                    print(json.dumps(inspect_repository(root,args.package,args.commit),indent=2))
            else:
                print(json.dumps(inspect_repository(Path(args.source),args.package,args.commit),indent=2))
        elif args.skills_action == "list":
            print(json.dumps(skill_store.list_skills(),indent=2))
        elif args.skills_action == "add":
            import tempfile
            def _install(folder):
                preview=skill_store.inspect_package(folder,args.package,args.commit)
                print(json.dumps(preview,indent=2))
                if args.approve:
                    if not args.expected_digest or args.expected_digest != skill_store.preview_digest(preview):
                        raise PermissionError('Reviewed package digest mismatch; inspect again')
                    skill_store.install_package(folder,args.package,args.commit,approved=True)
                else:
                    print("Review the files and hashes, then repeat with --approve to install.")
            if args.source.startswith("https://"):
                # GitHub kaynağı yalnızca tam commit SHA'sından çekilir ve çekilen commit doğrulanır.
                with tempfile.TemporaryDirectory() as tmp:
                    _install(skill_store.fetch_github(args.source,args.commit,Path(tmp)))
            else:
                _install(Path(args.source))
        elif args.skills_action == "remove":
            print(json.dumps({"removed_package":args.package,"skills":skill_store.remove_package(args.package)}))
        elif args.skills_action in {"enable","disable"}:
            skill_store.set_enabled(args.name,args.skills_action=="enable")
        return
    if args.cmd in {"set-key","remove-key","key-status"}:
        import re
        if not re.fullmatch(r"[a-z0-9_-]{1,64}",args.provider): raise SystemExit("Invalid provider ID")
    if args.cmd == "set-key":
        _set_key(args.provider, from_stdin=args.stdin)
    elif args.cmd == "remove-key":
        from .secret_store import delete_secret
        delete_secret(api_key_name(args.provider))
        print("Removed.")
    elif args.cmd == "add-mcp-json":
        from .mcp_config import add_server
        d=json.loads(sys.stdin.read()); item=add_server(d.get('name',''),d.get('command',''),d.get('args') or [],d.get('env') or {},d.get('transport','stdio'),d.get('url',''),d.get('headers') or {},d.get('oauth') or {})
        print(json.dumps({'ok':True,'id':item['id']}))
    elif args.cmd == "remove-mcp":
        from .mcp_config import remove_server
        print(json.dumps({'ok':remove_server(args.server_id)}))
    elif args.cmd == "mcp-auth-status":
        from .mcp_oauth import FileTokenStorage
        async def _oauth_status():
            tok=await FileTokenStorage(args.server_id).get_tokens()
            return bool(tok and (getattr(tok,'access_token',None) or getattr(tok,'refresh_token',None)))
        print('authorized' if asyncio.run(_oauth_status()) else 'not-authorized')
    elif args.cmd == "github-auth-status":
        from .discover_cli import probe_stdio_tool
        try:
            ok=asyncio.run(probe_stdio_tool(args.server_id,'get_me'))
        except Exception:
            ok=False
        print('authorized' if ok else 'not-authorized')
    elif args.cmd == "google-drive-auth-json":
        from .google_drive_integration import authorize
        draft=json.loads(sys.stdin.read() or '{}')
        try:
            result=asyncio.run(authorize(draft)); print('GOOGLE_DRIVE_AUTH '+json.dumps(result),flush=True)
        except Exception as exc:
            print('GOOGLE_DRIVE_ERROR '+json.dumps({'error':str(exc)}),flush=True); raise SystemExit(2)
    elif args.cmd == "google-drive-status":
        from .google_drive_integration import status
        print(json.dumps(status()))
    elif args.cmd == "google-drive-disconnect":
        from .google_drive_integration import disconnect
        asyncio.run(disconnect()); print(json.dumps({'ok':True}))
    elif args.cmd == "google-drive-mcp":
        from .google_drive_integration import build_google_drive_mcp
        build_google_drive_mcp().run(transport='stdio',show_banner=False)
    elif args.cmd == "chatgpt-auth":
        from .config import local_permission
        if not local_permission('siwc_enabled'):
            print(json.dumps({"ok": False, "error": "ChatGPT Preview is off. Enable it in Desktop settings."}))
            return
        from . import siwc_auth
        try:
            result = {"status": siwc_auth.status, "login": siwc_auth.sign_in, "logout": siwc_auth.sign_out, "cleanup-unlinked": siwc_auth.cleanup_unlinked, "clear-local": siwc_auth.clear_local}[args.action]()
            print(json.dumps({"ok": True, **result}))
        except Exception as exc:
            import traceback
            # Never write exception arguments, URLs or local variables to disk:
            # OAuth transport exceptions may contain bearer tokens or authorization codes.
            # Stack frames (file/function/line) plus a safe, bounded reason retain diagnostics.
            if isinstance(exc, PermissionError) and 'eski bir ChatGPT bağlantısı' in str(exc):
                reason = 'Bu cihazda eski bir ChatGPT bağlantısı var; önce temizleyin.'
            elif isinstance(exc, PermissionError) and 'Plan kullanımı izni verilmedi' in str(exc):
                reason = 'Plan kullanımı izni verilmedi. https://chatgpt.com/settings/usage'
            elif isinstance(exc, PermissionError):
                reason = 'ChatGPT bağlantısı bu MCPtoAI hesabına ait değil veya erişim reddedildi.'
            elif isinstance(exc, TimeoutError):
                reason = 'ChatGPT bağlantısı zaman aşımına uğradı.'
            else:
                reason = 'ChatGPT ' + args.action + ' başarısız. Ayrıntılar Agent hata günlüğünde.'
            safe_type = type(exc).__name__
            safe_stack = ''.join(traceback.format_list(traceback.extract_tb(exc.__traceback__)))
            logging.getLogger('mcptoai.siwc').error('SIWC %s failed: %s: %s\n%s',
                                                    args.action, safe_type, reason, safe_stack)
            print(json.dumps({"ok": False, "error": reason, "error_type": safe_type}))
    elif args.cmd == "provider-registry":
        from .provider_registry import registry
        providers = registry(settings.user_settings.get("custom_providers") or {})
        # Return presence only; provider secrets never leave the OS credential store.
        from .config import local_permission
        preview_enabled = local_permission('siwc_enabled')
        for provider_id, meta in providers.items():
            try:
                if provider_id == "chatgpt":
                    if not preview_enabled:
                        meta["has_key"] = False
                        meta["linked"] = False
                        meta["reason"] = "preview_disabled"
                    else:
                        from .siwc_auth import status
                        state = status()
                        meta["has_key"] = state["connected"] and state["sharing"]
                        meta["sharing"] = state["sharing"]
                        meta["linked"] = state["linked"]
                        meta["reason"] = state["reason"]
                        meta["usage_url"] = "https://chatgpt.com/settings/usage"
                else:
                    meta["has_key"] = False if meta.get("key") is False else bool(get_secret(api_key_name(provider_id)))
            except Exception:
                meta["has_key"] = False
                meta["error"] = "Provider status unavailable"
                if provider_id == "chatgpt":
                    meta["linked"] = False
                    meta["reason"] = "status_unavailable"
        print(json.dumps(providers))
    elif args.cmd == "key-status":
        print("yes" if get_secret(api_key_name(args.provider)) else "no")
    elif args.cmd == "logout":
        from .auth import disconnect_device
        asyncio.run(disconnect_device(settings)); print("Disconnected.")
    elif args.cmd == "clear-local-data":
        import shutil
        from .secret_store import destroy_vault
        # 1) Backend'den cihazı düşürmeyi dene (ağ/kasa hatası temizliği engellemez)
        try:
            from .auth import disconnect_device
            asyncio.run(disconnect_device(settings))
        except Exception:
            pass
        # 2) Kasayı içeriğine bakmadan sil (bozuk kasa dahil). Başarısızsa
        #    identity.pub'u SİLME: kimlik koruması devam etmeli.
        destroy_vault()
        # 3) Yerel yapılandırma (identity.pub, oauth istemci bilgisi, ayarlar)
        shutil.rmtree(config_dir(),ignore_errors=True)
        print("Local MCPtoAI data removed.")
    elif args.cmd == "pair-status":
        from .auth import _auth_bundle, device_removed_state
        try:
            bundle = _auth_bundle()
        except Exception as exc:
            print(f"error: {type(exc).__name__}"); raise SystemExit(2)
        print("paired" if not device_removed_state() and bundle.get("refresh_token") and bundle.get("owner_sub") else "unpaired")
    elif args.cmd == "status":
        from .auth import _auth_bundle, device_removed_state
        removed=device_removed_state()
        if removed:
            print("This device was removed from your account. Pair it again.")
            raise SystemExit(2)
        try:
            bundle=_auth_bundle()
        except Exception as exc:
            print(f"Credential status error: {type(exc).__name__}")
            raise SystemExit(2)
        if bundle.get("refresh_token") and bundle.get("owner_sub"):
            print("Device paired.")
        else:
            print("Device not paired.")
    elif args.cmd == "login":
        from .auth import device_login
        sub_id = asyncio.run(device_login(settings))
        print(f"Cihaz eşleştirildi: {sub_id}")
    elif args.cmd == "tools":
        asyncio.run(_list_tools())
    elif args.cmd == "chat":
        try:
            asyncio.run(_chat())
        except KeyboardInterrupt:
            pass
    elif args.cmd == "desktop-chat-jsonl":
        async def desktop_chat():
            from .agent import AgentSession
            from .providers import make_provider
            from .tools import build_server
            from .policy import ToolPolicy
            from .mcp_config import load_rules
            from .relay_client import RelayClient
            # Local Chat is a separate Agent process, so it must discover connected
            # MCPs for itself instead of relying on the relay process's memory.
            remote_runtime=RelayClient(settings)
            await remote_runtime._discover_mcp_tools(allow_oauth_prompt=False)
            sessions={}
            active={}
            pending_approvals={}
            async def one(d):
                sid=str(d.get('session_id') or 'local')[:128]; text=str(d.get('text') or '').strip()
                if not text or len(text.encode('utf-8'))>256*1024: return
                from dataclasses import replace
                from .provider_registry import registry
                from .secret_store import get_secret, api_key_name
                requested_provider=str(d.get('provider') or settings.provider).strip()
                info=registry(settings.user_settings.get('custom_providers') or {}).get(requested_provider)
                if not info or info.get('chat') is False: raise ValueError('Unsupported chat provider')
                if requested_provider == "chatgpt":
                    from .siwc_auth import status
                    if not status()["connected"]: raise RuntimeError("ChatGPT sign-in required")
                elif info.get('key',True) and not get_secret(api_key_name(requested_provider)): raise RuntimeError('Provider API key is not configured')
                provider_cfg=replace(settings,provider=requested_provider,openai_base_url=info.get('base_url') or (settings.openai_base_url if requested_provider==settings.provider else None))
                requested_model=str(d.get('model') or provider_cfg.model).strip()
                if not requested_model or len(requested_model)>160 or any(ord(c)<32 for c in requested_model): requested_model=provider_cfg.model
                # Anahtar değişirse (Desktop set/remove-key) eski anahtarlı oturum kullanılmaz.
                from .secret_store import provider_key_fingerprint
                credential_identity = provider_key_fingerprint(requested_provider) if requested_provider != 'chatgpt' else 'oauth'
                session_key=f'{sid}:{requested_provider}:{requested_model}:{credential_identity}'
                session=sessions.get(session_key)
                if session is None:
                    provider=make_provider(provider_cfg, siwc_origin="desktop-local", siwc_user_initiated=True); provider.model=requested_model
                    remote_rules={name: __import__("mcptoai_agent.policy",fromlist=["Decision"]).Decision((remote_runtime._remote_tool_map[name][0].get("tools") or {}).get(remote_runtime._remote_tool_map[name][1],"confirm")) for name in remote_runtime._remote_tool_specs}
                    session=sessions[session_key]=AgentSession(provider_cfg,provider,build_server(provider_cfg),policy=ToolPolicy(rules={**load_rules(),**remote_rules}),remote_tools=list(remote_runtime._remote_tool_specs.values()),remote_caller=remote_runtime._call_remote_tool,server_aliases=remote_runtime._server_aliases())
                async def emit(event):
                    _write_json_stdout({'kind':'event','session_id':sid,'event':event})
                async def approver(tool,tool_args):
                    aid=__import__('uuid').uuid4().hex
                    fut=asyncio.get_running_loop().create_future()
                    pending_approvals[aid]=(sid,fut)
                    _write_json_stdout({'kind':'approval_required','session_id':sid,'approval_id':aid,'tool':tool,'arguments':tool_args})
                    try:
                        return await asyncio.wait_for(fut,timeout=settings.approval_timeout_seconds)
                    except asyncio.TimeoutError:
                        return False
                    finally:
                        pending_approvals.pop(aid,None)
                try:
                    images=d.get('images') if isinstance(d.get('images'),list) else []
                    images=images[:8]; total=sum(len(str(x.get('data_url') or '')) for x in images if isinstance(x,dict))
                    if total>384*1024: raise ValueError('Images are too large')
                    preferred=d.get('preferred_mcp_server_ids') if isinstance(d.get('preferred_mcp_server_ids'),list) else []
                    preferred=[str(x)[:128] for x in preferred[:32]]
                    context=d.get('context') if isinstance(d.get('context'),list) else []
                    context=[x for x in context[-40:] if isinstance(x,dict) and x.get('role') in {'user','assistant'} and isinstance(x.get('content'),str)]
                    if sum(len(x['content'].encode('utf-8')) for x in context)>256*1024: raise ValueError('Chat context is too large')
                    capability=str(d.get('capability') or '').strip().casefold()
                    if capability: await session.run_capability(capability,text,approver,emit)
                    else: await session.run(text,approver,emit,images=images,language=d.get('language'),context=context,preferred_mcp_server_ids=preferred)
                except Exception as exc:
                    _write_json_stdout({'kind':'event','session_id':sid,'event':{'type':'error','message':f'{type(exc).__name__}: {exc}'}})
                _write_json_stdout({'kind':'turn_done','session_id':sid})
            while True:
                line=await asyncio.to_thread(sys.stdin.readline)
                if not line: break
                try: d=json.loads(line)
                except Exception: continue
                typ=d.get('type'); sid=str(d.get('session_id') or 'local')[:128]
                if typ=='approval':
                    aid=str(d.get('approval_id') or '')
                    item=pending_approvals.get(aid)
                    if item:
                        expected_sid,fut=item
                        if sid==expected_sid and not fut.done():
                            fut.set_result(d.get('approve') is True)
                    continue
                if typ=='cancel':
                    task=active.get(sid)
                    if task and not task.done(): task.cancel()
                    for aid,(approval_sid,fut) in list(pending_approvals.items()):
                        if approval_sid==sid and not fut.done(): fut.cancel()
                    continue
                if typ=='message':
                    prev=active.get(sid)
                    if prev and not prev.done():
                        _write_json_stdout({'kind':'event','session_id':sid,'event':{'type':'error','message':'A message is already running in this local chat.'}})
                        _write_json_stdout({'kind':'turn_done','session_id':sid})
                        continue
                    async def run_one(msg=d,key=sid):
                        try: await one(msg)
                        except asyncio.CancelledError:
                            _write_json_stdout({'kind':'event','session_id':key,'event':{'type':'cancelled'}})
                            _write_json_stdout({'kind':'turn_done','session_id':key})
                        finally: active.pop(key,None)
                    active[sid]=asyncio.create_task(run_one())
        asyncio.run(desktop_chat())
    elif args.cmd == "chat-once-json":
        async def run_once():
            from .agent import AgentSession
            from .providers import make_provider
            from .tools import build_server
            d=json.loads(sys.stdin.read() or '{}'); text=str(d.get('text') or '').strip()
            if not text or len(text.encode('utf-8'))>256*1024: raise ValueError('Invalid chat message')
            context=d.get('context') if isinstance(d.get('context'),list) else []
            if len(context)>40: context=context[-40:]
            events=[]
            async def approver(tool,args): return False
            async def emit(event): events.append(event)
            session=AgentSession(settings,make_provider(settings),build_server(settings))
            answer=await session.run(text,approver,emit,context=context,language=d.get('language'))
            _write_json_stdout({'ok':True,'text':answer,'events':events})
        try: asyncio.run(run_once())
        except Exception as exc: print(json.dumps({'ok':False,'error':f'{type(exc).__name__}: {exc}'})); raise SystemExit(1)
    elif args.cmd == "cloud-ipc-jsonl":
        async def cloud_ipc_jsonl():
            from .cloud_chat import handle_cloud_chat_request
            while True:
                raw=await asyncio.to_thread(sys.stdin.buffer.readline)
                if not raw:
                    break
                if len(raw)>512*1024:
                    _write_json_stdout({"ok":False,"error":"Cloud chat request too large"})
                    continue
                try:
                    req=json.loads(raw.decode("utf-8"))
                    if not isinstance(req,dict):
                        raise ValueError("Cloud chat request must be an object")
                    result=await handle_cloud_chat_request(settings,req)
                except Exception as exc:
                    result={"ok":False,"error":f"{type(exc).__name__}: {exc}"}
                _write_json_stdout(result)
        asyncio.run(cloud_ipc_jsonl())
    elif args.cmd == "cloud-ipc-json":
        async def cloud_ipc_json():
            raw=sys.stdin.buffer.read(512*1024+1)
            if len(raw)>512*1024:
                raise ValueError("Cloud chat request too large")
            req=json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(req,dict):
                raise ValueError("Cloud chat request must be an object")
            from .cloud_chat import handle_cloud_chat_request
            result=await handle_cloud_chat_request(settings,req)
            _write_json_stdout(result)
        try:
            asyncio.run(cloud_ipc_json())
        except Exception as exc:
            _write_json_stdout({"ok":False,"error":f"{type(exc).__name__}: {exc}"})
            raise SystemExit(1)
    elif args.cmd == "cloud-chats":
        async def cloud_chats():
            import httpx
            from .auth import get_access_token
            token=await get_access_token(settings); base=settings.server_url.rstrip('/')+'/api/chats/'
            url=base if args.action=='list' else base+str(args.session_id or '')+'/'
            async with httpx.AsyncClient(timeout=15) as http:
                r=await http.get(url,headers={'Authorization':f'Bearer {token}'})
                r.raise_for_status(); print(json.dumps(r.json(),ensure_ascii=False,default=str))
        try: asyncio.run(cloud_chats())
        except Exception as exc: print(json.dumps({'ok':False,'error':f'{type(exc).__name__}: {exc}'})); raise SystemExit(1)
    elif args.cmd == "discover-mcp":
        from .discover_cli import run
        raise SystemExit(run(args.server_id))
    elif args.cmd == "probe-provider":
        from .provider_probe import run
        try:
            run()
        except Exception as exc:
            print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), flush=True)
    elif args.cmd == "list-models":
        from .providers import make_provider
        try:
            print(json.dumps({"ok": True, "models": asyncio.run(make_provider(settings).list_models())}), flush=True)
        except Exception as exc:
            if settings.provider == "ollama":
                msg = "Ollama is not running or cannot be reached at http://127.0.0.1:11434."
            elif settings.provider == "lmstudio":
                msg = "LM Studio is not running or its local API server cannot be reached at http://127.0.0.1:1234."
            else:
                msg = f"{type(exc).__name__}: {exc}"
            print(json.dumps({"ok": False, "error": msg}), flush=True)
    elif args.cmd == "siwc-web":
        from .config import local_permission, save_local_permission
        if args.action == "on":
            if not local_permission("siwc_enabled"):
                print(json.dumps({"ok":False,"error":"Enable Desktop Preview first."}))
                return
            save_local_permission("siwc_web_enabled",True)
        elif args.action == "off":
            save_local_permission("siwc_web_enabled",False)
        print(json.dumps({"ok":True,"enabled":local_permission("siwc_enabled") and local_permission("siwc_web_enabled")}))
    elif args.cmd == "siwc-preview":
        from .config import local_permission, save_local_permission
        if args.action in ("on", "off"):
            save_local_permission("siwc_enabled", args.action == "on")
            if args.action == "off": save_local_permission("siwc_web_enabled",False)
        print(json.dumps({"enabled": local_permission("siwc_enabled"), "web_allowed": local_permission("siwc_enabled") and local_permission("siwc_web_enabled")}))
    elif args.cmd == "shell-access":
        # Yerel izin: yalnızca bu cihazda çalışan komutla değiştirilir (relay/web değiştiremez).
        from .config import local_permission, save_local_permission
        if args.action in ("on","off"):
            save_local_permission("shell", args.action=="on")
        print(json.dumps({"enabled": local_permission("shell"), "env_override": _bool_env("MCPTOAI_ENABLE_SHELL")}))
    elif args.cmd == "permission":
        from .macos_permissions import screen_status, request_screen
        if args.action=="status": print(screen_status())
        else: print("granted" if request_screen() else screen_status())
    elif args.cmd == "doctor":
        from .auth import device_removed_state
        removed=device_removed_state()
        checks = {
            "MCPtoAI server": settings.server_url,
            "Auth0 domain": "configured" if settings.auth0_domain else "MISSING",
            "Auth0 Native Client ID": "configured" if settings.auth0_device_client_id else "MISSING",
            "Auth0 audience": settings.auth0_audience,
            "Provider": settings.provider,
            "Device status": "This device was removed from your account. Pair it again." if removed else "OK",
            "Credential vault": __import__("mcptoai_agent.secret_store",fromlist=["vault_status"]).vault_status(),
        }
        for name, value in checks.items():
            print(f"{name}: {value}")
        from .security_php import inspect_php
        php = inspect_php()
        if php.status != "absent":
            print(f"PHP security [{php.status.upper()}]: {php.detail}")
        if not settings.auth0_domain or not settings.auth0_device_client_id:
            raise SystemExit("MCPtoAI production Auth0 configuration is incomplete.")
    elif args.cmd == "activity-list":
        # Metadata-only local history. Never export tool arguments or outputs.
        from .activity_store import ActivityStore
        store = ActivityStore()
        try:
            rows = store.list_events(limit=100)
            allowed = ('activity_id','session_id','tool_name','phase','timestamp_utc','target_display','duration_ms','permission_decision','provider','model')
            print(json.dumps([{k: row[k] for k in allowed if k in row} for row in rows]))
        finally:
            store.close()
    elif args.cmd == "activity-status":
        from .activity_recorder import recording_enabled
        print(json.dumps({"enabled": recording_enabled()}))
    elif args.cmd == "activity-recording":
        from .config import _user_settings, save_user_settings
        activity_settings = dict(_user_settings())
        activity_settings["activity_recording_enabled"] = args.enabled == "on"
        save_user_settings(activity_settings)
        print(json.dumps({"enabled": activity_settings["activity_recording_enabled"]}))
    elif args.cmd == "activity-clear":
        if not args.confirm:
            raise SystemExit("Explicit --confirm required")
        from .activity_store import ActivityStore
        store = ActivityStore()
        try: print(json.dumps({"deleted_count": store.clear()}))
        finally: store.close()

    elif args.cmd == "supervise":
        from .agent_supervisor import run
        raise SystemExit(run())
    elif args.cmd == "connect":
        from .agent_signals import install_connect_sigterm_handler
        from .relay_client import run_relay_client
        from .agent_instance_lock import agent_instance_lock
        from .credential_lock import CredentialLockTimeout
        try:
            install_connect_sigterm_handler()
            with agent_instance_lock():
                asyncio.run(run_relay_client(settings))
        except CredentialLockTimeout:
            raise SystemExit("MCPtoAI agent is already running on this device.")
        except KeyboardInterrupt:
            pass



if __name__ == "__main__":
    _configure_console_encoding()
    main()
