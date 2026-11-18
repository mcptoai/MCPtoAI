"""Model görsel yeteneklerini keşif verisiyle tutarlı raporla."""
import re

def supports_claude_image(model_id):
    model_id=str(model_id or '').lower()
    return bool(re.search(r'claude[-_](?:3(?:[.-]\d+)?|[4-9](?:[.-]\d+)?)[-_]',model_id) or re.search(r'claude[-_](?:sonnet|opus|haiku)[-_][3-9](?:[.-]\d+)?',model_id))

def modalities_for_model(model_id, reported=None, *, provider=''):
    if provider=='anthropic':
        return ['text','image'] if supports_claude_image(model_id) else ['text']
    return reported
