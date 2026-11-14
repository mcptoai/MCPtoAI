import errno
import ssl

from mcptoai_core.network import is_connection_reset


def test_connection_reset_and_tls_eof():
    assert is_connection_reset(ConnectionResetError())
    assert is_connection_reset(ssl.SSLEOFError())
    assert is_connection_reset(OSError(errno.EPIPE, 'broken pipe'))
    assert not is_connection_reset(ValueError('ordinary failure'))


def test_exception_chain_and_cycle():
    outer = RuntimeError('outer')
    outer.__cause__ = OSError(errno.ECONNRESET, 'reset')
    assert is_connection_reset(outer)
    cycle = RuntimeError('cycle')
    cycle.__cause__ = cycle
    assert not is_connection_reset(cycle)
