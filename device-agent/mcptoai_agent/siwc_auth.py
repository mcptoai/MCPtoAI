#!/usr/bin/env python3
"""Device-local ChatGPT OAuth PKCE flow and credential lifecycle."""
import base64
import hashlib
import json
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import jwt

AUTH = 'https://auth.openai.com'
RESOURCE = 'https://api.openai.com/v1'
from .secret_store import get_secret, set_secret, delete_secret
from .credential_lock import credential_lock
SERVICE = 'siwc:account'
SCOPES = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'


def paired_owner():
    """Read device owner from the OS-protected device authentication vault."""
    from .auth import _auth_bundle
    owner = _auth_bundle().get('owner_sub')
    if not isinstance(owner, str) or not owner.strip():
        raise PermissionError('Sign in to your MCPtoAI account before using ChatGPT Preview')
    return owner


def assert_owner(record=None):
    owner = paired_owner()
    if record is None:
        record = vault_get('account')
    if not record or not isinstance(record.get('mcptoai_owner_sub'), str):
        raise PermissionError('ChatGPT account is not linked to this MCPtoAI user; sign out and reconnect')
    if not secrets.compare_digest(owner, record['mcptoai_owner_sub']):
        raise PermissionError('ChatGPT account belongs to another MCPtoAI user; sign out and reconnect')
    return owner


def vault_get(name):
    value = get_secret('siwc:'+name)
    return json.loads(value) if value else None


def vault_put(name, value):
    set_secret('siwc:'+name, json.dumps(value, separators=(',',':')))


def host_id():
    value = vault_get('host_id')
    if value is None:
        value = 'urn:uuid:' + str(uuid.uuid4())
        vault_put('host_id', value)
    return value


def request_json(url, *, data=None, bearer=None):
    """Kimlik bilgilerini hata mesajına dahil etmeden HTTP JSON isteği yap."""
    headers = {'Accept': 'application/json'}
    if bearer:
        headers['Authorization'] = 'Bearer ' + bearer
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        data = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            raw = response.read()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'HTTP {exc.code} from OAuth/API endpoint') from None


def callback_listener(state, timeout=180):
    """Rastgele portta tek callback kabul et; state kontrolü zorunlu."""
    result = {}
    finished = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urllib.parse.urlsplit(self.path)
            qs = urllib.parse.parse_qs(path.query)
            if path.path != '/auth/callback' or not secrets.compare_digest(qs.get('state', [''])[0], state):
                self.send_error(400)
                return
            if finished.is_set():
                self.send_error(409)
                return
            result.update({key: values[0] for key, values in qs.items() if key in ('code', 'state', 'client_id', 'error')})
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'You may close this window and return to MCPtoAI.')
            finished.set()

        def log_message(self, *args):
            pass

    server = HTTPServer(('127.0.0.1', 0), Handler)
    server.timeout = 0.3
    port = server.server_address[1]
    def wait():
        deadline = time.monotonic() + timeout
        try:
            while not finished.is_set() and time.monotonic() < deadline:
                server.handle_request()
        finally:
            server.server_close()
            finished.set()
    return port, result, finished, threading.Thread(target=wait, daemon=True)


USAGE_URL = 'https://chatgpt.com/settings/usage'
SHARING_SCOPE = 'chatgpt.tokens.use.direct'

def assert_plan_sharing(record):
    if SHARING_SCOPE not in record.get('scopes', []):
        raise PermissionError('Plan kullanımı izni verilmedi. ChatGPT ayarları: ' + USAGE_URL)

def verify_identity(id_token, client_id, *, nonce=None, expected_subject=None):
    discovery = request_json(AUTH + '/.well-known/openid-configuration')
    jwks_uri = discovery['jwks_uri']
    if not isinstance(jwks_uri, str) or not jwks_uri.startswith(AUTH + '/'):
        raise RuntimeError('Unexpected JWKS origin')
    signing_key = jwt.PyJWKClient(jwks_uri).get_signing_key_from_jwt(id_token)
    claims = jwt.decode(id_token, signing_key.key, algorithms=['RS256'],
                        audience=client_id, issuer=AUTH,
                        options={'require': ['exp', 'iss', 'aud', 'sub']})
    if nonce is not None and not secrets.compare_digest(claims.get('nonce', ''), nonce):
        raise RuntimeError('OIDC nonce mismatch')
    if expected_subject is not None and not secrets.compare_digest(claims['sub'], expected_subject):
        raise RuntimeError('ChatGPT account identity changed during refresh')
    return claims

