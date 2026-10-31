"""Exercise the real CLI entrypoint with a cp1252 redirected pipe and fake Auth0."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = 'mcptoai_agent'


def _run_login_cp1252(entrypoint):
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as d:
        site = Path(d) / 'sitecustomize.py'
        site.write_text(f'''from types import SimpleNamespace
import {PKG}.auth as auth
original = auth.device_login
class Response:
    def raise_for_status(self): pass
    def json(self): return {{'verification_uri_complete':'https://auth.example.test/activate?code=ABC','user_code':'ABC','device_code':'fake','expires_in':5,'interval':0}}
class Client:
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    async def post(self,url,**kwargs):
        if url.endswith('/oauth/token'): raise SystemExit(0)
        return Response()
async def wrapped(_cfg):
    auth.httpx.AsyncClient=lambda **kwargs: Client()
    cfg=SimpleNamespace(auth0_domain='auth.example.test',auth0_device_client_id='fake',auth0_audience='fake')
    return await original(cfg)
auth.device_login=wrapped
''')
        env = dict(os.environ, PYTHONIOENCODING='cp1252', PYTHONPATH=os.pathsep.join([d,str(root)]))
        env.pop('PYTHONUTF8', None)
        if entrypoint == 'module':
            cmd = [sys.executable, '-m', PKG, 'login']
        elif entrypoint == 'cli-main':
            cmd = [sys.executable, '-c', f'import sys; from {PKG}.cli import main; sys.argv=["mcptoai", "login"]; main()']
        elif entrypoint == 'pyinstaller':
            cmd = [sys.executable, str(root / 'pyinstaller_entry.py'), 'login']
        else:
            raise ValueError(entrypoint)
        p = subprocess.run(cmd, env=env, cwd=root, capture_output=True, timeout=20)
        assert p.returncode == 0, p.stderr.decode('utf-8', 'replace')
        assert b'https://auth.example.test/activate' in p.stdout


def test_login_cp1252_module():
    _run_login_cp1252("module")


def test_login_cp1252_pyinstaller():
    _run_login_cp1252("pyinstaller")
