"""Regression: existing safe exact directory is success, unsafe collisions fail closed."""
import asyncio
from dataclasses import replace
from pathlib import Path
import pytest
from mcptoai_agent.config import settings
from mcptoai_agent.preflight import validate
from mcptoai_agent.folder_errors import existing_approved_folder, localized_folder_status, folder_error_localized
from mcptoai_agent.sensitive_paths import check_path


def test_existing_folder_is_success_in_preflight(tmp_path):
    (tmp_path/'test').mkdir()
    (tmp_path/'test'/'2026').mkdir()
    cfg=replace(settings,allowed_roots=[tmp_path])
    reason,meta=validate('create_folder',{'workspace':str(tmp_path),'relative_path':r'test\2026'},cfg)
    assert reason is None
    assert meta['already_exists'] is True and meta['folders_to_create']==[]
    assert existing_approved_folder(str(tmp_path),r'test\2026',[tmp_path],check_path=check_path)==tmp_path/'test'/'2026'
    assert list((tmp_path/'test').iterdir())==[tmp_path/'test'/'2026']



@pytest.mark.parametrize('lang',('en','tr','de','fr','es','zh','ar'))
def test_preflight_denials_are_localized_with_stable_reason(tmp_path, lang):
    cfg=replace(settings,allowed_roots=[tmp_path])
    reason,_=validate('create_folder',{'workspace':str(tmp_path),'relative_path':'../escape'},cfg,language=lang)
    assert reason.startswith('invalid_relative_path: '),reason
    root=tmp_path.parent/(tmp_path.name+'-sibling');root.mkdir(exist_ok=True)
    reason,_=validate('create_folder',{'workspace':str(root),'relative_path':'new'},cfg,language=lang)
    assert reason.startswith('unapproved_root: '),reason
    assert 'C:\\Users' not in reason

def test_new_nested_folder_still_requires_real_create(tmp_path):
    cfg=replace(settings,allowed_roots=[tmp_path])
    reason,meta=validate('create_folder',{'workspace':str(tmp_path),'relative_path':'deneme/2026'},cfg)
    assert reason is None and meta['folders_to_create']==['deneme','deneme/2026']
    assert not (tmp_path/'deneme').exists()


def test_unsafe_existing_not_success(tmp_path):
    (tmp_path/'Test').mkdir()
    (tmp_path/'file').write_text('hello')
    cfg=replace(settings,allowed_roots=[tmp_path])
    assert validate('create_folder',{'workspace':str(tmp_path),'relative_path':'test'},cfg)[0] is not None
    assert validate('create_folder',{'workspace':str(tmp_path),'relative_path':'file'},cfg)[0] is not None
    with pytest.raises((FileExistsError,PermissionError)):
        existing_approved_folder(str(tmp_path),'file',[tmp_path],check_path=check_path)
    outside=tmp_path.parent/(tmp_path.name+'-outside');outside.mkdir(exist_ok=True)
    (tmp_path/'link').symlink_to(outside,target_is_directory=True)
    with pytest.raises((FileExistsError,PermissionError)):
        existing_approved_folder(str(tmp_path),'link',[tmp_path],check_path=check_path)


@pytest.mark.parametrize('lang',('en','tr','de','fr','es','zh','ar'))
def test_seven_locales_keep_machine_reason_codes(lang):
    assert localized_folder_status('already_exists',lang).startswith('already_exists: ')
    assert folder_error_localized(PermissionError('subfolder_workspace_not_approved'),lang).startswith('unapproved_root: ')
    assert folder_error_localized(FileExistsError('subfolder_name_collision'),lang).startswith('name_collision: ')


def test_real_tool_existing_returns_success_without_mutation(tmp_path):
    try:
        from fastmcp import Client
    except ImportError:
        pytest.skip("FastMCP Client unavailable in this local test environment")
    from mcptoai_agent.tools.host_tools import build_server
    (tmp_path/'test').mkdir()
    async def run():
        server=build_server(replace(settings,allowed_roots=[tmp_path]))
        async with Client(server) as client:
            for lang in ('en','tr','de','fr','es','zh','ar'):
                reply=await client.call_tool('create_folder',{'workspace':str(tmp_path),'relative_path':'test','language':lang},raise_on_error=False)
                body=''.join(x.text for x in reply.content if hasattr(x,'text'))
                assert 'already_exists:' in body and '[ERROR]' not in body,(lang,body)
    asyncio.run(run())
