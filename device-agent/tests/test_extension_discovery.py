"""Desteklenmeyen depoların çalıştırılmadan reddedildiğini doğrular."""
import tempfile
from pathlib import Path
from unittest.mock import patch
from mcptoai_agent.extension_discovery import inspect_repository

SHA = 'a'*40

def test_unknown_repository_is_not_installable():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        (root/'README.md').write_text('nothing')
        result=inspect_repository(root,'sample',SHA)
        assert result['kind']=='unknown'
        assert not result['installable'] and not result['execution_allowed']

def test_cli_candidate_does_not_run_code():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        (root/'package.json').write_text('{"scripts":{"postinstall":"touch /tmp/should-not-exist"}}')
        with patch('subprocess.run',side_effect=AssertionError('Must not execute')):
            result=inspect_repository(root,'sample',SHA)
        assert result['kind']=='application-or-cli-candidate'
        assert not result['supported']

def test_valid_skill_requires_explicit_approval():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        skill=root/'skills'/'example';skill.mkdir(parents=True)
        (skill/'SKILL.md').write_text('---\nname: example\ndescription: example\n---\n')
        result=inspect_repository(root,'sample',SHA)
        assert result['kind']=='skill-package'
        assert result['requires_user_approval']
        assert not result['execution_allowed']
        assert result['preview']['skills']['example']['enabled']
