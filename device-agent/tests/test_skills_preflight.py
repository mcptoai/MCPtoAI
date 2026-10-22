"""Doğrulama onay kartından ÖNCE yapılır: zaten reddedilecek bir çağrı için kullanıcıdan onay istenmez.

Üç katman: preflight birim testleri, preflight ile yürütmenin ayrışmadığını kanıtlayan tutarlılık testi ve gerçek
AgentSession döngüsünde "onay hiç sorulmadı" testleri."""
import asyncio
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from mcptoai_agent import skills
from mcptoai_agent.agent import AgentSession
from mcptoai_agent.config import settings
from mcptoai_agent.providers.base import AssistantTurn, Provider, ToolCall
from mcptoai_agent.tools import build_server

SHA = 'c' * 40
SCRIPT = "import sys\nif len(sys.argv) > 1:\n    open(sys.argv[1], 'w').write('ran')\nprint('ok')\n"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        patcher = patch.object(skills, 'config_dir', return_value=self.root / 'config')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.work = self.root / 'work'
        self.work.mkdir()
        self.marker = self.work / 'ran.marker'
        source = self.root / 'source'
        for name in ('one', 'two'):
            directory = source / name
            directory.mkdir(parents=True)
            (directory / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: {name}\n---\nBody')
        (source / 'one' / 'run.py').write_text(SCRIPT)
        skills.install_package(source, 'pack', SHA, approved=True)
        self.package = self.root / 'config' / 'skills' / 'pack'

    def call(self, **overrides):
        args = {'skill': 'one', 'script': 'run.py', 'args': [str(self.marker)]}
        args.update(overrides)
        return args

    def snapshot(self):
        backup = self.root / 'backup'
        shutil.rmtree(backup, ignore_errors=True)
        shutil.copytree(self.package, backup)
        return backup

    def restore(self, backup):
        shutil.rmtree(self.package, ignore_errors=True)
        shutil.copytree(backup, self.package)


class PreflightTests(Fixture):
    def pre(self, tool='run_skill_script', **overrides):
        return skills.preflight(tool, self.call(**overrides) if tool == 'run_skill_script' else overrides, allowed_roots=[self.work])

    def test_valid_calls_pass(self):
        self.assertIsNone(self.pre())
        self.assertIsNone(self.pre('skill_data_write', path='~/.codex/youtube/voice.md', content='profil'))

    def test_other_tools_are_never_checked(self):
        for tool in ('read_file', 'load_skill', 'read_skill_file', 'write_file', 'run_command', 'skill_data_read', 'list_dir'):
            self.assertIsNone(skills.preflight(tool, {'skill': '../../x', 'path': '/etc/passwd'}, allowed_roots=[self.work]), tool)

    def test_every_refusal_reason_is_reported_before_approval(self):
        backup = self.snapshot()
        cases = {
            'betik değiştirildi': (lambda: (self.package / 'one' / 'run.py').write_text('print("evil")'), {}, 'Package files changed since installation'),
            'fazladan dosya': (lambda: (self.package / 'one' / 'extra.txt').write_text('x'), {}, 'Package files changed since installation'),
            'fazladan klasör': (lambda: (self.package / 'ghost').mkdir(), {}, 'Unexpected or missing entries'),
            'skill devre dışı': (lambda: skills.set_enabled('one', False), {}, 'disabled'),
            'kayıtsız betik': (lambda: None, {'script': 'missing.py'}, 'Script not installed'),
            'betik yolu kaçışı': (lambda: None, {'script': '../../x.py'}, ''),
            'çalışma alanı dışı argüman': (lambda: None, {'args': ['/etc/passwd']}, 'outside the allowed folders'),
            'liste olmayan argüman': (lambda: None, {'args': 'metin'}, 'Invalid script arguments'),
            'olmayan skill': (lambda: None, {'skill': 'yok'}, 'not installed'),
        }
        for label, (mutate, overrides, expected) in cases.items():
            with self.subTest(label):
                mutate()
                message = self.pre(**overrides)
                self.assertIsNotNone(message, 'onaydan önce reddedilmeliydi')
                self.assertIn('no approval was requested', message)
                self.assertIn(expected, message)
                if 'PermissionError' in message:
                    self.assertIn('workaround', message)  # modele "dolanma" talimatı gider
                self.restore(backup)
                skills.set_enabled('one', True)
                self.assertIsNone(self.pre(), f'{label}: geri alınınca geçmeli')

    def test_missing_python_is_reported_before_approval(self):
        with patch.object(skills.shutil, 'which', return_value=None):
            self.assertIn('Python gerekli', self.pre())

    def test_data_write_refusals(self):
        for label, kwargs in {'yol kaçışı': {'path': '../x', 'content': 'a'}, 'iki nokta': {'path': 'x:y', 'content': 'a'},
                              'mutlak yol': {'path': '/abs', 'content': 'a'}, 'büyük veri': {'path': 'ok/x.md', 'content': 'a' * 300000},
                              'metin değil': {'path': 'ok/x.md', 'content': 5}}.items():
            with self.subTest(label):
                message = self.pre('skill_data_write', **kwargs)
                self.assertIn('no approval was requested', message)

    def test_preflight_never_raises_on_garbage(self):
        for arguments in (None, [], 5, 'x', {}, {'skill': None}, {'skill': 5, 'script': ['a']}, {'skill': 'one', 'script': 'run.py', 'args': {'a': 1}},
                          {'skill': 'one', 'script': 'run.py', 'args': [None]}, {'skill': 'one', 'script': None}):
            message = skills.preflight('run_skill_script', arguments, allowed_roots=[self.work])
            self.assertIsInstance(message, str, repr(arguments))
        self.assertIsInstance(skills.preflight('skill_data_write', None, allowed_roots=None), str)


class AgreementTests(Fixture):
    def test_preflight_and_execution_never_disagree(self):
        # Özellik: onay öncesi doğrulama geçiyorsa çalıştırma başarılı olur; reddediyorsa çalıştırma da reddeder.
        backup = self.snapshot()
        scenarios = {
            'geçerli': (lambda: None, {}),
            'betik değişti': (lambda: (self.package / 'one' / 'run.py').write_text('print(1)'), {}),
            'fazladan dosya': (lambda: (self.package / 'two' / 'x.txt').write_text('x'), {}),
            'devre dışı': (lambda: skills.set_enabled('one', False), {}),
            'kayıtsız betik': (lambda: None, {'script': 'nope.py'}),
            'dış argüman': (lambda: None, {'args': ['/etc/hosts']}),
            'kardeş betik yazımı': (lambda: None, {'script': '../one/run.py'}),
            'yol kaçışı': (lambda: None, {'script': '../../run.py'}),
        }
        for label, (mutate, overrides) in scenarios.items():
            with self.subTest(label):
                mutate()
                args = self.call(**overrides)
                message = skills.preflight('run_skill_script', args, allowed_roots=[self.work])
                try:
                    result = skills.run_skill_script(args['skill'], args['script'], args['args'], allowed_roots=[self.work])
                    executed = result['exit_code'] == 0
                except (PermissionError, ValueError, RuntimeError, OSError):
                    executed = False
                self.assertEqual(message is None, executed, f'ayrışma: preflight={message!r} yürütme={executed}')
                self.restore(backup)
                skills.set_enabled('one', True)


class OneCall(Provider):
    name = 'onecall'

    def __init__(self, tool, arguments):
        super().__init__('x', 'onecall')
        self.tool, self.arguments, self.step = tool, arguments, 0

    async def complete(self, system, messages, tools):
        self.step += 1
        if self.step == 1:
            return AssistantTurn(tool_calls=[ToolCall('1', self.tool, self.arguments)])
        return AssistantTurn(text='bitti')


class AgentLoopTests(Fixture):
    def drive(self, tool, arguments):
        cfg = replace(settings, allowed_roots=[self.work], enable_shell=True)
        session = AgentSession(cfg, OneCall(tool, arguments), build_server(cfg))
        events, asked = [], []

        async def emit(event): events.append(event)

        async def approver(name, args):
            asked.append(name)
            return True
        asyncio.run(session.run('git', approver, emit))
        result = next(e for e in events if e['type'] == 'tool_result')
        return asked, result, session

    def test_valid_call_still_asks_for_approval_and_runs(self):
        asked, result, _ = self.drive('run_skill_script', self.call())
        self.assertEqual(asked, ['run_skill_script'])
        self.assertFalse(result['is_error'])
        self.assertEqual(self.marker.read_text(), 'ran')

    def test_tampered_package_is_refused_without_asking_and_nothing_runs(self):
        (self.package / 'one' / 'run.py').write_text(f"open({str(self.marker)!r}, 'w').write('EVIL')\n")
        asked, result, session = self.drive('run_skill_script', self.call())
        self.assertEqual(asked, [], 'kullanıcıya reddedilecek bir çağrı onaylatılmamalı')
        self.assertTrue(result['is_error'])
        self.assertIn('no approval was requested', result['preview'])
        self.assertIn('Package files changed since installation', result['preview'])
        self.assertFalse(self.marker.exists(), 'betik çalışmamalı')
        self.assertIn('preflight_refused', json.dumps(session.audit, default=str))

    def test_disabled_skill_and_outside_arguments_are_refused_without_asking(self):
        skills.set_enabled('one', False)
        asked, result, _ = self.drive('run_skill_script', self.call())
        self.assertEqual(asked, [])
        self.assertTrue(result['is_error'])
        skills.set_enabled('one', True)
        asked, result, _ = self.drive('run_skill_script', self.call(args=['/etc/passwd']))
        self.assertEqual(asked, [])
        self.assertIn('outside the allowed folders', result['preview'])

    def test_data_write_refusal_and_normal_approvals_are_unchanged(self):
        asked, result, _ = self.drive('skill_data_write', {'path': '../evil', 'content': 'x'})
        self.assertEqual(asked, [])
        self.assertTrue(result['is_error'])
        asked, result, _ = self.drive('skill_data_write', {'path': 'youtube/voice.md', 'content': 'profil'})
        self.assertEqual(asked, ['skill_data_write'])
        self.assertFalse(result['is_error'])
        asked, result, _ = self.drive('write_file', {'path': str(self.work / 'a.txt'), 'content': 'x'})
        self.assertEqual(asked, ['write_file'])   # skill dışı araçların onayı aynen sürer


if __name__ == '__main__':
    unittest.main()
