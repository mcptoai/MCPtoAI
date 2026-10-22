"""Ağ dayanıklılığı: bağlantı sıfırlanırsa o sunucu için klasik TLS grubuna (X25519) düşülür; vekil ayarları bozulmaz."""
import asyncio
import datetime
import errno
import os
import socket
import ssl
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx2

from mcptoai_agent import net
from mcptoai_agent.providers.anthropic_provider import AnthropicProvider
from mcptoai_agent.providers.evren_provider import EvrenProvider
from mcptoai_agent.providers.openai_provider import OpenAIProvider

Transport = net._transport_class(httpx2)


def reset_error(message='reset'):
    """httpcore'un yaptığı gibi: bağlantı hatası, nedeni ConnectionResetError."""
    exc = httpx2.ConnectError(message)
    exc.__cause__ = ConnectionResetError(errno.ECONNRESET, 'Connection reset by peer')
    return exc


class Fake(httpx2.AsyncBaseTransport):
    def __init__(self, name, error=None):
        self.name, self.error, self.calls, self.bodies = name, error, 0, []

    async def handle_async_request(self, request):
        self.calls += 1
        self.bodies.append(await request.aread())
        if self.error is not None:
            raise self.error
        return httpx2.Response(200, content=self.name.encode())


class NetCase(unittest.TestCase):
    def setUp(self):
        net.forget_fallback_hosts()
        self.addCleanup(net.forget_fallback_hosts)


class ResetDetectionTests(NetCase):
    def test_resets_are_recognised_through_the_cause_chain(self):
        wrapped = RuntimeError('sarmalanmış')
        wrapped.__cause__ = OSError(errno.ECONNRESET, 'reset')
        for exc in (ConnectionResetError(), OSError(errno.ECONNRESET, 'x'), OSError(errno.EPIPE, 'x'), ssl.SSLEOFError(), reset_error(), wrapped):
            self.assertTrue(net.is_connection_reset(exc), repr(exc))

    def test_other_errors_are_not_resets(self):
        for exc in (OSError(errno.ENOENT, 'x'), ValueError('x'), socket.gaierror(-2, 'Name or service not known'), TimeoutError(),
                    httpx2.ConnectError('çözülemedi'), ssl.SSLCertVerificationError()):
            self.assertFalse(net.is_connection_reset(exc), repr(exc))

    def test_a_cause_cycle_does_not_loop_forever(self):
        a, b = RuntimeError('a'), RuntimeError('b')
        a.__cause__, b.__cause__ = b, a
        self.assertFalse(net.is_connection_reset(a))

    def test_classical_context_tolerates_unsupported_objects(self):
        self.assertIsInstance(net.classical_context(ssl.create_default_context()), ssl.SSLContext)
        net.classical_context(object())  # set_ecdh_curve yok: hata vermemeli


class TransportTests(NetCase):
    def make(self, primary, classical):
        transport = Transport()
        transport._primary, transport._classical = primary, classical
        return transport

    def request(self, url='https://api.example.test/v1', body=None):
        return httpx2.Request('POST', url, content=body)

    def test_a_healthy_connection_never_touches_the_fallback(self):
        primary, classical = Fake('primary'), Fake('classical')
        response = asyncio.run(self.make(primary, classical).handle_async_request(self.request()))
        self.assertEqual(response.content, b'primary') if hasattr(response, 'content') else None
        self.assertEqual((primary.calls, classical.calls), (1, 0))
        self.assertEqual(net.fallback_hosts(), frozenset())

    def test_a_reset_falls_back_once_and_the_host_is_remembered(self):
        primary, classical = Fake('primary', reset_error()), Fake('classical')
        transport = self.make(primary, classical)

        async def run():
            first = await transport.handle_async_request(self.request(body=b'payload-1'))
            await first.aread()
            second = await transport.handle_async_request(self.request(body=b'payload-2'))
            await second.aread()
            return first, second
        asyncio.run(run())
        self.assertEqual(primary.calls, 1, 'sunucu hatırlanınca birincil bağlantı bir daha denenmez')
        self.assertEqual(classical.calls, 2)
        self.assertEqual(classical.bodies, [b'payload-1', b'payload-2'], 'istek gövdesi yeniden denemede aynen gider')
        self.assertEqual(net.fallback_hosts(), frozenset({'api.example.test'}))

    def test_other_hosts_keep_using_the_primary_connection(self):
        primary, classical = Fake('primary', reset_error()), Fake('classical')
        transport = self.make(primary, classical)
        asyncio.run(transport.handle_async_request(self.request('https://a.example.test/')))
        primary.error = None
        asyncio.run(transport.handle_async_request(self.request('https://b.example.test/')))
        self.assertEqual((primary.calls, classical.calls), (2, 1))
        self.assertEqual(net.fallback_hosts(), frozenset({'a.example.test'}))

    def test_only_connect_phase_resets_are_retried(self):
        # İstek gönderildikten sonraki hatalar (okuma/zaman aşımı) ve sıfırlama olmayan bağlantı hataları yeniden denenmez.
        read_reset = httpx2.ReadError('reset')   # sıfırlama nedenli ama OKUMA aşamasında: istek gitmiş olabilir
        read_reset.__cause__ = ConnectionResetError(errno.ECONNRESET, 'Connection reset by peer')
        cases = {'çözülemeyen ad': httpx2.ConnectError('dns'), 'okuma hatası (sıfırlama nedenli)': read_reset,
                 'bağlantı zaman aşımı': httpx2.ConnectTimeout('zaman aşımı'), 'okuma zaman aşımı': httpx2.ReadTimeout('x')}
        for label, error in cases.items():
            with self.subTest(label):
                primary, classical = Fake('primary', error), Fake('classical')
                with self.assertRaises(type(error)):
                    asyncio.run(self.make(primary, classical).handle_async_request(self.request()))
                self.assertEqual(classical.calls, 0)
                self.assertEqual(net.fallback_hosts(), frozenset())

    def test_a_failing_fallback_propagates_its_own_error(self):
        primary = Fake('primary', reset_error())
        classical = Fake('classical', httpx2.ConnectError('klasik de olmadı'))
        with self.assertRaisesRegex(httpx2.ConnectError, 'klasik de olmadı'):
            asyncio.run(self.make(primary, classical).handle_async_request(self.request()))


