"""systemd lifecycle regression: user-only, restart and persistence on upgrade."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcptoai_linux import service


def test_unit_is_user_service_with_failure_restart():
    unit=service.unit_text('/home/test/.local/bin/mcptoai')
    assert 'ExecStart=/home/test/.local/bin/mcptoai connect' in unit
    assert 'Restart=on-failure' in unit
    assert 'RestartSec=5' in unit
    assert 'NoNewPrivileges=yes' in unit
    assert 'WantedBy=default.target' in unit
    assert 'User=root' not in unit
    assert 'ExecStartPre=' not in unit


def test_install_preserves_profile_and_enables_user_unit(tmp_path,monkeypatch):
    home=tmp_path/'user';home.mkdir()
    monkeypatch.setenv('XDG_CONFIG_HOME',str(home))
    monkeypatch.setattr(service.os,'geteuid',lambda:1000)
    monkeypatch.setattr(service,'executable',lambda:'/opt/mcptoai/bin/mcptoai')
    monkeypatch.setattr(service,'linger_enabled',lambda:True)
    calls=[]
    monkeypatch.setattr(service,'systemctl',lambda *args,**kwargs:calls.append(args) or SimpleNamespace(returncode=0,stderr=''))
    data=home/'mcptoai';data.mkdir()
    marker=data/'identity.pub';marker.write_text('preserve identity')
    activity=data/'activity-v1.sqlite3';activity.write_bytes(b'preserve activity')
    assert service.install()==[]
    assert service.unit_path().exists()
    assert calls==[('daemon-reload',),('enable','--now',service.UNIT_NAME)]
    assert marker.read_text()=='preserve identity'
    assert activity.read_bytes()==b'preserve activity'
    calls.clear()
    assert service.install()==[]  # reinstall after upgrade is idempotent
    assert calls==[('daemon-reload',),('enable','--now',service.UNIT_NAME)]
    assert marker.read_text()=='preserve identity'
    assert activity.read_bytes()==b'preserve activity'
    service.uninstall()
    assert not service.unit_path().exists()
    assert marker.exists() and activity.exists()  # uninstall never erases user data


def test_install_rejects_root_and_does_not_write(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    monkeypatch.setattr(service.os,'geteuid',lambda:0)
    with pytest.raises(SystemExit,match='root'):
        service.install()
    assert not service.unit_path().exists()


def test_linger_warning_when_disabled(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    monkeypatch.setenv('USER','test-user')
    monkeypatch.setattr(service.os,'geteuid',lambda:1000)
    monkeypatch.setattr(service,'executable',lambda:'/opt/mcptoai/bin/mcptoai')
    monkeypatch.setattr(service,'linger_enabled',lambda:False)
    monkeypatch.setattr(service,'systemctl',lambda *args,**kwargs:SimpleNamespace(returncode=0,stderr=''))
    assert 'sudo loginctl enable-linger test-user' in service.install()[0]
