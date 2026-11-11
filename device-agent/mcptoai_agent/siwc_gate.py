"""SIWC local Desktop or explicitly authorized interactive web turns."""
from .config import local_permission

WEB_DENIAL='ChatGPT web plan usage is disabled or not authorized'

def enforce(*, origin: str, user_initiated: bool = False, web_authorized: bool = False) -> None:
    if origin == 'web-relay':
        if not user_initiated or not web_authorized:
            raise PermissionError(WEB_DENIAL)
        # Authorization was checked before provider creation. No alternate path.
        return
    if origin != 'desktop-local':
        raise PermissionError(WEB_DENIAL)
    if not user_initiated:
        raise PermissionError('ChatGPT plan requires a user-initiated desktop turn')
    if not local_permission('siwc_enabled'):
        raise PermissionError('ChatGPT Preview is off. Enable it in Desktop settings.')
    from .siwc_auth import assert_owner
    assert_owner()
