"""Opt-in device gate, real AgentSession tool-dispatch regression tests."""
import asyncio
from dataclasses import replace

import pytest

from mcptoai_agent.agent import AgentSession
from mcptoai_agent.config import settings
from mcptoai_agent.policy import Decision, ToolPolicy
from mcptoai_agent.providers.base import AssistantTurn, Provider, ToolCall
from mcptoai_agent.tools import build_server


class OneCall(Provider):
    name = 'gate-test'
    def __init__(self, tool, arguments):
        super().__init__('x', 'gate-test'); self.tool = tool; self.arguments = arguments; self.step = 0
    async def complete(self, system, messages, tools):
        self.step += 1
        if self.step == 1:
            return AssistantTurn(tool_calls=[ToolCall('gate-1', self.tool, self.arguments)])
        return AssistantTurn(text='done')


def run_one(tmp_path, *, enabled, approve=True, mutate=False, tool='write_file', policy=None):
    cfg = replace(settings, allowed_roots=[tmp_path.resolve()])
    target = tmp_path / 'written.txt'
    args = {'path': str(target), 'content': 'original'} if tool == 'write_file' else {'path': str(target)}
    session = AgentSession(cfg, OneCall(tool, args), build_server(cfg), policy=policy)
    session.action_approval_gate_enabled = enabled
    session.action_identity_resolver = lambda: ("auth0|test-user", "paired-device")
    session.action_turn_id = "local-test-turn"
    events = []
    async def emit(event): events.append(event)
    async def approver(name, arguments):
        if mutate: arguments['content'] = 'tampered'
        return approve
    asyncio.run(session.run('test', approver, emit))
    return target, events, session


def test_gate_off_preserves_legacy_write(tmp_path):
    target, events, _ = run_one(tmp_path, enabled=False)
    assert target.read_text() == 'original'


def test_gate_on_executes_approved_write(tmp_path):
    target, events, session = run_one(tmp_path, enabled=True)
    assert target.read_text() == 'original'
    assert any(e.get('type') == 'tool_result' and not e.get('is_error') for e in events)


def test_gate_on_ignores_mutation_of_native_preview_copy(tmp_path):
    target, events, _ = run_one(tmp_path, enabled=True, mutate=True)
    assert target.read_text() == 'original'
    assert any(e.get('type') == 'tool_result' and not e.get('is_error') for e in events)


def test_gate_on_preserves_denied_write(tmp_path):
    target, events, _ = run_one(tmp_path, enabled=True, approve=False)
    assert not target.exists()


def test_gate_on_preserves_off_policy(tmp_path):
    target, events, _ = run_one(tmp_path, enabled=True, policy=ToolPolicy(rules={'write_file': Decision.DENY}))
    assert not target.exists()


def test_gate_on_preserves_auto_read_policy(tmp_path):
    target = tmp_path / 'written.txt'; target.write_text('hello')
    cfg = replace(settings, allowed_roots=[tmp_path.resolve()])
    session = AgentSession(cfg, OneCall('read_file', {'path': str(target)}), build_server(cfg),
                           policy=ToolPolicy(rules={'read_file': Decision.AUTO}))
    session.action_approval_gate_enabled = True
    session.action_identity_resolver = lambda: ("auth0|test-user", "paired-device")
    session.action_turn_id = "local-test-turn"
    events=[]
    async def emit(event): events.append(event)
    async def never_approve(*args): raise AssertionError('Auto read must not prompt')
    asyncio.run(session.run('read', never_approve, emit))
    assert any(e.get('type') == 'tool_result' and not e.get('is_error') for e in events)


def test_identity_changed_during_approval_rejects_dispatch(tmp_path):
    cfg = replace(settings, allowed_roots=[tmp_path.resolve()])
    target = tmp_path / 'identity-denied.txt'
    session = AgentSession(cfg, OneCall('write_file', {'path': str(target), 'content': 'secret'}), build_server(cfg))
    session.action_approval_gate_enabled = True
    session.action_turn_id = 'turn-1'
    identity = [('auth0|original', 'device-original')]
    session.action_identity_resolver = lambda: identity[0]
    async def approver(tool, arguments):
        assert arguments['_mcptoai_native_action'] is True
        identity[0] = ('auth0|different', 'device-original')
        return True
    async def emit(event): pass
    asyncio.run(session.run('write', approver, emit))
    assert not target.exists()


def test_missing_identity_fails_closed(tmp_path):
    cfg = replace(settings, allowed_roots=[tmp_path.resolve()])
    target = tmp_path / 'missing-identity.txt'
    session = AgentSession(cfg, OneCall('write_file', {'path': str(target), 'content': 'secret'}), build_server(cfg))
    session.action_approval_gate_enabled = True
    session.action_turn_id = 'turn-1'
    session.action_identity_resolver = lambda: None
    async def approver(tool, arguments): return True
    async def emit(event): pass
    asyncio.run(session.run('write', approver, emit))
    assert not target.exists()
