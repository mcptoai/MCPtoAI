"""Ağ dayanıklılığı: bazı ağ yollarında sıfırlanan TLS bağlantılarına karşı klasik anahtar grubuna yedek.

OpenSSL 3.5+ varsayılan olarak post-kuantum hibrit anahtar paylaşımı (X25519MLKEM768) önerir; bu, ClientHello'yu yaklaşık üç
kat büyütür. Bazı ağ cihazları ya da uçlar bu büyük ClientHello'yu bağlantıyı SIFIRLAYARAK reddeder (ör. bir Macn yalnızca
api.anthropic.com'a gidenler: curl ve klasik gruplu istemciler çalışır, OpenSSL tabanlı istemci 'Connection reset by peer' alır).
Sonuç: sağlayıcının model listesi hiç gelmez.

Çözüm bağlantı BAŞINA ve yalnızca gerektiğinde: bağlantı aşamasında sıfırlanan bir sunucu için istek, X25519 ile sınırlı bir TLS
bağlamıyla bir kez yeniden denenir ve sunucu süreç boyunca hatırlanır. Böylece post-kuantum koruma çalışan her yerde korunur,
yalnızca sıfırlanan sunucularda klasik gruba düşülür. Bağlantı aşamasında olduğu için istek henüz gönderilmemiştir: yeniden
deneme güvenlidir (POST dahil). Vekil (HTTP(S)_PROXY) ortam değişkenleri bozulmaz: taşıma 'mounts' ile bağlanır."""
from __future__ import annotations

import errno
import logging
import ssl
import sys

logger = logging.getLogger("mcptoai.net")

# Sıfırlanan ve klasik gruba düşürülen sunucular (süreç boyunca hatırlanır).
_FALLBACK_HOSTS: set[str] = set()
_CLASSES: dict[str, type] = {}
_RESET_ERRNOS = {errno.ECONNRESET, errno.EPIPE}


def fallback_hosts() -> frozenset[str]:
    return frozenset(_FALLBACK_HOSTS)


def forget_fallback_hosts() -> None:
    _FALLBACK_HOSTS.clear()


def classical_context(context: ssl.SSLContext) -> ssl.SSLContext:
    """Verilen bağlamı yalnızca X25519 öneren hâle getirir (post-kuantum hibrit grup önerilmez).

    httpx2'nin varsayılanı bir truststore.SSLContext sarmalayıcısıdır (sistem sertifika deposu için) ve set_ecdh_curve çağrısını
    YUTAR: ClientHello 1522 bayt kalır. ClientHello'yu gerçekten üreten iç bağlam '_ctx' özniteliğindedir; kısıtlama oraya
    uygulanır (sistem sertifika deposu ve kurumsal kök sertifikalar korunur). Mac gerçek Anthropic bağlantısıyla doğrulandı."""
    inner = getattr(context, "_ctx", None)
    target = inner if isinstance(inner, ssl.SSLContext) else context
    try:
        target.set_ecdh_curve("X25519")
    except (AttributeError, ValueError, ssl.SSLError):  # çok eski/farklı OpenSSL: bağlam olduğu gibi kalır
        logger.debug("TLS grupları kısıtlanamadı")
    return context


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


def _transport_class(h):
    """h: SDK'nın kullandığı httpx modülü ('httpx' ya da 'httpx2'); taşıma sınıfı ona göre türetilir."""
    if h.__name__ in _CLASSES:
        return _CLASSES[h.__name__]

    class ResilientAsyncTransport(h.AsyncBaseTransport):
        def __init__(self, context_factory=None) -> None:
            self._factory = context_factory or h.create_ssl_context
            self._primary = h.AsyncHTTPTransport(verify=self._factory())
            self._classical = None

        def _fallback(self):
            if self._classical is None:
                self._classical = h.AsyncHTTPTransport(verify=classical_context(self._factory()))
            return self._classical

        async def handle_async_request(self, request):
            host = request.url.host
            if host in _FALLBACK_HOSTS:
                return await self._fallback().handle_async_request(request)
            try:
                return await self._primary.handle_async_request(request)
            except h.ConnectError as exc:
                # Yalnızca BAĞLANTI aşamasında ve yalnızca sıfırlamada: istek gönderilmediği için yeniden deneme güvenlidir.
                if not is_connection_reset(exc):
                    raise
                _FALLBACK_HOSTS.add(host)
                logger.warning("%s bağlantıyı sıfırladı; klasik TLS anahtar grubuyla (X25519) yeniden deneniyor", host)
                return await self._fallback().handle_async_request(request)

        async def aclose(self) -> None:
            await self._primary.aclose()
            if self._classical is not None:
                await self._classical.aclose()

    _CLASSES[h.__name__] = ResilientAsyncTransport
    return ResilientAsyncTransport


def resilient_http_client(default_client_cls, context_factory=None):
    """SDK'nın DefaultAsyncHttpxClient'ından dayanıklı bir istemci üretir; bir sorun olursa None (SDK varsayılanı) döner."""
    try:
        base = next(c for c in default_client_cls.__mro__ if c.__name__ == "AsyncClient")
        h = sys.modules[base.__module__.split(".")[0]]
        return default_client_cls(mounts={"all://": _transport_class(h)(context_factory)})
    except Exception:  # dayanıklılık eklentisi asla sağlayıcıyı bozmamalı
        logger.warning("Dayanıklı HTTP istemcisi kurulamadı; SDK varsayılanı kullanılıyor", exc_info=True)
        return None
