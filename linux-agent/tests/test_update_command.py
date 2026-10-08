import argparse
import sys
from types import SimpleNamespace

import pytest

import mcptoai_linux.cli as cli


def _args(check=False):
    return argparse.Namespace(check=check)


def test_update_check_never_runs_upgrade(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_latest_pypi_version", lambda: "0.2.0")
    monkeypatch.setattr(cli, "_update_available", lambda current, latest: True)
    monkeypatch.setattr(cli, "_detect_update_command", lambda: (_ for _ in ()).throw(AssertionError("must not run updater")))
    cli.cmd_update(_args(check=True))
    out = capsys.readouterr().out
    assert "Update available." in out


def test_update_noop_when_current(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_latest_pypi_version", lambda: cli.__version__)
    monkeypatch.setattr(cli, "_update_available", lambda current, latest: False)
    monkeypatch.setattr(cli, "_detect_update_command", lambda: (_ for _ in ()).throw(AssertionError("must not run updater")))
    cli.cmd_update(_args())
    assert "already up to date" in capsys.readouterr().out


def test_detect_update_command_uses_pipx(monkeypatch):
    monkeypatch.setattr(cli.sys, "executable", "/home/u/.local/share/pipx/venvs/mcptoai/bin/python")
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/pipx" if name == "pipx" else None)
    command, method = cli._detect_update_command("0.2.0")
    assert command == ["/usr/bin/pipx", "runpip", "mcptoai", "install", "--upgrade", "--no-cache-dir", "--index-url", "https://pypi.org/simple", "mcptoai==0.2.0"]
    assert method == "pipx"


def test_detect_update_command_uses_current_python_for_pip(monkeypatch):
    monkeypatch.setattr(cli.sys, "executable", "/srv/venv/bin/python")
    command, method = cli._detect_update_command("0.2.0")
    assert command == ["/srv/venv/bin/python", "-m", "pip", "install", "--upgrade", "--no-cache-dir", "--index-url", "https://pypi.org/simple", "mcptoai==0.2.0"]
    assert method == "pip"


def test_successful_update_restarts_active_service(monkeypatch, capsys):
    import mcptoai_linux.service as service
    monkeypatch.delenv("MCPTOAI_CONTAINER", raising=False)
    monkeypatch.setattr(cli, "_latest_pypi_version", lambda: "0.2.0")
    monkeypatch.setattr(cli, "_update_available", lambda current, latest: True)
    monkeypatch.setattr(cli, "_detect_update_command", lambda latest: (["fake-updater", latest], "pipx"))
    monkeypatch.setattr(service, "is_active", lambda: True)
    calls = []
    monkeypatch.setattr(service, "systemctl", lambda *args, **kwargs: calls.append(args) or SimpleNamespace(returncode=0, stderr=""))

    def fake_run(command, *args, **kwargs):
        if command == ["fake-updater", "0.2.0"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[:2] == [sys.executable, "-c"]:
            return SimpleNamespace(returncode=0, stdout="0.2.0\n", stderr="")
        raise AssertionError(command)
    monkeypatch.setattr("subprocess.run", fake_run)
    cli.cmd_update(_args())
    assert ("restart", service.UNIT_NAME) in calls
    assert "Updated:" in capsys.readouterr().out


def test_failed_update_does_not_restart_service(monkeypatch):
    import mcptoai_linux.service as service
    monkeypatch.delenv("MCPTOAI_CONTAINER", raising=False)
    monkeypatch.setattr(cli, "_latest_pypi_version", lambda: "0.2.0")
    monkeypatch.setattr(cli, "_update_available", lambda current, latest: True)
    monkeypatch.setattr(cli, "_detect_update_command", lambda latest: (["fake-updater", latest], "pipx"))
    monkeypatch.setattr(service, "is_active", lambda: True)
    monkeypatch.setattr(service, "systemctl", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not restart")))
    monkeypatch.setattr("subprocess.run", lambda *a, **k: SimpleNamespace(returncode=2, stdout="", stderr=""))
    with pytest.raises(SystemExit):
        cli.cmd_update(_args())


def test_docker_update_is_rejected(monkeypatch):
    monkeypatch.setenv("MCPTOAI_CONTAINER", "1")
    with pytest.raises(SystemExit) as exc:
        cli.cmd_update(_args())
    assert "Docker" in str(exc.value)


def test_latest_pypi_version_uses_stdlib_urllib(monkeypatch):
    import urllib.request

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self, *args, **kwargs):
            return b'{"info":{"version":"9.9.9"}}'

    seen = {}
    def fake_urlopen(req, timeout=0):
        seen['url'] = req.full_url
        seen['ua'] = req.headers.get('User-agent')
        seen['timeout'] = timeout
        return FakeResponse()

    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)
    assert cli._latest_pypi_version() == '9.9.9'
    assert seen['url'] == 'https://pypi.org/pypi/mcptoai/json'
    assert 'MCPtoAI/' in seen['ua']
    assert seen['timeout'] == 10


def test_update_refuses_false_success_when_version_did_not_change(monkeypatch):
    import mcptoai_linux.service as service
    monkeypatch.delenv("MCPTOAI_CONTAINER", raising=False)
    monkeypatch.setattr(cli, "_latest_pypi_version", lambda: "0.2.0")
    monkeypatch.setattr(cli, "_update_available", lambda current, latest: True)
    monkeypatch.setattr(cli, "_detect_update_command", lambda latest: (["fake-updater", latest], "pip"))
    monkeypatch.setattr(service, "is_active", lambda: True)
    monkeypatch.setattr(service, "systemctl", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not restart")))

    def fake_run(command, *args, **kwargs):
        if command == ["fake-updater", "0.2.0"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[:2] == [sys.executable, "-c"]:
            return SimpleNamespace(returncode=0, stdout="0.1.0\n", stderr="")
        raise AssertionError(command)

    monkeypatch.setattr("subprocess.run", fake_run)
    with pytest.raises(SystemExit) as exc:
        cli.cmd_update(_args())
    assert "did not reach 0.2.0" in str(exc.value)
    assert "service was not restarted" in str(exc.value)
