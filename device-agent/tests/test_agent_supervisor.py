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


def test_two_crashes_backoff_and_job_cleanup(monkeypatch):
    import mcptoai_agent.windows_job as windows_job
    class Job:
        def __init__(self): self.assigned=[]; self.closed=False
        def assign(self,pid): self.assigned.append(pid)
        def close(self): self.closed=True
    job=Job()
    monkeypatch.setattr(windows_job,'create_kill_on_close_job',lambda:job)
    codes=iter([9,7,0]); delays=[]; spawned=[]
    class Child:
        def __init__(self): self.pid=100+len(spawned);spawned.append(self)
        def wait(self): return next(codes)
    assert supervise(['agent','connect'],popen=lambda *a,**kw:Child(),pause=lambda seconds:(delays.append(seconds) or False))==0
    assert delays==[1,2]
    assert job.assigned==[100,101,102]
    assert job.closed is True


def test_job_assignment_failure_terminates_child(monkeypatch):
    import pytest
    import mcptoai_agent.windows_job as windows_job
    class Job:
        closed=False
        def assign(self,pid): raise OSError('assign failed')
        def close(self): self.closed=True
    job=Job();monkeypatch.setattr(windows_job,'create_kill_on_close_job',lambda:job)
    class Child:
        pid=101;terminated=False
        def terminate(self): self.terminated=True
        def wait(self): return 0
    child=Child()
    with pytest.raises(OSError,match='assign failed'):
        supervise(['agent','connect'],popen=lambda *a,**kw:child)
    assert child.terminated and job.closed
