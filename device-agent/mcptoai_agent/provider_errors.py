"""Safe, human-readable provider failures. Raw exceptions belong in device logs only."""
import re
from .provider_registry import registry

_STATUS = {
    401: 'API key invalid (401)',
    403: 'Access denied (403)',
    404: 'Model or endpoint not found (404)',
    429: 'Rate limit reached (429)',
    500: 'Provider server error (5xx)',
}

def friendly_provider_error(provider_id, error, custom=None):
    info = registry(custom).get(provider_id, {})
    name = str(info.get('name') or 'AI provider')[:80]
    # Never put raw exception text, URLs, internal IDs or response JSON on screen.
    siwc = _siwc_reason(error)
    if siwc:
        return f'{name}: {siwc}'
    status = getattr(error, 'status_code', None)
    if not isinstance(status, int):
        match = re.search(r'(?<!\d)(401|403|404|429|5\d\d)(?!\d)', str(error))
        status = int(match.group(1)) if match else None
    if status in _STATUS:
        reason = _STATUS[status]
    elif isinstance(status, int) and 500 <= status <= 599:
        reason = _STATUS[500]
    else:
        reason = 'Connection or model request failed'
    return f'{name}: {reason}'


def _siwc_reason(error):
    """ChatGPT planı yanıtları HTTP 200 ile gelir; asıl hata akıştaki olaydadır."""
    from .providers.siwc_responses import SiwcResponseError
    if not isinstance(error, SiwcResponseError):
        return None
    if error.is_usage_limit:
        return 'ChatGPT plan usage limit reached. Check your limits with "Manage usage".'
    if error.kind == 'incomplete':
        if error.code == 'max_output_tokens':
            return 'Response was cut off (output limit reached)'
        if error.code == 'content_filter':
            return 'Response was stopped by a safety filter'
        return 'Response was incomplete' + (f' ({error.code})' if error.code else '')
    return 'Model request failed' + (f' ({error.code})' if error.code else '')
