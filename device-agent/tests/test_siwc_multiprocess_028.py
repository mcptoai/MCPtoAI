"""Two real OS processes, real file lock, synthetic token storage and HTTP."""
import json
import multiprocessing
import time
from pathlib import Path
from unittest.mock import patch

from mcptoai_agent import siwc_auth
from mcptoai_agent.credential_lock import CredentialLock


def _worker(path, ready, start, results):
    state = Path(path)
    lock = CredentialLock(lambda: state / 'vault.lock')

    def read(_name):
        return json.loads((state / 'account.json').read_text())

    def write(_name, value):
        (state / 'account.json').write_text(json.dumps(value))

    def fake_request(_url, **_kwargs):
        with (state / 'calls.txt').open('a') as output:
            output.write('refresh\n')
        time.sleep(0.15)
        return {'access_token':'rotated-access', 'refresh_token':'rotated-refresh', 'expires_in':3600}

    # Both processes must observe the stale token before either may refresh.
    stale = read('account')
    ready.put(True)
    if not start.wait(10):
        results.put('start timeout')
        return
    with patch.object(siwc_auth, 'credential_lock', lock.hold), \
         patch.object(siwc_auth, 'vault_get', side_effect=read), \
         patch.object(siwc_auth, 'vault_put', side_effect=write), \
         patch.object(siwc_auth, 'paired_owner', return_value='synthetic-owner'), \
         patch.object(siwc_auth, 'request_json', side_effect=fake_request):
        try:
            results.put(siwc_auth.refresh(expected_refresh_token=stale['refresh_token']))
        except Exception as exc:
            results.put(type(exc).__name__ + ': ' + str(exc))


def test_real_processes_refresh_once(tmp_path):
    (tmp_path / 'account.json').write_text(json.dumps({
        'mcptoai_owner_sub':'synthetic-owner', 'client_id':'fake-client',
        'refresh_token':'stale-refresh', 'access_token':'stale-access',
        'expires_at':0, 'scopes':['chatgpt.tokens.use.direct']}))
    ctx = multiprocessing.get_context('spawn')
    ready, results, start = ctx.Queue(), ctx.Queue(), ctx.Event()
    processes = [ctx.Process(target=_worker, args=(str(tmp_path), ready, start, results)) for _ in range(2)]
    for process in processes:
        process.start()
    try:
        assert ready.get(timeout=10) and ready.get(timeout=10)
        start.set()
        values = [results.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(timeout=15)
        assert all(process.exitcode == 0 for process in processes)
        assert values == ['rotated-access', 'rotated-access']
        assert (tmp_path / 'calls.txt').read_text().splitlines() == ['refresh']
        assert json.loads((tmp_path / 'account.json').read_text())['refresh_token'] == 'rotated-refresh'
    finally:
        start.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
