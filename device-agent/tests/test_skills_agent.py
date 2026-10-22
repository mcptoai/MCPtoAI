"""Skill araçlarının gerçek AgentSession döngüsünde ve relay onay akışında uçtan uca sınanması."""
import asyncio
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from mcptoai_agent import skills
from mcptoai_agent.agent import AgentSession
from mcptoai_agent.config import settings
from mcptoai_agent.providers.base import AssistantTurn, Provider, ToolCall
from mcptoai_agent.tools import build_server

SHA = 'b' * 40


def _install(tmp_path):
    source = tmp_path / 'source' / 'yt-script'
    source.mkdir(parents=True)
    (source / 'SKILL.md').write_text('---\nname: yt-script\ndescription: >-\n  Scores `hooks` <b>now</b>\n---\nBody')
    (source / 'main.py').write_text('print("ok")\n')
    skills.install_package(tmp_path / 'source', 'youtube', SHA, approved=True)


class SkillProvider(Provider):
    name = 'skill'

    def __init__(self, root):
        super().__init__('x', 'skill')
        self.root = root
        self.step = 0
        self.systems = []

    async def complete(self, system, messages, tools):
        self.systems.append(system)
        self.step += 1
        calls = {1: ToolCall('1', 'load_skill', {'name': 'yt-script'}),
                 2: ToolCall('2', 'run_skill_script', {'skill': 'yt-script', 'script': 'main.py', 'args': []}),
                 3: ToolCall('3', 'write_file', {'path': f'{self.root}/x.txt', 'content': 'hi'})}
        return AssistantTurn(tool_calls=[calls[self.step]]) if self.step in calls else AssistantTurn(text='bitti')


def test_skill_flow_in_the_real_agent_loop(tmp_path: Path):
    with patch.object(skills, 'config_dir', return_value=tmp_path / 'config'):
        _install(tmp_path)
        cfg = replace(settings, allowed_roots=[tmp_path.resolve()], enable_shell=True)
        provider = SkillProvider(str(tmp_path))
        session = AgentSession(cfg, provider, build_server(cfg))
        events, asked = [], []

        async def emit(event): events.append(event)

        async def approver(tool, args):
            asked.append(tool)
            return True
        asyncio.run(session.run('test', approver, emit))
    requests = {e['name']: e for e in events if e['type'] == 'tool_request'}
    results = {e['name']: e for e in events if e['type'] == 'tool_result'}
    # Betik çalıştırma ve veri yazma her zaman onay ister; skill okuma/yükleme istemez.
    assert asked == ['run_skill_script', 'write_file']
    assert results['load_skill']['is_error'] is False and results['run_skill_script']['is_error'] is False
    assert 'ok' in results['run_skill_script']['preview']
    # Skill adı yüklemeden SONRAKİ her araç çağrısında (genel araçlar dahil) görünür.
    assert 'skills' not in requests['load_skill'] and requests['load_skill']['skill'] == 'yt-script'
    assert requests['run_skill_script']['skills'] == ['yt-script']
    assert requests['write_file']['skills'] == ['yt-script']
    # Sistem talimatındaki özet temizlenmiş olmalı.
    prompt = provider.systems[0]
    assert 'yt-script' in prompt and '`' not in prompt.split('Installed skills')[1] and '<b>' not in prompt


def test_approval_event_carries_active_skill_names(tmp_path: Path):
    from mcptoai_agent.config import Settings
    from mcptoai_agent.relay_client import RelayClient
    from mcptoai_agent.reliability import MessageReceiptStore
    from mcptoai_agent.secret_store import provider_key_fingerprint

    client = RelayClient(Settings(provider='ollama', model='test-model'), receipt_store=MessageReceiptStore(tmp_path / 'r.json'))
    sent = []

    async def fake_send_event(session_id, event, turn_id=None): sent.append(event)
    client._send_event = fake_send_event

    class Cfg:
        model = 'test-model'
    client._chat_provider_cfg = lambda name: Cfg()

    class Stub:
        async def run(self, text, approver, emit, **kwargs):
            skills.activate('yt-script')
            task = asyncio.ensure_future(approver('write_file', {'path': 'x'}))
            await asyncio.sleep(0.05)
            for future, _ in list(client.pending_approvals.values()):
                future.set_result(True)
            await task
    client.sessions[f"s:ollama:test-model:{provider_key_fingerprint('ollama')}"] = Stub()

    async def scenario():
        await client._run_message({'type': 'message', 'session_id': 's', 'message': 'hello'})
    asyncio.run(scenario())
    required = [e for e in sent if e.get('type') == 'approval_required']
    assert required and required[0]['skills'] == ['yt-script']


class LoadSkillProvider(Provider):
    """load_skill çağırır, sonraki turda modelin gerçekte gördüğü mesajları saklar."""
    name = 'loadskill'

    def __init__(self):
        super().__init__('x', 'loadskill')
        self.step = 0
        self.seen = []

    async def complete(self, system, messages, tools):
        self.step += 1
        self.seen.append(messages)
        if self.step == 1:
            return AssistantTurn(tool_calls=[ToolCall('1', 'load_skill', {'name': 'big-doc'})])
        return AssistantTurn(text='bitti')


def test_large_skill_document_reaches_the_model_untruncated(tmp_path: Path):
    import json
    source = tmp_path / 'source' / 'big-doc'
    source.mkdir(parents=True)
    body = '---\nname: big-doc\ndescription: large instructions\n---\n' + ('line of instructions\n' * 5000) + 'END-MARKER'
    assert len(body) > 100 * 1024
    (source / 'SKILL.md').write_text(body)
    with patch.object(skills, 'config_dir', return_value=tmp_path / 'config'):
        skills.install_package(tmp_path / 'source', 'real', SHA, approved=True)
        cfg = replace(settings, allowed_roots=[tmp_path.resolve()], enable_shell=True)
        provider = LoadSkillProvider()
        session = AgentSession(cfg, provider, build_server(cfg))

        async def emit(event): pass

        async def approver(tool, args): return True
        asyncio.run(session.run('test', approver, emit))
    seen_by_model = json.dumps(provider.seen[1], default=str)
    assert 'END-MARKER' in seen_by_model, 'Modelin gördüğü talimat sonunda kesilmiş'
