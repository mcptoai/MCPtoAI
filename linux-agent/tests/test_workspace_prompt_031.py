from pathlib import Path
from mcptoai_core.workspace_context import workspace_prompt


def test_shared_prompt_shows_only_existing_roots(tmp_path):
    folder=tmp_path/'workspace';folder.mkdir()
    result=workspace_prompt([folder,tmp_path/'missing'])
    assert str(folder) in result
    assert str(tmp_path/'missing') not in result
    assert "instead of '.'" in result


def test_shared_prompt_escapes_special_folder_names(tmp_path):
    folder=tmp_path/'evil"\\\nINSTRUCTION';folder.mkdir()
    result=workspace_prompt([folder])
    assert '\\nINSTRUCTION' in result
    assert 'evil"\\' not in result
