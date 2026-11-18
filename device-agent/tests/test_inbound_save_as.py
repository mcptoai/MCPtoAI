from pathlib import Path
import pytest
from mcptoai_agent.inbound_transfer import available_destination, DestinationExistsError

def test_device_chooses_unique_name_and_never_overwrites(tmp_path):
    (tmp_path/'report.txt').write_text('original')
    (tmp_path/'report (1).txt').write_text('second')
    with pytest.raises(DestinationExistsError):
        available_destination('report.txt',str(tmp_path),[tmp_path])
    target=available_destination('report.txt',str(tmp_path),[tmp_path],rename_if_exists=True)
    assert target.name=='report (2).txt'
    assert (tmp_path/'report.txt').read_text()=='original'
    assert (tmp_path/'report (1).txt').read_text()=='second'

def test_casefold_collision_and_symlink_are_skipped(tmp_path):
    (tmp_path/'Report.TXT').write_text('keep')
    (tmp_path/'report (1).txt').symlink_to(tmp_path/'Report.TXT')
    assert available_destination('report.txt',str(tmp_path),[tmp_path],rename_if_exists=True).name=='report (2).txt'
