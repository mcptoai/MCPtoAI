from dataclasses import replace
import os
from pathlib import Path
import pytest
from mcptoai_core.safe_subfolders import create_subfolder
from mcptoai_agent.sensitive_paths import check_path
from mcptoai_agent.preflight import validate
from mcptoai_agent.config import settings


def test_nested_creation_and_explicit_approval_path(tmp_path):
    cfg = replace(settings, allowed_roots=[tmp_path])
    err, meta = validate('create_folder', {'workspace': str(tmp_path), 'relative_path': 'new/nested'}, cfg)
    assert err is None and meta['file_action'] == 'create folder'
    result = create_subfolder(str(tmp_path), 'new/nested', cfg.allowed_roots, check_path=check_path)
    assert result == tmp_path/'new'/'nested' and result.is_dir()
    if os.name != "nt":
        assert result.stat().st_mode & 0o077 == 0
    with pytest.raises(PermissionError):
        create_subfolder(str(tmp_path), 'other', [tmp_path/'new'], check_path=check_path)


@pytest.mark.parametrize('name', ['', '.', '..', 'x/../escape', r'x\..\escape', r'x\C:evil', '/abs', '\\windows', 'C:/drive',
                                  'x//y', 'x/.', 'x/..', 'CON', 'AUX.txt', 'a ', 'a.',
                                  'a\x00b', 'x/'*20+'z'])
def test_reject_invalid_components(tmp_path, name):
    cfg = replace(settings, allowed_roots=[tmp_path])
    with pytest.raises((ValueError, PermissionError)):
        create_subfolder(str(tmp_path), name, cfg.allowed_roots, check_path=check_path)
    assert not (tmp_path/'escape').exists()


def test_symlink_and_collision_denied(tmp_path):
    outside = tmp_path.parent / (tmp_path.name+'outside'); outside.mkdir(exist_ok=True)
    (tmp_path/'escape').symlink_to(outside, target_is_directory=True)
    with pytest.raises((FileExistsError, PermissionError)):
        create_subfolder(str(tmp_path), 'escape/created', [tmp_path], check_path=check_path)
    assert not (outside/'created').exists()
    (tmp_path/'Alias').mkdir()
    with pytest.raises(FileExistsError):
        create_subfolder(str(tmp_path), 'alias', [tmp_path], check_path=check_path)


def test_existing_name_not_merged_and_rollback(tmp_path):
    (tmp_path/'exists').mkdir()
    with pytest.raises(FileExistsError):
        create_subfolder(str(tmp_path), 'exists', [tmp_path], check_path=check_path)
    assert not (tmp_path/'new').exists()


def test_preflight_does_not_expand_roots(tmp_path):
    other = tmp_path.parent / (tmp_path.name + 'other')
    other.mkdir(exist_ok=True)
    cfg = replace(settings, allowed_roots=[tmp_path])
    err, _ = validate('create_folder', {'workspace':str(other),'relative_path':'new'},cfg)
    assert err is not None
    assert not (other/'new').exists()


def test_write_file_cannot_implicitly_create_folder(tmp_path):
    cfg = replace(settings, allowed_roots=[tmp_path])
    err, _ = validate('write_file', {'path':str(tmp_path/'missing'/'f.txt'), 'content':'x'},cfg)
    assert 'Parent folder' in err


def test_policy_forces_local_confirmation_even_if_config_auto():
    import asyncio
    from mcptoai_agent.policy import ToolPolicy, Decision
    policy = ToolPolicy(rules={'create_folder': Decision.AUTO})
    calls = []
    async def approver(name, args):
        calls.append((name, args)); return False
    allowed, reason = asyncio.run(policy.authorize('create_folder',
        {'workspace':'/tmp/example','relative_path':'draft'}, approver))
    assert not allowed and reason == 'user_denied' and len(calls) == 1


def test_sensitive_folder_name_rejected(tmp_path):
    cfg = replace(settings, allowed_roots=[tmp_path])
    for relative in ('.ssh/keys', '.config/gh', 'secrets/.env'):
        error, _ = validate('create_folder', {'workspace':str(tmp_path),'relative_path':relative},cfg)
        assert error is not None
        assert not (tmp_path/relative).exists()


def test_parallel_same_name_only_one_wins(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    def attempt(_):
        try: return create_subfolder(str(tmp_path), 'parent/child', [tmp_path], check_path=check_path)
        except FileExistsError: return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert sum(x is not None for x in results) == 1
    assert (tmp_path/'parent'/'child').is_dir()


def test_staged_directory_rollback_on_sensitive_name(tmp_path):
    with pytest.raises(PermissionError):
        create_subfolder(str(tmp_path), 'new/.ssh', [tmp_path], check_path=check_path)
    assert not (tmp_path/'new').exists()


def test_reuses_safe_intermediate_and_normalizes_backslash(tmp_path):
    (tmp_path/'test').mkdir()
    cfg = replace(settings, allowed_roots=[tmp_path])
    err, meta = validate('create_folder', {'workspace':str(tmp_path),'relative_path':r'test\2026'},cfg)
    assert err is None and meta['folders_to_create'] == ['test/2026']
    assert not (tmp_path/'test'/'2026').exists()
    created = create_subfolder(str(tmp_path),r'test\2026',[tmp_path],check_path=check_path)
    assert created.is_dir()
    with pytest.raises(FileExistsError):
        create_subfolder(str(tmp_path),'test/2026',[tmp_path],check_path=check_path)


def test_approval_preflight_lists_all_missing_components(tmp_path):
    cfg = replace(settings, allowed_roots=[tmp_path])
    err, meta = validate('create_folder', {'workspace':str(tmp_path),'relative_path':'deneme/2026'},cfg)
    assert err is None and meta['folders_to_create']==['deneme','deneme/2026']
    assert not (tmp_path/'deneme').exists()
    assert create_subfolder(str(tmp_path),'deneme/2026',[tmp_path],check_path=check_path).is_dir()
