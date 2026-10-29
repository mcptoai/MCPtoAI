"""Official SIWC Codex app-server transport (local process only).

OAuth registration, PKCE, refresh and secure storage belong to the separate
SIWC account manager. Never pass API keys or Codex CLI auth files here.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any


class CodexAppServerError(RuntimeError):
    pass


CODEX_ARGS = (
    'app-server', '--listen', 'stdio://',
    '-c', 'model_provider="openai_chatgpt_plan"',
    '-c', 'model_providers.openai_chatgpt_plan.name="ChatGPT plan"',
    '-c', 'model_providers.openai_chatgpt_plan.base_url="https://api.openai.com/v1"',
    '-c', 'model_providers.openai_chatgpt_plan.env_key="ACCESS_TOKEN"',
    '-c', 'model_providers.openai_chatgpt_plan.wire_api="responses"',
    '-c', 'model_providers.openai_chatgpt_plan.requires_openai_auth=false',
    '-c', 'model_providers.openai_chatgpt_plan.supports_websockets=false',
)


class CodexAppServer:
    """Local stdio JSON-RPC wrapper; never sends OAuth tokens to MCPtoAI Cloud."""

    def __init__(self, access_token: str, *, executable: str = 'codex') -> None:
        if not access_token or not access_token.strip():
            raise ValueError('SIWC access token required')
        self._token = access_token
        self.executable = executable
        self.process: subprocess.Popen[str] | None = None
        self._next_id = 0

    def start(self, *, version: str = '0.2.7') -> None:
        if self.process is not None:
            raise CodexAppServerError('Already started')
        env = dict(os.environ)
        env.pop('OPENAI_API_KEY', None)
        env['ACCESS_TOKEN'] = self._token
        self.process = subprocess.Popen(
            [self.executable, *CODEX_ARGS], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1, env=env,
        )
        self._token = ''
        self.request('initialize', {
            'clientInfo': {'name': 'mcptoai', 'title': 'MCPtoAI', 'version': version},
            'capabilities': {},
        })
        self.send({'method': 'initialized', 'params': {}})

    def send(self, message: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise CodexAppServerError('App-server not started')
        self.process.stdin.write(json.dumps(message, separators=(',', ':')) + '\n')
        self.process.stdin.flush()

    def events(self):
        if not self.process or not self.process.stdout:
            raise CodexAppServerError('App-server not started')
        for line in self.process.stdout:
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise CodexAppServerError('Invalid JSON from app-server') from exc

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self.send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params})
        for message in self.events():
            if message.get('id') == request_id:
                if 'error' in message:
                    raise CodexAppServerError(str(message['error']))
                return message.get('result') or {}
        raise CodexAppServerError('App-server closed unexpectedly')

    def close(self) -> None:
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None
