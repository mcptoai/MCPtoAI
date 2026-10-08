from __future__ import annotations
import json, uuid, ipaddress, socket
from urllib.parse import urlparse
from pathlib import Path
from .policy import DEFAULT_RULES, Decision, CAPABILITIES
from .mcp_secrets import store_map,load_map,delete_map
from .paths import config_dir

PATH=config_dir()/'mcp-tools.json'

def validate_remote_mcp_url(url:str)->str:
    value=str(url or '').strip()
    try: p=urlparse(value)
    except Exception: raise ValueError('Invalid MCP URL')
    if p.scheme != 'https' or not p.hostname or p.username or p.password:
        raise ValueError('Remote MCP URL must use HTTPS without embedded credentials')
    host=p.hostname.rstrip('.').lower()
    if host == 'localhost' or host.endswith('.localhost'):
        raise ValueError('Local/private MCP URLs must be configured on this device')
    try:
        ip=ipaddress.ip_address(host)
        if not ip.is_global: raise ValueError('Local/private MCP URLs must be configured on this device')
    except ValueError as exc:
        if 'Local/private' in str(exc): raise
    try:
        infos=socket.getaddrinfo(host,p.port or 443,type=socket.SOCK_STREAM)
    except socket.gaierror as exc: raise ValueError('MCP host could not be resolved') from exc
    if not infos: raise ValueError('MCP host could not be resolved')
    for info in infos:
        ip=ipaddress.ip_address(info[4][0].split('%')[0])
        if not ip.is_global: raise ValueError('MCP hostname resolves to a local/private address')
    return value

def _bounded_map(values:dict|None,kind:str)->dict[str,str]:
    if not isinstance(values or {},dict): raise ValueError(f'{kind} must be an object')
    if len(values or {})>32: raise ValueError(f'Too many {kind} entries')
    out={}
    for k,v in (values or {}).items():
        key=str(k).strip(); val=str(v)
        if not key or len(key)>128 or any(c in key for c in '\r\n:'):
            raise ValueError(f'Invalid {kind} name')
        if len(val.encode('utf-8'))>8192 or '\r' in val or '\n' in val:
            raise ValueError(f'Invalid {kind} value')
        out[key]=val
    return out

def _raw()->dict:
    try:
        data=json.loads(PATH.read_text())
        return data if isinstance(data,dict) else {}
    except (FileNotFoundError,json.JSONDecodeError):
        return {}

def _write(data:dict):
    PATH.parent.mkdir(parents=True,exist_ok=True)
    tmp=PATH.with_suffix('.tmp'); tmp.write_text(json.dumps(data,indent=2)); tmp.chmod(0o600); tmp.replace(PATH)

def load_rules()->dict[str,Decision]:
    raw=_raw(); out=dict(DEFAULT_RULES)
    for k,v in raw.get('tools',{}).items():
        try: out[k]=Decision(v)
        except ValueError: pass
    return out

def save_rules(values:dict[str,str])->dict[str,Decision]:
    raw=_raw(); rules=load_rules()
    for k,v in values.items():
        if k in DEFAULT_RULES: rules[k]=Decision(v)
    raw.update({'version':2,'tools':{k:v.value for k,v in rules.items()}})
    _write(raw); return rules

def load_capabilities()->dict[str,Decision]:
    raw=_raw(); saved=raw.get('capabilities') or {}; out={}
    for k,meta in CAPABILITIES.items():
        try: out[k]=Decision(saved.get(k,meta['default'].value))
        except ValueError: out[k]=meta['default']
    return out

def save_capability(name:str,value:str)->bool:
    if name not in CAPABILITIES: return False
    try: d=Decision(value)
    except ValueError: return False
    raw=_raw(); caps=dict(raw.get('capabilities') or {}); caps[name]=d.value; raw['capabilities']=caps
    tools=dict(raw.get('tools') or {})
    for tool in CAPABILITIES[name]['tools']:
        if tool in DEFAULT_RULES: tools[tool]=d.value
    raw['tools']=tools; raw['version']=4; _write(raw); return True

def custom_servers()->list[dict]:
    raw=_raw(); stored=list(raw.get('servers') or []); out=[]; migrated=False
    for src in stored:
        clean=dict(src); sid=str(clean.get('id') or '')
        if isinstance(clean.get('env'),dict):
            if clean['env']: clean['env_keys']=store_map(sid,'env',clean['env'])
            clean.pop('env',None); migrated=True
        if isinstance(clean.get('headers'),dict):
            if clean['headers']: clean['header_keys']=store_map(sid,'header',clean['headers'])
            clean.pop('headers',None); migrated=True
        s=dict(clean); s['env']=load_map(sid,'env',clean.get('env_keys') or []); s['headers']=load_map(sid,'header',clean.get('header_keys') or [])
        oauth_secret=load_map(sid,'oauth',clean.get('oauth_secret_keys') or [])
        if clean.get('oauth_client_id'):
            s['oauth']={'client_id':clean.get('oauth_client_id'),'client_secret':oauth_secret.get('client_secret',''),'token_endpoint_auth_method':clean.get('oauth_token_endpoint_auth_method') or 'client_secret_post'}
        out.append(s)
        src.clear(); src.update(clean)
    if migrated:
        raw['version']=4; raw['servers']=stored; _write(raw)
    return out