class FallbackContextTests(NetCase):
    def test_the_fallback_connection_really_uses_a_restricted_context(self):
        # Gerçek TLS testi yalnızca post-kuantum gönderen OpenSSL'de çalışır; burada bağlamın kısıtlandığı her yerde doğrulanır.
        class Context:
            def __init__(self):
                self.curve = None

            def set_ecdh_curve(self, curve):
                self.curve = curve
        recorded = []

        class Recorder(httpx2.AsyncHTTPTransport):
            def __init__(self, verify=True, **kwargs):
                recorded.append(verify)
                super().__init__()
        with patch.object(httpx2, 'AsyncHTTPTransport', Recorder):
            transport = Transport(context_factory=Context)
            transport._fallback()
        primary, classical = recorded
        self.assertIsNone(primary.curve, 'birincil bağlantı varsayılan grupları kullanır (post-kuantum korunur)')
        self.assertEqual(classical.curve, 'X25519')
        self.assertIsNot(primary, classical)


class WrapperContextTests(NetCase):
    def test_a_wrapper_that_swallows_set_ecdh_curve_is_restricted_through_its_inner_context(self):
        class Inner(ssl.SSLContext):
            curve = None

            def set_ecdh_curve(self, curve):
                self.curve = curve

        class Wrapper:  # truststore.SSLContext gibi: çağrıyı yutar, gerçek bağlam _ctx'te
            _ctx = Inner(ssl.PROTOCOL_TLS_CLIENT)

            def set_ecdh_curve(self, curve):
                raise AssertionError('sarmalayıcıya uygulanan kısıtlama ClientHello\'ya ulaşmaz')
        wrapper = Wrapper()
        self.assertIs(net.classical_context(wrapper), wrapper)
        self.assertEqual(wrapper._ctx.curve, 'X25519')

    def test_the_real_default_httpx2_context_sends_a_smaller_client_hello_when_restricted(self):
        # Bu test bir hatayı yakalamak için eklendi: sarmalayıcı bağlama uygulanan kısıtlama ClientHello'yu değiştirmiyordu ve
        # yedek, gerçek Anthropic bağlantısında işe yaramadı. Gerçek varsayılan bağlamın boyutu ölçülür (post-kuantum
        # göndermeyen OpenSSL'de ölçülecek fark yoktur).
        default = hello_size(httpx2.create_ssl_context())
        restricted = hello_size(net.classical_context(httpx2.create_ssl_context()))
        if default <= restricted + 100:
            if default > 800:
                self.fail(f'kısıtlama ClientHello\'yu küçültmedi ({default} -> {restricted} bayt)')
            self.skipTest(f'bu OpenSSL post-kuantum hibrit grup göndermiyor ({default} bayt)')
        self.assertLess(restricted, default - 100)


class WiringTests(NetCase):
    def resilient_in(self, provider):
        client = provider.client._client
        return any(isinstance(t, Transport) for t in client._mounts.values())

    def test_every_provider_uses_the_resilient_transport(self):
        for provider in (AnthropicProvider('k', 'm'), OpenAIProvider('k', 'm'), OpenAIProvider('k', 'm', 'http://localhost:11434/v1'),
                         EvrenProvider('k', 'm')):
            self.assertTrue(self.resilient_in(provider), type(provider).__name__)

    def test_environment_proxies_are_not_bypassed(self):
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://127.0.0.1:9', 'https_proxy': 'http://127.0.0.1:9'}):
            provider = AnthropicProvider('k', 'm')
            transport = provider.client._client._transport_for_url(httpx2.URL('https://api.anthropic.com/v1/models'))
            self.assertNotIsInstance(transport, Transport, 'vekil ayarlıyken istek vekile gitmeli')

    def test_a_broken_helper_never_breaks_the_provider(self):
        self.assertIsNone(net.resilient_http_client(object))  # SDK varsayılanına düşer
        with patch('mcptoai_agent.providers.anthropic_provider.resilient_http_client', return_value=None):
            self.assertIsNotNone(AnthropicProvider('k', 'm').client)


