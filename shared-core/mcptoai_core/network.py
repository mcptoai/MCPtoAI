"""Platform-neutral TLS connection-reset classification for retry decisions."""
from __future__ import annotations

import errno
import ssl

_RESET_ERRNOS = {errno.ECONNRESET, errno.EPIPE}


def is_connection_reset(exc: BaseException) -> bool:
    """Bağlantı el sıkışması sırasında karşı tarafça/ağ cihazınca kesildi mi? (neden zincirine bakar)"""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (ConnectionResetError, ssl.SSLEOFError)):
            return True
        if isinstance(current, OSError) and current.errno in _RESET_ERRNOS:
            return True
        current = current.__cause__ or current.__context__
    return False
