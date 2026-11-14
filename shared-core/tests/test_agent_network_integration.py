"""Both legacy import paths use the shared classifier when it is installed."""
import subprocess
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_agent_network_uses_shared_classifier():
    for directory, module in (("device-agent", "mcptoai_agent.net"),
                              ("linux-agent", "mcptoai_linux.net")):
        script = (
            "from mcptoai_core.network import is_connection_reset; "
            f"from {module} import is_connection_reset as legacy; "
            "assert legacy is is_connection_reset"
        )
        env = dict(os.environ, PYTHONPATH=str(ROOT / "shared-core") + os.pathsep + str(ROOT / directory))
        subprocess.run([sys.executable, "-c", script], cwd=ROOT / directory, env=env,
                       check=True, capture_output=True, text=True)


def test_agent_relay_uses_shared_reconnect_policy():
    # Parse import surface without initializing an agent or starting sockets.
    import ast
    for directory in ('device-agent', 'linux-agent'):
        path = ROOT / directory / ('mcptoai_agent' if directory == 'device-agent' else 'mcptoai_linux') / 'relay_client.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                   and n.module == 'mcptoai_core.reconnect']
        assert len(imports) == 1
        assert any(a.name == 'reconnect_delay' and a.asname == '_reconnect_delay'
                   for a in imports[0].names)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == '_reconnect_delay']
        assert len(calls) == 2


def test_both_relays_use_shared_replay_parser():
    import ast
    for directory, strict in (('device-agent', False), ('linux-agent', True)):
        package = 'mcptoai_agent' if directory == 'device-agent' else 'mcptoai_linux'
        path = ROOT / directory / package / 'relay_client.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                   and n.module == 'mcptoai_core.replay']
        assert len(imports) >= 1
        assert any(a.name == 'parse_replay_request' for n in imports for a in n.names)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == '_parse_replay_request']
        assert len(calls) == 1
        assert any(k.arg == 'reject_turn_cursor' and isinstance(k.value, ast.Constant)
                   and k.value.value is strict for k in calls[0].keywords)


def test_both_relays_use_shared_replay_batch_and_completion():
    import ast
    for directory in ('device-agent', 'linux-agent'):
        package = 'mcptoai_agent' if directory == 'device-agent' else 'mcptoai_linux'
        tree = ast.parse((ROOT / directory / package / 'relay_client.py').read_text())
        calls = [n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)]
        assert calls.count('_replay_batch') == 0  # Transport helper owns replay batching
        assert calls.count('_replay_completion') == 1


def test_both_journals_import_shared_pruner():
    import ast
    for directory in ('device-agent', 'linux-agent'):
        package = 'mcptoai_agent' if directory == 'device-agent' else 'mcptoai_linux'
        tree = ast.parse((ROOT / directory / package / 'event_journal.py').read_text())
        assert any(isinstance(n, ast.ImportFrom) and n.module == 'mcptoai_core.journal'
                   and any(a.name == 'prune_expired' for a in n.names)
                   for n in ast.walk(tree))


def test_both_receipt_stores_use_shared_pruning():
    import ast
    for directory in ('device-agent', 'linux-agent'):
        package = 'mcptoai_agent' if directory == 'device-agent' else 'mcptoai_linux'
        tree = ast.parse((ROOT / directory / package / 'reliability.py').read_text())
        assert any(isinstance(n, ast.ImportFrom) and n.module == 'mcptoai_core.receipts'
                   for n in ast.walk(tree))
        assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == '_prune_receipts' for n in ast.walk(tree))


def test_both_relays_use_shared_event_envelopes():
    import ast
    for directory in ('device-agent', 'linux-agent'):
        package = 'mcptoai_agent' if directory == 'device-agent' else 'mcptoai_linux'
        tree = ast.parse((ROOT / directory / package / 'relay_client.py').read_text())
        assert any(isinstance(n, ast.ImportFrom) and n.module == 'mcptoai_core.events'
                   for n in ast.walk(tree))
        assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == '_event_envelope' for n in ast.walk(tree))


def test_both_relays_use_shared_replay_sender():
    import ast
    for directory in ('device-agent', 'linux-agent'):
        package = 'mcptoai_agent' if directory == 'device-agent' else 'mcptoai_linux'
        tree = ast.parse((ROOT / directory / package / 'relay_client.py').read_text())
        assert any(isinstance(n, ast.ImportFrom) and n.module == 'mcptoai_core.replay_transport'
                   for n in ast.walk(tree))
        assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == '_send_replay_events' for n in ast.walk(tree))


def test_both_relays_use_shared_session_pruning():
    import ast
    for directory in ('device-agent', 'linux-agent'):
        package = 'mcptoai_agent' if directory == 'device-agent' else 'mcptoai_linux'
        tree = ast.parse((ROOT / directory / package / 'relay_client.py').read_text())
        assert any(isinstance(n, ast.ImportFrom) and n.module == 'mcptoai_core.session_state'
                   for n in ast.walk(tree))
        assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == '_prune_session_state' for n in ast.walk(tree))


def test_both_journals_use_shared_safe_event_allowlist():
    import ast
    for directory in ('device-agent', 'linux-agent'):
        package = 'mcptoai_agent' if directory == 'device-agent' else 'mcptoai_linux'
        tree = ast.parse((ROOT / directory / package / 'event_journal.py').read_text())
        assert any(isinstance(n, ast.ImportFrom) and n.module == 'mcptoai_core.journal_entry'
                   for n in ast.walk(tree))
        assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == '_safe_journal_event' for n in ast.walk(tree))
