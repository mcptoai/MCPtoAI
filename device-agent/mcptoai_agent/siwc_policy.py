"""SIWC web authorization: independent device opt-in and server kill switch.

The relay overwrites browser identity claims with its authenticated WS user.
No client-provided identity may authorize a plan call.
"""
import secrets
import httpx
from .config import local_permission, PRODUCTION_SERVER_URL

WEB_DENIAL = 'ChatGPT web plan usage is disabled or not authorized'

def remote_web_enabled() -> bool:
    """Read the server switch on every web invocation. Any error denies."""
    try:
        response=httpx.get(PRODUCTION_SERVER_URL+'/api/siwc/web-policy/',timeout=3.0,
                           headers={'Cache-Control':'no-cache'})
        response.raise_for_status()
        payload=response.json()
        return (isinstance(payload,dict) and payload.get('schema') == 1 and
                payload.get('web_siwc_enabled') is True)
    except (httpx.HTTPError,ValueError,TypeError):
        return False

def authorize_web_turn(identity, *, interactive: bool, fresh_message_id: bool,
                       replay: bool = False, job_or_sampling: bool = False) -> None:
    # Do not read SIWC credentials until local and remote gates both pass.
    if not local_permission('siwc_enabled') or not local_permission('siwc_web_enabled'):
        raise PermissionError(WEB_DENIAL)
    if not remote_web_enabled():
        raise PermissionError(WEB_DENIAL)
    if not interactive or not fresh_message_id or replay or job_or_sampling:
        raise PermissionError('Only new, user-initiated web chat turns may use ChatGPT plan')
    if not isinstance(identity,dict) or identity.get('source') != 'authenticated_relay':
        raise PermissionError('Verified relay identity missing')
    from .siwc_auth import paired_owner, assert_owner
    from .auth import _auth_bundle
    bundle=_auth_bundle()
    device_id=bundle.get('device_id')
    if not isinstance(device_id,str) or not device_id or identity.get('device_id') != device_id:
        raise PermissionError('Web relay device does not match paired device')
    owner=paired_owner()
    subjects=identity.get('subjects')
    if (not isinstance(subjects,list) or len(subjects) != 1
            or not isinstance(subjects[0],str) or not subjects[0] or len(subjects[0]) >= 512):
        raise PermissionError('Exactly one verified relay account identity is required')
    if not secrets.compare_digest(owner,subjects[0]):
        raise PermissionError('Web relay user does not match paired device owner')
    linked_owner=assert_owner()
    if not secrets.compare_digest(owner,linked_owner):
        raise PermissionError('Web relay user does not match ChatGPT connection owner')
