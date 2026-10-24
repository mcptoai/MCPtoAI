from unittest.mock import patch
from mcptoai_agent.security_php import inspect_php


def test_no_php():
    with patch('mcptoai_agent.security_php.shutil.which', return_value=None):
        assert inspect_php().status == 'absent'


def test_vulnerable_upstream():
    with patch('mcptoai_agent.security_php.shutil.which', return_value='/usr/bin/php'), patch('mcptoai_agent.security_php.subprocess.run') as run:
        run.return_value.stdout = 'PHP 8.4.25 (cli)'
        run.return_value.stderr = ''
        finding = inspect_php()
        assert finding.status == 'review'
        assert '8.4.27' in finding.detail
        assert run.call_args.kwargs['timeout'] == 4


def test_patched_upstream():
    with patch('mcptoai_agent.security_php.shutil.which', return_value='/usr/bin/php'), patch('mcptoai_agent.security_php.subprocess.run') as run:
        run.return_value.stdout = 'PHP 8.4.27 (cli)'
        run.return_value.stderr = ''
        assert inspect_php().status == 'updated'


def test_old_branch():
    with patch('mcptoai_agent.security_php.shutil.which', return_value='/usr/bin/php'), patch('mcptoai_agent.security_php.subprocess.run') as run:
        run.return_value.stdout = 'PHP 7.4.33 (cli)'
        run.return_value.stderr = ''
        assert inspect_php().status == 'review'
