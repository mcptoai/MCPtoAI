from __future__ import annotations
import asyncio,json,os
from urllib.parse import urlparse,parse_qs
import httpx
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from .mcp_config import custom_servers
from .mcp_oauth import OAUTH_CALLBACK_URL, oauth_metadata_for, oauth_provider_for, prepare_oauth_storage

async def discover(server_id:str):
    server=next((s for s in custom_servers() if s.get('id')==server_id),None)
    if not server: raise RuntimeError('MCP server not found')
    if server.get('transport')=='stdio':
        params=StdioServerParameters(command=server['command'],args=server.get('args') or [],env={**os.environ,**(server.get('env') or {})})
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize(); result=await session.list_tools(); return [t.name for t in result.tools]
    state={'value':None}
    async def redirect(url):
        state['value']=(parse_qs(urlparse(url).query).get('state') or [None])[0]
        if not state['value']: raise RuntimeError('OAuth state missing')
        endpoint=OAUTH_CALLBACK_URL
        async with httpx.AsyncClient(timeout=10) as h:
            register=await h.post(endpoint,json={'state':state['value']})
            register.raise_for_status()
        # Log only non-secret OAuth request metadata for diagnostics.
        from urllib.parse import urlparse as _up, parse_qs as _pq
        _q=_pq(_up(url).query)
        print('AUTH_META '+json.dumps({'host':_up(url).netloc,'scope':(_q.get('scope') or [''])[0],'resource':(_q.get('resource') or [''])[0],'state_prefix':(state['value'] or '')[:8]}),flush=True)
        print('AUTH_URL '+url,flush=True)
    async def callback():
        if not state['value']: raise RuntimeError('OAuth state missing')
        endpoint=OAUTH_CALLBACK_URL
        async with httpx.AsyncClient(timeout=10) as h:
            for _ in range(600):
                r=await h.get(endpoint,params={'state':state['value']})
                if r.status_code==200:
                    d=r.json()
                    if d.get('error'): raise RuntimeError(d['error'])
                    if d.get('code'): return d['code'],d.get('state')
                await asyncio.sleep(1)
        raise TimeoutError('OAuth callback timed out')
    metadata=oauth_metadata_for(server)
    storage=await prepare_oauth_storage(server)
    auth=oauth_provider_for(server,metadata,storage,redirect,callback)
    async with streamablehttp_client(server['url'],headers=server.get('headers') or {},timeout=20,auth=auth) as streams:
        async with ClientSession(streams[0],streams[1]) as session:
            await session.initialize()
            result=await session.list_tools()
            # Google Drive exposes its tool catalogue before account authorization.
            # A tiny read-only probe forces the actual OAuth challenge so that
            # 'Connect' means an account was really authorized, not merely discovered.
            if server.get('managed_integration') == 'google-drive-official':
                probe=await session.call_tool('list_recent_files',{'pageSize':1,'excludeContentSnippets':True})
                if getattr(probe,'isError',False):
                    raise RuntimeError('Google Drive authorization was not completed')
            return [t.name for t in result.tools]

async def probe_stdio_tool(server_id: str, tool_name: str = "get_me") -> bool:
    server=next((s for s in custom_servers() if s.get('id')==server_id),None)
    if not server or server.get('transport')!='stdio':
        raise RuntimeError('STDIO MCP server not found')
    env=server.get('env') or {}
    # GitHub MCP exposes get_me even without a PAT and returns an OAuth instruction
    # as a successful tool result. Never treat that state as authenticated.
    if server.get('managed_integration') == 'github-official' and not str(env.get('GITHUB_PERSONAL_ACCESS_TOKEN') or '').strip():
        return False
    params=StdioServerParameters(command=server['command'],args=server.get('args') or [],env={**os.environ,**env})
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            tools=await session.list_tools()
            if tool_name not in {t.name for t in tools.tools}:
                raise RuntimeError(f'MCP tool not available: {tool_name}')
            result=await session.call_tool(tool_name,{})
            text=' '.join(str(getattr(x,'text','')) for x in (getattr(result,'content',None) or [])).strip()
            if getattr(result,'isError',False):
                raise RuntimeError(text or f'{tool_name} failed')
            # Önce yapısal kontrol: get_me bir kullanıcı JSON'u döndürdüyse (login alanı
            # dolu) token kesin olarak geçerlidir. Profil metninde "to authorize" geçse
            # bile yanlışlıkla reddedilmez.
            try:
                data=json.loads(text)
            except ValueError:
                data=None
            if isinstance(data,dict) and str(data.get('login') or '').strip():
                return True
            # Yapısal olmayan yanıtlar için önceki kontrol: tokensız GitHub MCP, OAuth
            # talimatını başarılı bir araç sonucu olarak döndürür.
            low=text.casefold()
            if 'to authorize' in low or 'authorization' in low and ('http://localhost' in low or 'https://github.com/login' in low):
                return False
            return True

def _friendly_error(exc:BaseException)->dict:
    text=str(exc)
    # ExceptionGroup often hides the useful nested OAuth exception in str().
    parts=[]
    def walk(e):
        parts.append(str(e))
        response=getattr(e,'response',None)
        if response is not None:
            try:
                body=(response.text or '').strip()
                if body:
                    parts.append('HTTP_BODY '+body[:1200])
            except Exception:
                pass
        for child in getattr(e,'exceptions',[]) or []: walk(child)
    walk(exc); detail=' | '.join(x for x in parts if x)
    low=detail.lower()
    if 'invalid_redirect_uri' in low or 'redirect uri' in low and 'not allowed' in low:
        return {'code':'oauth_invalid_redirect_uri','title':'OAuth callback not allowed','message':'This MCP server does not allow the MCPtoAI OAuth callback URL: https://app.mcptoai.com/api/mcp/oauth/callback','detail':detail[:1200]}
    if 'registration failed' in low or 'oauthregistrationerror' in low:
        return {'code':'oauth_registration_failed','title':'OAuth registration failed','message':'The MCP server rejected OAuth client registration.','detail':detail[:1200]}
    if '401' in low or 'unauthorized' in low:
        return {'code':'unauthorized','title':'Authentication required','message':'The MCP server requires authentication and the connection could not be authorized.','detail':detail[:1200]}
    if '403' in low or 'forbidden' in low:
        return {'code':'forbidden','title':'Access denied','message':'The MCP server refused access.','detail':detail[:1200]}
    if 'timed out' in low or 'timeout' in low:
        return {'code':'timeout','title':'Connection timed out','message':'The MCP server did not complete the connection in time.','detail':detail[:1200]}
    return {'code':'connection_failed','title':'MCP connection failed','message':'MCPtoAI could not complete tool discovery for this server.','detail':detail[:1200]}

def run(server_id:str):
    try:
        tools=asyncio.run(discover(server_id)); print('TOOLS '+json.dumps(tools),flush=True); return 0
    except BaseException as exc:
        print('MCP_ERROR '+json.dumps(_friendly_error(exc),ensure_ascii=False),flush=True)
        return 2
