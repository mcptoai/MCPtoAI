from pathlib import Path
from mcptoai_agent.tools.bounded_find import find_bounded


def check(_path, *, write=False):
    assert not write


def test_result_limit_returns_partial_and_sorted(tmp_path):
    for n in range(10): (tmp_path/f'file{n}.txt').write_text('x'*(n+1))
    output=find_bounded(tmp_path,'*.txt',check_path=check,limit=3)
    assert len([x for x in output.splitlines() if 'file' in x])==3
    assert 'PARTIAL RESULTS: result limit' in output


def test_depth_limit_marks_incomplete(tmp_path):
    deep=tmp_path/'a'/'b';deep.mkdir(parents=True)
    (deep/'lost.txt').write_text('hidden')
    output=find_bounded(tmp_path,'*.txt',check_path=check,max_depth=1)
    assert 'lost.txt' not in output
    assert 'PARTIAL RESULTS: depth limit' in output


def test_time_limit_returns_partial(tmp_path):
    for i in range(50): (tmp_path/f'{i}.txt').write_text('ok')
    tick=[0]
    def time_source():
        tick[0]+=.1
        return tick[0]
    output=find_bounded(tmp_path,'*.txt',check_path=check,seconds=.5,clock=time_source)
    assert 'PARTIAL RESULTS: time limit' in output


def test_protected_and_symlink_never_traversed(tmp_path):
    protected=tmp_path/'secret';protected.mkdir();(protected/'hidden.txt').write_text('bad')
    (tmp_path/'allowed.txt').write_text('ok')
    (tmp_path/'linked').symlink_to(protected,target_is_directory=True)
    def policy(path,*,write=False):
        if path==protected or protected in path.parents:raise PermissionError('no')
    output=find_bounded(tmp_path,'*.txt',check_path=policy)
    assert 'allowed.txt' in output and 'hidden.txt' not in output
    assert 'protected paths skipped' in output