def sign_in():
    """Dynamic registration, PKCE ve JWKS doğrulaması yap."""
    owner = paired_owner()
    prior = vault_get('account')
    if prior:
        if status()['reason'] == 'legacy_token':
            raise PermissionError('Bu cihazda eski bir ChatGPT bağlantısı var; önce temizleyin (chatgpt-auth clear-local).')
        assert_owner(prior)
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    port, callback, finished, worker = callback_listener(state)
    redirect = f'http://127.0.0.1:{port}/auth/callback'
    client_id = prior['client_id'] if prior else 'dynamic_agent_client'
    params = {'client_id': client_id, 'ext_agent_host_id': host_id(), 'response_type': 'code',
              'redirect_uri': redirect, 'scope': SCOPES, 'resource': RESOURCE,
              'state': state, 'nonce': nonce, 'code_challenge_method': 'S256', 'code_challenge': challenge}
    if not prior:
        params['agent_name_hint'] = 'MCPtoAI'
    worker.start()
    webbrowser.open(AUTH + '/api/accounts/authorize?' + urllib.parse.urlencode(params))

    try:
        while worker.is_alive():
            worker.join(0.2)
    except KeyboardInterrupt:
        raise RuntimeError('Sign-in cancelled') from None
    if 'error' in callback:
        raise RuntimeError('Authorization declined')
    if 'code' not in callback:
        raise RuntimeError('Authorization timed out or callback rejected')
    issued = callback.get('client_id', client_id)
    if issued == 'dynamic_agent_client' or (prior and issued != prior['client_id']):
        raise RuntimeError('Missing or mismatched issued client ID')
    tokens = request_json(AUTH + '/api/accounts/oauth/token', data={
        'grant_type': 'authorization_code', 'client_id': issued, 'code': callback['code'],
        'code_verifier': verifier, 'redirect_uri': redirect, 'resource': RESOURCE})
    claims = verify_identity(tokens['id_token'], issued, nonce=nonce)
    if prior and claims['sub'] != prior['subject']:
        raise RuntimeError('Different ChatGPT account selected')
    scopes = tokens.get('scope', '').split()
    if SHARING_SCOPE not in scopes:
        raise PermissionError('Plan kullanımı izni verilmedi. ChatGPT ayarları: ' + USAGE_URL)
    if paired_owner() != owner:
        raise PermissionError('MCPtoAI account changed during ChatGPT sign-in')
    record = {'mcptoai_owner_sub': owner, 'client_id': issued, 'subject': claims['sub'], 'access_token': tokens['access_token'],
              'refresh_token': tokens['refresh_token'], 'id_token': tokens['id_token'],
              'scopes': scopes, 'expires_at': time.time() + tokens.get('expires_in', 3600)}
    vault_put('account', record)
    return {'connected':True}


def refresh(expected_refresh_token=None):
    """Serialize refresh and skip a second refresh after another process rotates."""
    with credential_lock():
        record = vault_get('account')
        if not record:
            raise RuntimeError('Sign in first')
        assert_owner(record)
        if record.get('pending_refresh'):
            pending = record['pending_refresh']
            if pending.get('id_token'):
                verify_identity(pending['id_token'], record['client_id'], expected_subject=record['subject'])
            if pending.get('id_token') is None:
                pending.pop('id_token', None)
            record.update(pending)
            record.pop('pending_refresh', None)
            vault_put('account', record)
            assert_plan_sharing(record)
            return record['access_token']
        if expected_refresh_token is not None and record['refresh_token'] != expected_refresh_token:
            if record['expires_at'] > time.time() + 120:
                return record['access_token']
        tokens = request_json(AUTH + '/api/accounts/oauth/token', data={
            'grant_type': 'refresh_token', 'client_id': record['client_id'],
            'refresh_token': record['refresh_token'], 'resource': RESOURCE})
        # Persist rotated credentials before network-based identity verification.
        # A failed JWKS request must not discard the only valid successor refresh token.
        pending = {'access_token': tokens['access_token'],
                   'refresh_token': tokens['refresh_token'],
                   'id_token': tokens.get('id_token'),
                   'scopes': tokens.get('scope', ' '.join(record['scopes'])).split(),
                   'expires_at': time.time() + tokens.get('expires_in', 3600)}
        record['pending_refresh'] = pending
        vault_put('account', record)
        if pending['id_token']:
            verify_identity(pending['id_token'], record['client_id'], expected_subject=record['subject'])
        if pending.get('id_token') is None:
            pending.pop('id_token', None)  # Keep the last verified identity token.
        record.update(pending)
        record.pop('pending_refresh', None)
        vault_put('account', record)
        assert_plan_sharing(record)
    return record['access_token']


