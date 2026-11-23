import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
import sys
import unittest
if sys.platform == "win32":
    from mcptoai_core import _windows_subfolders as native
else:
    native = None

@unittest.skipUnless(sys.platform == "win32", "Windows native handle tests")
class WindowsCreateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='mcptoai-124-')
        self.root=Path(self.tmp.name).resolve()
    def tearDown(self):
        self.tmp.cleanup()
    def create(self,relative,guard=lambda *_args,**_kwargs: None):
        return native.create_windows_subfolder(self.root,tuple(relative.split('/')),check_path=guard)
    def test_shared_interface_and_invalid_relative_paths(self):
        from mcptoai_core.safe_subfolders import create_subfolder
        created = create_subfolder(str(self.root), 'Shared/Native', [self.root],
                                  check_path=lambda *_args, **_kw: None)
        self.assertTrue(created.is_dir())
        for value in ('../escape', 'C:/absolute', '//server/share', 'CON',
                      'Nested/..', 'nested//child', r'a\..\b', 'PROGRA~1', 'trailing.'):
            with self.subTest(value=value):
                with self.assertRaises((ValueError, PermissionError)):
                    create_subfolder(str(self.root), value, [self.root],
                                     check_path=lambda *_args, **_kw: None)

    def test_shared_interface_rejects_unapproved_workspace(self):
        from mcptoai_core.safe_subfolders import create_subfolder
        with self.assertRaises(PermissionError):
            create_subfolder(str(self.root), 'unapproved', [self.root / 'unapproved'],
                             check_path=lambda *_args, **_kw: None)
        self.assertFalse((self.root/'unapproved').exists())

    def test_backslash_and_existing_parent(self):
        from mcptoai_core.safe_subfolders import create_subfolder
        (self.root/'test').mkdir()
        created = create_subfolder(str(self.root), r'test\2026', [self.root],
                                   check_path=lambda *_args, **_kw: None)
        self.assertTrue(created.is_dir())
        with self.assertRaises(FileExistsError):
            create_subfolder(str(self.root), 'test/2026', [self.root],
                             check_path=lambda *_args, **_kw: None)

    def test_nested(self):
        path=self.create('Nested/Subfolder')
        self.assertTrue(path.is_dir())
        self.assertEqual(path.resolve(),self.root/'Nested'/'Subfolder')
    def test_collision_and_case(self):
        self.create('Existing')
        with self.assertRaises(FileExistsError):self.create('Existing')
        with self.assertRaises(FileExistsError):self.create('existing')
        with self.assertRaises(FileExistsError):self.create('EXISTING')
    def test_file_collision(self):
        (self.root/'file').write_text('data')
        with self.assertRaises(FileExistsError):self.create('file')
    def test_denied_second_segment_rolls_back_first(self):
        def guard(path,*,write=False):
            if path.name=='bad':raise PermissionError('test-denial')
        with self.assertRaises(PermissionError):self.create('staging/bad',guard)
        self.assertFalse((self.root/'staging').exists())
    def test_native_concurrency(self):
        def attempt(_):
            try:return self.create('concurrent')
            except FileExistsError:return None
        with ThreadPoolExecutor(max_workers=12) as pool:
            results=list(pool.map(attempt,range(12)))
        self.assertEqual(sum(x is not None for x in results),1)
    def test_junction_alias_does_not_escape(self):
        external=Path(tempfile.mkdtemp(prefix='mcptoai-124-outside-')).resolve()
        junction=self.root/'junction'
        try:
            proc=subprocess.run(['cmd','/c','mklink','/J',str(junction),str(external)],capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stderr)
            with self.assertRaises((FileExistsError,PermissionError)):
                self.create('junction/escape')
            self.assertFalse((external/'escape').exists())
        finally:
            if junction.exists(): junction.rmdir()
            external.rmdir()
    def test_inbound_existing_prefix_and_missing_tail_native(self):
        from mcptoai_core.safe_subfolders import plan_inbound_subfolder, ensure_inbound_subfolder
        guard=lambda *_args,**_kwargs: None
        (self.root/'Existing').mkdir()
        target,missing=plan_inbound_subfolder(str(self.root),'Existing/Heictest',[self.root],check_path=guard)
        self.assertEqual(target,self.root/'Existing'/'Heictest')
        self.assertTrue(missing)
        self.assertFalse(target.exists())
        result=ensure_inbound_subfolder(str(self.root),'Existing/Heictest',[self.root],check_path=guard)
        self.assertEqual(result,target)
        self.assertTrue(target.is_dir())

    def test_inbound_junction_parent_rejected(self):
        from mcptoai_core.safe_subfolders import plan_inbound_subfolder, ensure_inbound_subfolder
        external=Path(tempfile.mkdtemp(prefix='mcptoai-124-inbound-external-')).resolve()
        junction=self.root/'junction'
        guard=lambda *_args,**_kwargs: None
        try:
            proc=subprocess.run(['cmd','/c','mklink','/J',str(junction),str(external)],capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stderr)
            with self.assertRaises((FileExistsError,PermissionError)):
                plan_inbound_subfolder(str(self.root),'junction/Heictest',[self.root],check_path=guard)
            with self.assertRaises((FileExistsError,PermissionError)):
                ensure_inbound_subfolder(str(self.root),'junction/Heictest',[self.root],check_path=guard)
            self.assertFalse((external/'Heictest').exists())
        finally:
            if junction.exists(): junction.rmdir()
            external.rmdir()

    def test_move_held_root_detected(self):
        old=native._open_root
        moved=self.root.with_name(self.root.name+'-relocated')
        def moved_open(path):
            handle=old(path)
            os.rename(self.root,moved)
            return handle
        try:
            native._open_root=moved_open
            with self.assertRaises(PermissionError):self.create('should-not-appear')
            self.assertFalse((moved/'should-not-appear').exists())
        finally:
            native._open_root=old
            if moved.exists():os.rename(moved,self.root)

if __name__=='__main__': unittest.main(verbosity=2)