def make_certificate(directory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), critical=False).sign(key, hashes.SHA256()))
    cert_path, key_path = Path(directory) / 'cert.pem', Path(directory) / 'key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return cert_path, key_path


def hello_size(context):
    """Bu OpenSSL'in gönderdiği TLS ClientHello kaydının bayt boyutu."""
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(1)
    captured = []

    def accept():
        conn, _ = server.accept()
        header = conn.recv(5)
        length = int.from_bytes(header[3:5], 'big')
        data = b''
        while len(data) < length:
            data += conn.recv(length - len(data))
        captured.append(5 + length)
        conn.close()
    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    client = socket.create_connection(('127.0.0.1', server.getsockname()[1]))
    try:
        context.wrap_socket(client, server_hostname='localhost')
    except (ssl.SSLError, OSError):
        pass
    thread.join(5)
    server.close()
    return captured[0]


class Middlebox:
    """Büyük ClientHello'yu RST ile sıfırlayan, diğerlerini sunucuya ileten ağ cihazı benzetimi."""

    def __init__(self, backend_port, limit):
        self.backend_port, self.limit, self.resets, self.forwarded = backend_port, limit, 0, 0

    async def handle(self, reader, writer):
        header = await reader.readexactly(5)
        length = int.from_bytes(header[3:5], 'big')
        body = await reader.readexactly(length)
        if 5 + length > self.limit:
            self.resets += 1
            writer.get_extra_info('socket').setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
            writer.transport.abort()
            return
        self.forwarded += 1
        upstream_reader, upstream_writer = await asyncio.open_connection('127.0.0.1', self.backend_port)
        upstream_writer.write(header + body)

        async def pipe(src, dst):
            try:
                while data := await src.read(65536):
                    dst.write(data)
                    await dst.drain()
            except (ConnectionError, OSError):
                pass
            finally:
                dst.close()
        await asyncio.gather(pipe(reader, upstream_writer), pipe(upstream_reader, writer))


class MiddleboxIntegrationTests(NetCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cert, self.key = make_certificate(self.tmp.name)
        self.factory = lambda: ssl.create_default_context(cafile=str(self.cert))
        self.default_size = hello_size(self.factory())
        self.classical_size = hello_size(net.classical_context(self.factory()))
        if self.default_size <= self.classical_size + 100:
            self.skipTest(f'bu OpenSSL post-kuantum hibrit grup göndermiyor (ClientHello {self.default_size} ~ {self.classical_size} bayt); '
                          'sıfırlama benzetimi yapılamaz')
        self.limit = (self.default_size + self.classical_size) // 2

    async def serve(self):
        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ctx.load_cert_chain(self.cert, self.key)

        async def backend(reader, writer):
            await reader.readuntil(b'\r\n\r\n')
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nhello')
            await writer.drain()
            writer.close()
        backend_server = await asyncio.start_server(backend, '127.0.0.1', 0, ssl=server_ctx)
        box = Middlebox(backend_server.sockets[0].getsockname()[1], self.limit)
        box_server = await asyncio.start_server(box.handle, '127.0.0.1', 0)
        return backend_server, box_server, box

    def test_the_benchmark_really_resets_a_default_client(self):
        async def run():
            backend_server, box_server, box = await self.serve()
            port = box_server.sockets[0].getsockname()[1]
            try:
                async with httpx2.AsyncClient(verify=self.factory()) as client:
                    with self.assertRaises(httpx2.ConnectError) as caught:
                        await client.get(f'https://localhost:{port}/')
                self.assertTrue(net.is_connection_reset(caught.exception))
                self.assertGreaterEqual(box.resets, 1)
            finally:
                backend_server.close(); box_server.close()
        asyncio.run(run())

    def test_the_resilient_transport_gets_through_and_remembers_the_host(self):
        async def run():
            backend_server, box_server, box = await self.serve()
            port = box_server.sockets[0].getsockname()[1]
            try:
                async with httpx2.AsyncClient(mounts={'all://': Transport(self.factory)}) as client:
                    first = await client.get(f'https://localhost:{port}/')
                    self.assertEqual((first.status_code, first.text), (200, 'hello'))
                    self.assertEqual(box.resets, 1, 'yalnızca ilk deneme sıfırlanır')
                    second = await client.get(f'https://localhost:{port}/')
                    self.assertEqual(second.text, 'hello')
                    self.assertEqual(box.resets, 1, 'hatırlanan sunucuya doğrudan klasik grupla gidilir')
                self.assertIn('localhost', net.fallback_hosts())
            finally:
                backend_server.close(); box_server.close()
        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
