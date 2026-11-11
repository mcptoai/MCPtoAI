"""Real subprocess fixtures for unexpected vs normal exit."""
import sys
import time
from mcptoai_agent.agent_supervisor import supervise


def test_crash_then_normal_exit(tmp_path):
    marker=tmp_path/'runs'
    code=("from pathlib import Path; p=Path(%r); n=int(p.read_text())+1 if p.exists() else 1; "
          "p.write_text(str(n)); raise SystemExit(9 if n==1 else 0)") % str(marker)
    assert supervise([sys.executable,'-c',code],pause=lambda _:False)==0
    assert marker.read_text()=='2'


def test_normal_exit_never_restarts(tmp_path):
    marker=tmp_path/'runs'
    code=f"from pathlib import Path; p=Path({str(marker)!r}); p.write_text('1')"
    assert supervise([sys.executable,'-c',code])==0
    assert marker.read_text()=='1'
