"""Offline entrypoint migration safety and idempotence."""
import os
from pathlib import Path

import pytest

from mcptoai_linux import container_entrypoint as entry


@pytest.fixture(autouse=True)
def restore_entrypoint_environment():
    """Entrypoint prepares process env; these unit tests must not leak it to pytest."""
    keys = ("MCPTOAI_CONTAINER", "XDG_CONFIG_HOME")
    before = {key: os.environ.get(key) for key in keys}
    try:
        yield
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_copy_preserves_modes_and_never_moves(tmp_path, monkeypatch, capsys):
    legacy = tmp_path / 'old' / 'mcptoai'
    legacy.mkdir(parents=True)
    vault = legacy / 'vault'
    vault.mkdir(mode=0o700)
    secret = vault / 'vault'
    secret.write_text('paired-device')
    secret.chmod(0o600)
    modern = tmp_path / 'data'
    modern.mkdir()
    monkeypatch.setattr(entry, 'LEGACY', legacy)
    monkeypatch.setattr(entry, 'DATA', modern)
    monkeypatch.setattr(entry, '_mounted', lambda p: True)
    entry.prepare()
    assert (modern / 'vault' / 'vault').read_text() == 'paired-device'
    assert (modern / 'vault' / 'vault').stat().st_mode & 0o777 == 0o600
    assert secret.read_text() == 'paired-device'
    assert (modern / entry.MARKER).is_file()
    (modern / 'vault' / 'vault').write_text('newer')
    entry.prepare()
    assert (modern / 'vault' / 'vault').read_text() == 'newer'
    assert capsys.readouterr().err.count('copying legacy profile') == 1


def test_legacy_only_fallback(tmp_path, monkeypatch, capsys):
    legacy = tmp_path / 'old' / 'mcptoai'
    legacy.mkdir(parents=True)
    (legacy / 'identity.pub').write_text('paired')
    monkeypatch.setattr(entry, 'LEGACY', legacy)
    monkeypatch.setattr(entry, 'DATA', tmp_path / 'data')
    monkeypatch.setattr(entry, '_mounted', lambda p: False)
    entry.prepare()
    assert os.environ['MCPTOAI_CONTAINER'] == '0'
    assert os.environ['XDG_CONFIG_HOME'] == str(legacy.parent)
    assert 'only legacy volume mounted' in capsys.readouterr().err


def test_refuses_symlink_in_legacy(tmp_path, monkeypatch):
    legacy = tmp_path / 'old' / 'mcptoai'
    legacy.mkdir(parents=True)
    (legacy / 'vault').symlink_to(tmp_path)
    modern = tmp_path / 'data'
    modern.mkdir()
    monkeypatch.setattr(entry, 'LEGACY', legacy)
    monkeypatch.setattr(entry, 'DATA', modern)
    monkeypatch.setattr(entry, '_mounted', lambda p: True)
    import pytest
    with pytest.raises(RuntimeError, match='symlink'):
        entry.prepare()
    assert not (modern / entry.MARKER).exists()
