#!/usr/bin/env python3
"""Offline regression probe: settings, paired-device vault, identity and activity."""
import json
import os
from pathlib import Path

from mcptoai_linux.paths import config_dir
from mcptoai_linux.secret_store import get_secret, set_secret

root = config_dir()
root.mkdir(parents=True, exist_ok=True)
mode = os.environ['UPGRADE_PROBE_MODE']
settings = root / 'settings.json'
identity = root / 'identity.pub'
marker = root / 'pairing-probe.json'
expected = {'provider': 'openai', 'workspace_root': '/tmp/mcptoai-upgrade-workspace'}
if mode == 'seed':
    settings.write_text(json.dumps(expected))
    identity.write_text('public-key-preserved')
    marker.write_text(json.dumps({'device_id': 'paired-device-preserved'}))
    set_secret('device_id', 'paired-device-preserved')
    set_secret('device_auth', 'offline-test-token')
elif mode == 'verify':
    assert json.loads(settings.read_text()) == expected
    assert identity.read_text() == 'public-key-preserved'
    assert json.loads(marker.read_text())['device_id'] == 'paired-device-preserved'
    assert get_secret('device_id') == 'paired-device-preserved'
    assert get_secret('device_auth') == 'offline-test-token'
else:
    raise ValueError(mode)
if os.getenv('UPGRADE_CHECK_ACTIVITY') == '1':
    from mcptoai_core.activity_store import ActivityStore
    from mcptoai_core.activity_events import make_event
    store = ActivityStore()
    try:
        if mode == 'seed':
            store.append(make_event(session_id='upgrade', turn_id='turn', tool_name='read_file', phase='completed', target_type='other'))
        else:
            assert len(store.list_events(limit=10)) == 1, 'Activity history lost'
    finally:
        store.close()
print(f'{mode}: config, pairing and optional activity state intact at {root}')
