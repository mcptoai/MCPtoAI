"""Desktop IPC calls local CLI; destructive tests run in an isolated HOME only."""
import os
import subprocess
import sys
from pathlib import Path

from mcptoai_agent.activity_events import make_event
from mcptoai_agent.activity_store import ActivityStore


def test_desktop_clear_uses_local_ipc_cli_not_relay():
    desktop=Path(__file__).resolve().parents[2]/'desktop'/'src'
    main=(desktop/'main.js').read_text()
    renderer=(desktop/'renderer.js').read_text()
    # The IPC handler must call the local CLI and only clear the persisted
    # observation after the CLI reports successful deletion.
    assert "ipcMain.handle('activity:clear'" in main
    assert "activityCli(['activity-clear','--confirm'])" in main
    assert 'if(result.ok)activityObservation.clear(configRoot)' in main
    assert "ipcRenderer.invoke('activity:clear')" in (desktop/'preload.js').read_text()
    assert 'window.mcp.activityClear()' in renderer


def test_activity_clear_isolated_mac_profile(tmp_path):
    if sys.platform!='darwin':
        import pytest
        pytest.skip('macOS profile isolation regression')
    root=tmp_path/'isolated'; root.mkdir()
    (root/'.mcptoai-activity-test-only').touch()
    home=root/'home';home.mkdir()
    target=home/'.config'/'mcptoai'/'activity-v1.sqlite3'
    from mcptoai_agent.activity_test_guard import assert_isolated_activity_db
    import mcptoai_agent.activity_test_guard as guard
    old=guard.config_dir
    guard.config_dir=lambda:target.parent
    try: assert assert_isolated_activity_db(root)==target.resolve()
    finally: guard.config_dir=old
    store=ActivityStore(target)
    store.append(make_event(session_id='isolated',turn_id='test',tool_name='read_file',phase='completed'))
    assert len(store.list_events(limit=10))==1
    store.close()
    env=dict(os.environ,HOME=str(home))
    # Do not inherit host's XDG location into an isolated test profile.
    env.pop('XDG_CONFIG_HOME',None)
    env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])+os.pathsep+str(Path(__file__).resolve().parents[2]/'shared-core')
    cmd=[sys.executable,'-m','mcptoai_agent','activity-clear']
    denied=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=20)
    assert denied.returncode!=0
    store=ActivityStore(target)
    assert len(store.list_events(limit=10))==1
    store.close()
    result=subprocess.run(cmd+['--confirm'],env=env,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    store=ActivityStore(target)
    assert store.list_events(limit=10)==[]
    store.close()
    assert target.resolve().is_relative_to(root.resolve())
