import sys
import warnings
from mcptoai_agent.packaged_warnings import configure_packaged_warnings


def test_source_environment_preserves_upstream_warning(monkeypatch):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter('always')
        configure_packaged_warnings()
        warnings.warn_explicit('authlib.jose module is deprecated, please use joserfc instead.',
                               DeprecationWarning, 'fastmcp/server/auth/providers/jwt.py', 10,
                               module='fastmcp.server.auth.providers.jwt')
        assert len(records) == 1


def test_frozen_filters_only_exact_upstream_warning(monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter('always')
        configure_packaged_warnings()
        for message, module in [
            ('authlib.jose module is deprecated, please use joserfc instead.', 'fastmcp.server.auth.providers.jwt'),
            ('authlib.jose module is deprecated, please use joserfc instead.', 'mcptoai_agent.other'),
            ('another deprecation', 'fastmcp.server.auth.providers.jwt'),
        ]:
            warnings.warn_explicit(message, DeprecationWarning, 'test.py', 1, module=module)
        assert len(records) == 2
