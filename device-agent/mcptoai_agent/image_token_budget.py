"""Estimate *visual* token use without charging base64 bytes as text tokens.

Heuristics are for budgeting only, not provider billing. Provider APIs remain
responsible for actual token accounting. Unparseable images use a fixed and
conservative per-image allowance, not an unbounded encoded-string length.
"""
from __future__ import annotations

import base64
import io
import math
import re

UNKNOWN_IMAGE_TOKENS = 8192
MAX_IMAGE_PIXELS = 100_000_000
_IMAGE_URL = re.compile(r'^data:image/(?:jpeg|png|webp|gif);base64,([A-Za-z0-9+/]+={0,2})$')


def image_dimensions(image: dict) -> tuple[int, int] | None:
    if not isinstance(image, dict):
        return None
    value = image.get('data_url')
    if not isinstance(value, str) or len(value) > 16_000_000:
        return None
    match = _IMAGE_URL.fullmatch(value)
    if not match:
        return None
    try:
        from PIL import Image
        raw = base64.b64decode(match.group(1), validate=True)
        with Image.open(io.BytesIO(raw)) as img:
            w, h = img.size
        if type(w) is int and type(h) is int and 0 < w*h <= MAX_IMAGE_PIXELS and w > 0 and h > 0:
            return w, h
    except (ValueError, OSError, TypeError, ImportError):
        pass
    return None


def visual_tokens(image: dict, provider: str = '') -> int:
    dimensions = image_dimensions(image)
    if dimensions is None:
        return UNKNOWN_IMAGE_TOKENS
    w, h = dimensions
    provider = str(provider).lower()
    if provider == 'anthropic':
        # Claude vision: ceil(width/28) * ceil(height/28) visual patches.
        # Standard-tier safety bound 1,568 visual tokens; high-tier devices
        # may accept more, but estimating conservatively here cannot overrun.
        max_patches = 4784
        max_edge = 2576
        scale = min(1., max_edge / max(w, h), math.sqrt(max_patches * 784 / (w*h)))
        return max(1, math.ceil(w*scale/28) * math.ceil(h*scale/28))
    if provider == 'openai':
        # Conservative legacy high-detail tiled estimator: 85 base + 170 per
        # 512x512 tile after longest-edge 2048 and shortest-edge 768 scaling.
        scale = min(1., 2048 / max(w, h))
        sw, sh = w*scale, h*scale
        if min(sw, sh) > 768:
            shrink = 768 / min(sw, sh)
            sw *= shrink; sh *= shrink
        return 85 + 170 * math.ceil(sw/512) * math.ceil(sh/512)
    return UNKNOWN_IMAGE_TOKENS