def access_token():
    record=vault_get('account')
    if not record:
        raise RuntimeError('ChatGPT sign-in required')
    assert_owner(record)
    if record.get('pending_refresh'):
        return refresh(expected_refresh_token=record['refresh_token'])
    assert_plan_sharing(record)
    if record['expires_at'] < time.time()+120:
        return refresh(expected_refresh_token=record['refresh_token'])
    return record['access_token']


def status():
    """Read-only connection state; never return credentials or mutate the vault."""
    record = vault_get('account')
    if not record:
        return {'connected': False, 'linked': False, 'sharing': False, 'reason': None, 'expires_at': None}
    bound = record.get('mcptoai_owner_sub')
    if not isinstance(bound, str) or not bound.strip():
        reason = 'legacy_token'
    else:
        try:
            owner = paired_owner()
        except PermissionError:
            owner = None
        reason = None if owner and secrets.compare_digest(owner, bound) else 'owner_mismatch'
    linked = reason is None
    sharing = linked and SHARING_SCOPE in record.get('scopes', []) and not record.get('pending_refresh')
    if linked and not sharing:
        reason = 'refresh_pending' if record.get('pending_refresh') else 'plan_permission_missing'
    return {'connected': linked, 'linked': linked, 'sharing': sharing, 'reason': reason,
            'expires_at': int(record['expires_at']) if linked and 'expires_at' in record else None}


def cleanup_unlinked():
    """Explicitly user-approved cleanup. Never expose or use the token for inference."""
    with credential_lock():
        record = vault_get('account')
        if not record:
            return {'disconnected': True, 'revoked': True}
        state = status()
        if state['linked']:
            raise PermissionError('Use normal sign out for a linked ChatGPT account')
        revoked = False
        try:
            token = record.get('refresh_token')
            client_id = record.get('client_id')
            if token and client_id:
                discovery = request_json(AUTH + '/.well-known/openid-configuration')
                endpoint = discovery.get('revocation_endpoint', '')
                if not isinstance(endpoint, str) or not endpoint.startswith(AUTH + '/'):
                    raise RuntimeError('Unexpected revocation endpoint')
                request_json(endpoint, data={'token': token, 'token_type_hint': 'refresh_token',
                                             'client_id': client_id})
                revoked = True
        except Exception:
            pass  # Best-effort only; local removal is mandatory even if offline.
        finally:
            delete_secret('siwc:account')
        return {'disconnected': True, 'revoked': revoked}


def clear_local():
    """Explicitly approved removal of an unlinked legacy SIWC record only."""
    return cleanup_unlinked()


def list_models():
    data=request_json(RESOURCE+'/models',bearer=access_token())
    return [{'id':m['slug'],'name':m.get('display_name',m['slug'])} for m in data.get('models',data.get('data',[])) if m.get('visibility')=='list' and isinstance(m.get('slug'),str)]





def sign_out():
    record=vault_get('account')
    if not record:
        return {'disconnected':True,'revoked':True}
    if status()['reason'] == 'legacy_token':
        raise PermissionError('Bu cihazda eski bir ChatGPT bağlantısı var; önce temizleyin (chatgpt-auth clear-local).')
    assert_owner(record)
    revoked=False
    try:
        discovery=request_json(AUTH+'/.well-known/openid-configuration')
        endpoint=discovery.get('revocation_endpoint','')
        if not endpoint.startswith(AUTH+'/'):
            raise RuntimeError('Unexpected revocation endpoint')
        request_json(endpoint,data={'token':record['refresh_token'],
                                    'token_type_hint':'refresh_token','client_id':record['client_id']})
        revoked=True
    except (RuntimeError,KeyError):
        pass
    finally:
        delete_secret('siwc:account')
    return {'disconnected':True,'revoked':revoked}
