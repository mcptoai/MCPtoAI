from pathlib import Path
import pytest
from mcptoai_agent.inbound_transfer import validate_destination, DestinationExistsError


def test_existing_target_reports_validation(tmp_path):
    (tmp_path / 'report.txt').write_text('old')
    with pytest.raises(DestinationExistsError) as error:
        validate_destination('report.txt', str(tmp_path), [tmp_path])
    assert (error.value.kind, error.value.stage) == ('target', 'validation')


def test_symlink_reports_type(tmp_path):
    (tmp_path / 'report.txt').symlink_to(tmp_path / 'missing.txt')
    with pytest.raises(DestinationExistsError) as error:
        validate_destination('report.txt', str(tmp_path), [tmp_path])
    assert error.value.kind == 'symlink'


def test_casefold_collision(tmp_path):
    (tmp_path / 'REPORT.TXT').write_text('old')
    with pytest.raises(DestinationExistsError) as error:
        validate_destination('report.txt', str(tmp_path), [tmp_path])
    assert error.value.kind == 'target_name_equivalent'


def test_unrelated_filename_remains_allowed(tmp_path):
    (tmp_path / '.hidden.txt').write_text('old')
    assert validate_destination('report.txt', str(tmp_path), [tmp_path]) == tmp_path / 'report.txt'
