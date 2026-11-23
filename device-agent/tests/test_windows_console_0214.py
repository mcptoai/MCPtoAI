"""Windows real shell regression: Turkish filenames survive the command tool's pipe."""
import asyncio
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from mcptoai_agent.windows_console import shell_command_and_encoding


class WindowsShellEncodingTests(unittest.TestCase):
    def test_command_wrapper(self):
        command, encoding=shell_command_and_encoding('dir', windows=True)
        self.assertEqual(command, 'dir')
        self.assertTrue(encoding)
        self.assertEqual(shell_command_and_encoding('echo hello', windows=False), ('echo hello', None))

    @unittest.skipUnless(os.name == 'nt', 'requires Windows cmd and PowerShell')
    def test_real_cmd_and_powershell_turkish_directory(self):
        with tempfile.TemporaryDirectory(prefix='mcptoai-console-') as folder:
            name='ğşıöçü-test'
            target=Path(folder)/name
            target.mkdir()
            for command in (f'dir "{target}"',
                            f'powershell.exe -NoProfile -NonInteractive -Command "Get-ChildItem -LiteralPath \'{folder}\' | Select-Object -ExpandProperty Name"'):
                with self.subTest(command=command.split()[0]):
                    cmd, encoding=shell_command_and_encoding(command)
                    completed=subprocess.run(cmd,shell=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=20)
                    self.assertEqual(completed.returncode,0,completed.stderr)
                    self.assertIn(name,completed.stdout.decode(encoding))

    @unittest.skipUnless(os.name == 'nt', 'requires Windows shell')
    def test_real_async_shell_tool_turkish_directory(self):
        # Exercise the same subprocess_shell and decode path as run_command.
        from mcptoai_agent.tools.host_tools import build_server
        from mcptoai_agent.config import Settings
        from fastmcp import Client
        with tempfile.TemporaryDirectory(prefix='mcptoai-console-') as folder:
            target=Path(folder)/'ğşıöçü-test'; target.mkdir()
            async def test():
                server=build_server(Settings(enable_shell=True,allowed_roots=[Path(folder)]))
                async with Client(server) as client:
                    for command in (f'dir "{target}"',
                                    f'powershell.exe -NoProfile -NonInteractive -Command "Get-ChildItem -LiteralPath \'{folder}\' | Select-Object -ExpandProperty Name"'):
                        result=await client.call_tool('run_command', {'command':command})
                        body=''.join(c.text for c in result.content if hasattr(c,'text'))
                        self.assertIn('ğşıöçü-test',body,body)
            asyncio.run(test())