def add_server(name:str,command:str="",args:list[str]|None=None,env:dict|None=None,transport:str="stdio",url:str="",headers:dict|None=None,oauth:dict|None=None)->dict:
    raw=_raw(); servers=list(raw.get('servers') or [])
    transport=transport if transport in ("stdio","streamable-http") else "stdio"
    if not isinstance(args or [],list) or len(args or [])>64: raise ValueError('Invalid MCP arguments')
    clean_args=[str(x) for x in (args or [])]
    if any(len(x.encode('utf-8'))>4096 for x in clean_args): raise ValueError('MCP argument is too long')
    clean_env=_bounded_map(env,'environment'); clean_headers=_bounded_map(headers,'header')
    oauth=dict(oauth or {}) if isinstance(oauth or {},dict) else {}
    oauth_client_id=str(oauth.get('client_id') or '').strip()[:512]
    oauth_client_secret=str(oauth.get('client_secret') or '')
    oauth_auth_method=str(oauth.get('token_endpoint_auth_method') or 'client_secret_post')
    if oauth_client_secret and not oauth_client_id: raise ValueError('OAuth client ID is required when client secret is provided')
    if oauth_client_secret and len(oauth_client_secret.encode('utf-8'))>8192: raise ValueError('OAuth client secret is too long')
    if oauth_auth_method not in ('client_secret_post','client_secret_basic','none'): raise ValueError('Unsupported OAuth client authentication method')
    item={'id':'mcp-'+uuid.uuid4().hex[:12],'name':str(name).strip()[:80] or 'Custom MCP','transport':transport,'command':str(command).strip(),'args':clean_args,'env_keys':[],'url':url.strip(),'header_keys':[],'oauth_client_id':oauth_client_id,'oauth_secret_keys':[],'oauth_token_endpoint_auth_method':oauth_auth_method if oauth_client_id else '', 'enabled':True,'tools':{}}
    if transport=="stdio" and not item['command']: raise ValueError('Command is required')
    if transport=="streamable-http": item['url']=validate_remote_mcp_url(item['url'])
    item['env_keys']=store_map(item['id'],'env',clean_env); item['header_keys']=store_map(item['id'],'header',clean_headers)
    if oauth_client_secret: item['oauth_secret_keys']=store_map(item['id'],'oauth',{'client_secret':oauth_client_secret})
    servers.append(item); raw['version']=4; raw['servers']=servers; _write(raw); return item

def update_server(server_id:str,patch:dict)->dict|None:
    raw=_raw(); servers=list(raw.get('servers') or []); found=None
    for s in servers:
        if s.get('id')!=server_id: continue
        found=s
        if 'enabled' in patch: s['enabled']=bool(patch['enabled'])
        if 'name' in patch and str(patch['name']).strip(): s['name']=str(patch['name']).strip()[:80]
        if 'tools' in patch:
            requested=patch.get('tools') or {}
            if not isinstance(requested,dict) or len(requested)>256: raise ValueError('Invalid MCP tool permissions')
            perms=s.setdefault('tools',{})
            for k,v in requested.items():
                key=str(k)
                if len(key)>256: raise ValueError('Invalid MCP tool name')
                if v in ('deny','confirm','auto'): perms[key]=v
    _write(raw); return found

def remove_server(server_id:str)->bool:
    raw=_raw(); before=list(raw.get('servers') or []); target=next((s for s in before if s.get('id')==server_id),None); after=[s for s in before if s.get('id')!=server_id]
    if target:
        delete_map(server_id,'env',target.get('env_keys') or list((target.get('env') or {}).keys())); delete_map(server_id,'header',target.get('header_keys') or list((target.get('headers') or {}).keys())); delete_map(server_id,'oauth',(target.get('oauth_secret_keys') or ['client_secret']) if target.get('oauth_client_id') else (target.get('oauth_secret_keys') or []))
        from .mcp_oauth import delete_oauth_storage
        delete_oauth_storage(server_id)
    raw['servers']=after; _write(raw); return len(after)!=len(before)

def state(discovered:dict[str,list[str]]|None=None)->dict:
    rules=load_rules(); discovered=discovered or {}
    servers=[{'id':'local-device','name':'Local Device MCP','transport':'builtin','enabled':True,'tools':[{'name':k,'permission':v.value} for k,v in rules.items()]}]
    for s in custom_servers():
        names=discovered.get(s.get('id'),[])
        perms=s.get('tools') or {}
        servers.append({'id':s.get('id'),'name':s.get('name'),'transport':s.get('transport','stdio'),'enabled':bool(s.get('enabled',True)),'command':s.get('command',''),'args':s.get('args',[]),'url':s.get('url',''),'has_env':bool(s.get('env')),'has_headers':bool(s.get('headers')),'oauth_configured':bool(s.get('oauth',{}).get('client_id')),'managed_integration':s.get('managed_integration',''),'tools':[{'name':n,'permission':perms.get(n,'confirm')} for n in names]})
    return {'servers':servers}
