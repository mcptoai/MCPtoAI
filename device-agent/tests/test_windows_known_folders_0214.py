"""Win #124: redirected known folders and cloud-placeholder reparse policy."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from mcptoai_agent.folder_errors import folder_error_reason


class FolderReasonsTests(unittest.TestCase):
    def test_actionable_short_messages_without_private_path(self):
        samples=[
            (PermissionError('subfolder_workspace_not_approved'),'unapproved_root'),
            (PermissionError('subfolder_reparse_junction_or_mount_point:0xa0000003'),'reparse_junction'),
            (PermissionError('subfolder_reparse_symlink:0xa000000c'),'reparse_symlink'),
            (PermissionError('subfolder_reparse_unknown_reparse_tag:0x12345678'),'reparse_unknown'),
            (FileExistsError('subfolder_name_collision'),'already_exists'),
        ]
        for error,category in samples:
            with self.subTest(category=category):
                result=folder_error_reason(error)
                self.assertTrue(result.startswith(category+':'))
                self.assertNotIn('C:\\Users',result)


@unittest.skipUnless(os.name=='nt','Windows shell folders and native tags')
class WindowsOneDriveTests(unittest.TestCase):
    def test_cfapi_tag_allowlist_and_junction_denial(self):
        from mcptoai_core._windows_subfolders import safe_directory_reparse_tag
        for num in range(16):
            with self.subTest(num=num):
                self.assertTrue(safe_directory_reparse_tag(0x9000001A | (num<<12)))
        for tag in (0xA000000C,0xA0000003,0,0x8000001B,0xA000001F,0x9000001B,0x8000001A):
            with self.subTest(tag=hex(tag)):
                self.assertFalse(safe_directory_reparse_tag(tag))

    def test_all_three_known_folders_via_shell_api(self):
        from mcptoai_agent.windows_known_folders import get_known_folder, default_windows_roots
        roots=default_windows_roots()
        for kind in ('Desktop','Documents','Downloads'):
            with self.subTest(kind=kind):
                p=get_known_folder(kind)
                self.assertTrue(p.is_dir())
                self.assertTrue(p.is_absolute())
                self.assertIn(p,roots)

    def test_windows_default_roots_use_knownfolder_not_profile_guess(self):
        from mcptoai_agent.config import _roots
        from mcptoai_agent.windows_known_folders import get_known_folder
        with patch.dict(os.environ, {'MCP_ALLOWED_ROOTS':''}):
            import mcptoai_agent.config as config
            with patch.object(config,'USER_SETTINGS',{}):
                roots=_roots()
        self.assertIn(get_known_folder('Desktop'),roots)
        self.assertIn(get_known_folder('Documents'),roots)

    def test_selected_parent_advertises_only_its_known_folder_children(self):
        from mcptoai_agent.windows_known_folders import get_known_folder
        import mcptoai_agent.config as config
        home=Path.home().resolve()
        with patch.dict(os.environ, {'MCP_ALLOWED_ROOTS':''}), \
             patch.object(config,'USER_SETTINGS',{'workspace_root':str(home)}):
            roots=config._roots()
        self.assertEqual(roots[0],home)
        for kind in ('Desktop','Documents','Downloads'):
            known=get_known_folder(kind)
            if known.is_relative_to(home):
                self.assertIn(known,roots)
        # A narrower custom root must not advertise siblings outside it.
        with patch.dict(os.environ, {'MCP_ALLOWED_ROOTS':''}), \
             patch.object(config,'USER_SETTINGS',{'workspace_root':str(get_known_folder('Desktop'))}):
            roots=config._roots()
        self.assertEqual(roots,[get_known_folder('Desktop')])

    def test_preflight_explains_redirected_workspace_and_existing_folder(self):
        from mcptoai_agent.windows_known_folders import get_known_folder
        import mcptoai_agent.config as config
        from mcptoai_agent.preflight import validate
        root=get_known_folder('Desktop')
        with patch.dict(os.environ, {'MCP_ALLOWED_ROOTS':''}), \
             patch.object(config,'USER_SETTINGS',{'workspace_root':str(Path.home().resolve())}):
            cfg=type('Cfg',(),{'allowed_roots':config._roots()})()
        name='MCPtoAI124PreflightProbe'
        target=root/name
        if target.exists():self.skipTest('probe target already exists')
        args={'workspace':str(root),'relative_path':name}
        reason,metadata=validate('create_folder',args,cfg)
        self.assertIsNone(reason,reason)
        self.assertEqual(metadata['relative_path'],name)
        try:
            target.mkdir()
            reason,_=validate('create_folder',args,cfg)
            self.assertIsNone(reason,reason)
        finally:
            if target.is_dir() and not any(target.iterdir()):target.rmdir()
        reason,_=validate('create_folder',{'workspace':str(root),'relative_path':'../outside'},cfg)
        self.assertTrue(reason.startswith('invalid_relative_path'),reason)
        with tempfile.TemporaryDirectory(prefix='mcptoai-124-unapproved-') as external:
            reason,_=validate('create_folder',{'workspace':external,'relative_path':'demo'},cfg)
            self.assertTrue(reason.startswith('unapproved_root:'),reason)

    def test_nested_deneme_2026_under_redirected_desktop(self):
        from mcptoai_agent.windows_known_folders import get_known_folder
        from mcptoai_agent.sensitive_paths import check_path
        from mcptoai_core.safe_subfolders import create_subfolder
        root=get_known_folder('Desktop')
        parent=root/'MCPtoAI124DenemeProbe'
        child=parent/'2026'
        if parent.exists():self.skipTest('probe target already exists')
        try:
            result=create_subfolder(str(root),'MCPtoAI124DenemeProbe/2026',[root],check_path=check_path)
            self.assertEqual(result,child)
            self.assertTrue(child.is_dir())
            with self.assertRaises(FileExistsError):
                create_subfolder(str(root),'MCPtoAI124DenemeProbe/2026',[root],check_path=check_path)
        finally:
            if child.is_dir() and not any(child.iterdir()):child.rmdir()
            if parent.is_dir() and not any(parent.iterdir()):parent.rmdir()

    def test_real_cloud_redirected_desktop_and_junction(self):
        from mcptoai_agent.windows_known_folders import get_known_folder
        from mcptoai_core.safe_subfolders import create_subfolder,plan_inbound_subfolder,ensure_inbound_subfolder
        root=get_known_folder('Desktop')
        guard=lambda *_args,**_kwargs: None
        # The directory is user-authorized; never overwrite anything present.
        name='MCPtoAI124KnownFolderProbe'
        target=root/name
        if target.exists() or target.is_symlink(): self.skipTest('probe name in use')
        try:
            result=create_subfolder(str(root),name,[root],check_path=guard)
            self.assertEqual(result,target)
            self.assertTrue(target.is_dir())
            result.rmdir()
            planned,missing=plan_inbound_subfolder(str(root),name,[root],check_path=guard)
            self.assertTrue(missing)
            self.assertEqual(planned,target)
            created=ensure_inbound_subfolder(str(root),name,[root],check_path=guard)
            self.assertEqual(created,target)
            created.rmdir()
        finally:
            if target.is_dir() and not any(target.iterdir()):target.rmdir()
        with tempfile.TemporaryDirectory(prefix='mcptoai-124-test-') as external:
            link=root/'MCPtoAI124JunctionProbe'
            if link.exists() or link.is_symlink(): self.skipTest('junction probe name in use')
            try:
                p=subprocess.run(['cmd','/c','mklink','/J',str(link),external],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stderr)
                with self.assertRaises((PermissionError,FileExistsError)):
                    plan_inbound_subfolder(str(root),'MCPtoAI124JunctionProbe/bad',[root],check_path=guard)
                self.assertFalse((Path(external)/'bad').exists())
            finally:
                if link.exists():link.rmdir()

if __name__=='__main__':unittest.main()
