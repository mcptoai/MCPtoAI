"""0.2.9 PR 3: agent döngüsünden aktivite olayları (tek üretici, yalnızca meta veri)."""
import asyncio
import json
from dataclasses import replace
from pathlib import Path

from mcptoai_linux.activity_store import ActivityStore
from mcptoai_linux.agent import AgentSession
from mcptoai_linux.config import settings
from mcptoai_linux.providers.base import AssistantTurn, Provider, ToolCall
from mcptoai_linux.tools import build_server

SECRET = 'sk-live-SECRET1234567890abcdef'


class ScriptProvider(Provider):
    name = 'fake'

    def __init__(self, calls):
        super().__init__('x', 'fake')
        self.calls = list(calls)

    async def complete(self, system, messages, tools):
        if self.calls:
            return AssistantTurn(tool_calls=[self.calls.pop(0)])
        return AssistantTurn(text='done')


def _run(tmp_path, calls, approve=True, grants=()):
    cfg = replace(settings, allowed_roots=[tmp_path.resolve()])
    session = AgentSession(cfg, ScriptProvider(calls), build_server(cfg))
    session.policy.session_grants.update(grants)
    session.activity_store = ActivityStore(tmp_path / 'activity.db')
    session.activity_session_id = 'session-test-1'
    events = []

    async def emit(e):
        events.append(e)

    async def approver(tool, args):
        return approve

    asyncio.run(session.run('go', approver, emit))
    rows = session.activity_store.list_events(limit=500)[::-1]
    raw = session.activity_store.path.read_bytes()
    session.activity_store.close()
    return events, rows, raw


def _phases(rows, tool):
    return [r['phase'] for r in rows if r['tool_name'] == tool]


def test_auto_allowed_tool_records_lifecycle_with_duration(tmp_path):
    events, rows, _ = _run(tmp_path, [ToolCall('1', 'list_dir', {'path': str(tmp_path)})], grants={'list_dir'})
    assert _phases(rows, 'list_dir') == ['requested', 'started', 'completed']
    final = [r for r in rows if r['phase'] == 'completed'][0]
    assert final['permission_decision'] == 'not_required' and isinstance(final['duration_ms'], int)
    assert all(r['session_id'] == 'session-test-1' for r in rows)
    req = [e for e in events if e.get('type') == 'tool_request'][0]
    res = [e for e in events if e.get('type') == 'tool_result'][0]
    assert req['activity_id'] == res['activity_id'] == final['activity_id']
    assert req['activity']['phase'] == 'requested' and res['activity']['phase'] == 'completed'


def test_approved_write_records_approval_phases_and_hides_content(tmp_path):
    events, rows, raw = _run(tmp_path, [ToolCall('1', 'write_file', {'path': str(tmp_path / 'x.txt'), 'content': SECRET})])
    assert _phases(rows, 'write_file') == ['requested', 'approval_pending', 'approved', 'started', 'completed']
    assert (tmp_path / 'x.txt').read_text() == SECRET
    # Araç içeriği hiçbir aktivite kaydına ya da relay meta verisine girmez.
    assert SECRET.encode() not in raw
    for e in events:
        if 'activity' in e:
            assert SECRET not in json.dumps(e['activity'])


def test_denied_write_is_recorded_as_denied(tmp_path):
    events, rows, _ = _run(tmp_path, [ToolCall('1', 'write_file', {'path': str(tmp_path / 'y.txt'), 'content': 'x'})], approve=False)
    assert _phases(rows, 'write_file') == ['requested', 'approval_pending', 'denied']
    res = [e for e in events if e.get('type') == 'tool_result'][0]
    assert res['activity']['phase'] == 'denied' and res['activity']['permission_decision'] == 'denied'
    assert not (tmp_path / 'y.txt').exists()


def test_preflight_refusal_is_recorded_as_denied(tmp_path):
    events, rows, _ = _run(tmp_path, [ToolCall('1', 'read_file', {'path': str(tmp_path / 'missing.txt')})])
    assert _phases(rows, 'read_file') == ['requested', 'denied']
    res = [e for e in events if e.get('type') == 'tool_result'][0]
    assert res['activity']['phase'] == 'denied'


def test_failed_remote_mcp_tool_is_recorded_as_failed(tmp_path):
    cfg = replace(settings, allowed_roots=[tmp_path.resolve()])
    call = ToolCall('1', 'mcp__github__list_pull_requests', {'owner': 'mcptoai', 'repo': 'x', 'token': SECRET})
    session = AgentSession(cfg, ScriptProvider([call]), build_server(cfg))
    session.policy.session_grants.add(call.name)
    session.activity_store = ActivityStore(tmp_path / 'activity.db')

    async def remote(name, args):
        return '404 Not Found', True

    session.remote_caller = remote
    events = []

    async def emit(e):
        events.append(e)

    async def approver(tool, args):
        return True

    asyncio.run(session.run('go', approver, emit))
    rows = session.activity_store.list_events(limit=500)[::-1]
    raw = session.activity_store.path.read_bytes()
    session.activity_store.close()
    assert _phases(rows, call.name) == ['requested', 'started', 'failed']
    assert rows[0]['target_type'] == 'mcp' and rows[0]['target_display'] == 'github / list_pull_requests'
    assert SECRET.encode() not in raw
    res = [e for e in events if e.get('type') == 'tool_result'][0]
    assert res['is_error'] and res['activity']['phase'] == 'failed'


def test_broken_store_never_breaks_the_tool(tmp_path):
    class Broken:
        def append(self, event):
            raise OSError('disk full')

    cfg = replace(settings, allowed_roots=[tmp_path.resolve()])
    session = AgentSession(cfg, ScriptProvider([ToolCall('1', 'list_dir', {'path': str(tmp_path)})]), build_server(cfg))
    session.activity_store = Broken()
    events = []

    async def emit(e):
        events.append(e)

    async def approver(tool, args):
        return True

    assert asyncio.run(session.run('go', approver, emit)) == 'done'
    res = [e for e in events if e.get('type') == 'tool_result'][0]
    assert res['status'] == 'completed' and res['activity']['phase'] == 'completed'
