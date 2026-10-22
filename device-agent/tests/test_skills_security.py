"""Skills güvenlik saldırı matrisi (Faz 2): yol geçişi, bağlantılar, değiştirilmiş paket, devre dışı erişim,
özel dosyalar, betik ve kurulum vektörleri. Windows'a özgü yol tuzakları yalnızca Windows'ta çalışır.

Her test bir SALDIRI vektörleri listesini toplu dener; her vektör reddedilmeli, olumlu kontroller ise çalışmaya devam etmeli."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcptoai_agent import skills

SHA = 'a' * 40
DENIED = (PermissionError, ValueError, OSError)


def _can_symlink():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.symlink(tmp, os.path.join(tmp, 'probe'))
            return True
        except (OSError, NotImplementedError):
            return False


CAN_SYMLINK = _can_symlink()


class SecurityBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / 'config'
        patcher = patch.object(skills, 'config_dir', return_value=self.config)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.work = self.root / 'work'
        self.work.mkdir()
        self.outside = self.root / 'outside'
        self.outside.mkdir()
        (self.outside / 'secret.txt').write_text('OUTSIDE-SECRET')
        self.source = self.make_package('source', {
            'one': {'SKILL.extra': '', 'notes.md': 'notes of one', 'run.py': 'print("one ran")\n', 'sub/deep.md': 'deep',
                    'big.txt': 'x' * (skills.MAX_DATA + 10)},
            'two': {'data.json': '{"d": 1}', 'x.py': 'print("two ran")\n'},
        })
        skills.install_package(self.source, 'pack', SHA, approved=True)
        skills.install_package(self.make_package('foreign-source', {'foreign': {'secret.txt': 'FOREIGN-SECRET', 'run.py': 'print(1)\n'}}),
                               'other', SHA, approved=True)

    def make_package(self, folder, skill_files):
        base = self.root / folder
        for name, files in skill_files.items():
            directory = base / name
            directory.mkdir(parents=True)
            (directory / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: {name} skill\n---\nINSTRUCTIONS OF {name.upper()}\n')
            for filename, text in files.items():
                target = directory / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
        return base

    def package(self, name='pack'):
        return self.config / 'skills' / name

    def run_script(self, skill, script, args=None):
        return skills.run_skill_script(skill, script, args or [], allowed_roots=[self.work])

    def assert_denied(self, label, fn):
        try:
            result = fn()
        except DENIED:
            return
        self.fail(f'KABUL EDİLDİ: {label} -> {str(result)[:80]!r}')


class TraversalTests(SecurityBase):
    VECTORS = ['../../../../../../etc/passwd', '..\\..\\..\\windows\\win.ini', './../../x', '/etc/passwd', 'C:\\Windows\\win.ini',
               'C:win.ini', '\\\\server\\share\\x', '//server/share/x', '~/.ssh/id_rsa', 'a/../../../x', 'notes.md\x00.txt',
               'file:///etc/passwd', '', '.', '..', '../..', 'sub/../../../x', 'x' * 600, '../../other/foreign/secret.txt',
               '../../manifest.json', 'notes.md:stream', 'notes.md::$DATA', '../other/foreign/SKILL.md', '../../other/foreign/SKILL.md',
               'big.txt']

    def test_read_skill_file_rejects_every_traversal_vector(self):
        for vector in self.VECTORS:
            self.assert_denied(repr(vector), lambda v=vector: skills.read_skill_file('one', v))

    def test_legitimate_reads_keep_working(self):
        self.assertEqual(skills.read_skill_file('one', 'notes.md'), 'notes of one')
        self.assertEqual(skills.read_skill_file('one', 'sub/deep.md'), 'deep')
        self.assertEqual(skills.read_skill_file('one', 'sub\\deep.md'), 'deep')     # ayraç normalleştirilir
        self.assertEqual(skills.read_skill_file('one', '../two/data.json'), '{"d": 1}')

    def test_script_vectors_are_rejected(self):
        for vector in ['../../x.py', '/bin/sh', 'run.py\x00', 'notes.md', 'RUN.PY', '../../run.py', '../foreign/run.py', '../other/run.py',
                       'sub/../../one/../../run.py', 'C:\\x.py', '..\\two\\x.py\x00', '']:
            self.assert_denied(repr(vector), lambda v=vector: self.run_script('one', v))
        self.assertEqual(self.run_script('one', './run.py')['exit_code'], 0)           # normalleşen yol serbest
        self.assertEqual(self.run_script('one', '../two/x.py')['output'].strip(), 'two ran')

    @unittest.skipIf(os.name == 'nt', 'Windows dosya adında iki nokta üst üste kullanamaz')
    def test_colon_paths_are_rejected_even_when_the_file_really_exists(self):
        # Kural, dosyanın var olmasına bağlı olmamalı (Windows'ta 'dosya:akış' bütünlük özetinin görmediği gizli içeriktir).
        source = self.make_package('colon-source', {'stream': {'a:b': 'HIDDEN'}})
        skills.install_package(source, 'colon', SHA, approved=True)
        self.assert_denied('var olan iki nokta üst üste adlı dosya', lambda: skills.read_skill_file('stream', 'a:b'))

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX')
    def test_special_files_never_hang_or_leak(self):
        os.mkfifo(self.package() / 'one' / 'pipe')
        self.assert_denied('FIFO', lambda: skills.read_skill_file('one', 'pipe'))
        self.assert_denied('dizin', lambda: skills.read_skill_file('one', 'sub'))


class DisabledSkillTests(SecurityBase):
    SIBLING_VECTORS = ['../two/SKILL.md', '../two/data.json', '../two/./SKILL.md', 'sub/../../two/SKILL.md', '../TWO/SKILL.md',
                       '../two//SKILL.md', '../two/../two/SKILL.md', '..\\two\\SKILL.md']

    def test_disabled_skill_is_unreachable_by_every_model_tool(self):
        skills.set_enabled('two', False)
        for vector in self.SIBLING_VECTORS:
            self.assert_denied(f'etkin kardeş üzerinden {vector!r}', lambda v=vector: skills.read_skill_file('one', v))
        self.assert_denied('doğrudan okuma', lambda: skills.read_skill_file('two', 'SKILL.md'))
        self.assert_denied('load_skill', lambda: skills.load_skill('two'))
        self.assert_denied('betik', lambda: self.run_script('two', 'x.py'))
        self.assert_denied('kardeş betik yolu', lambda: self.run_script('one', '../two/x.py'))
        self.assertNotIn('two:', skills.prompt_summary())
        self.assertIn('one:', skills.prompt_summary())
        self.assertFalse(skills.list_skills()['two']['enabled'])
        skills.set_enabled('two', True)                                                 # yeniden etkinleştirince erişim döner
        self.assertIn('INSTRUCTIONS OF TWO', skills.read_skill_file('one', '../two/SKILL.md'))
        self.assertEqual(self.run_script('one', '../two/x.py')['exit_code'], 0)

    def test_disable_only_closes_the_model_tools_not_the_scripts_of_enabled_skills(self):
        # Belgelenmiş sınır: betikler kullanıcı yetkisiyle çalışır; etkin bir skill'in betiği devre dışı kardeşin verisini okuyabilir.
        (self.package() / 'one' / 'reads_two.py').write_text('x')  # bütünlüğü bozar; yerine yeni paket kur
        shutil.rmtree(self.package()); skills._save({k: v for k, v in skills._manifest().items() if v.get('package') != 'pack'})
        source = self.make_package('source2', {
            'one': {'reads_two.py': "import os\nprint(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'two', 'data.json')).read())\n"},
            'two': {'data.json': '{"d": 2}'}})
        skills.install_package(source, 'pack', SHA, approved=True)
        skills.set_enabled('two', False)
        self.assertEqual(self.run_script('one', 'reads_two.py')['output'].strip(), '{"d": 2}')
        self.assert_denied('araçla okuma', lambda: skills.read_skill_file('one', '../two/data.json'))


class TamperTests(SecurityBase):
    def snapshot(self):
        backup = self.root / 'backup'
        shutil.rmtree(backup, ignore_errors=True)
        shutil.copytree(self.package(), backup, symlinks=True)
        return backup

    def restore(self, backup):
        shutil.rmtree(self.package(), ignore_errors=True)
        shutil.copytree(backup, self.package(), symlinks=True)

    def all_tools_deny(self, label):
        self.assert_denied(f'{label}: load_skill', lambda: skills.load_skill('one'))
        self.assert_denied(f'{label}: read_skill_file', lambda: skills.read_skill_file('one', 'notes.md'))
        self.assert_denied(f'{label}: betik', lambda: self.run_script('one', 'run.py'))

    def test_every_kind_of_modification_is_rejected_by_every_tool(self):
        backup = self.snapshot()
        one, two, package = self.package() / 'one', self.package() / 'two', self.package()
        mutations = {
            'SKILL.md değişti': lambda: (one / 'SKILL.md').write_text('değişti'),
            'betik değişti': lambda: (one / 'run.py').write_text('print("evil")'),
            'veri dosyası değişti': lambda: (two / 'data.json').write_text('{"d": 99}'),
            'fazladan dosya': lambda: (one / 'extra.txt').write_text('x'),
            'silinmiş dosya': lambda: (one / 'notes.md').unlink(),
            'bayt kodu eklendi': lambda: ((one / '__pycache__').mkdir(), (one / '__pycache__' / 'run.cpython-312.pyc').write_bytes(b'x')),
            'stdlib gölgeleyen dosya': lambda: (one / 'json.py').write_text('print("shadow")'),
            'skill klasörü yeniden adlandırıldı': lambda: two.rename(package / 'two2'),
            'paket kökünde dosya': lambda: (package / 'stray.txt').write_text('x'),
            'yeni skill klasörü': lambda: ((package / 'three').mkdir(), (package / 'three' / 'SKILL.md').write_text('x')),
            'skill klasörü silindi': lambda: shutil.rmtree(two),
        }
        if CAN_SYMLINK:
            mutations['dosya sembolik bağlantıyla değişti'] = lambda: ((one / 'notes.md').unlink(), os.symlink(self.outside / 'secret.txt', one / 'notes.md'))
            mutations['klasör sembolik bağlantıyla değişti'] = lambda: (shutil.rmtree(two), os.symlink(self.outside, two, target_is_directory=True))
            mutations['yeni sembolik bağlantı'] = lambda: os.symlink(self.outside / 'secret.txt', one / 'link.txt')
        for label, mutate in mutations.items():
            with self.subTest(label):
                mutate()
                self.all_tools_deny(label)
                self.restore(backup)
                self.assertEqual(self.run_script('one', 'run.py')['exit_code'], 0, f'{label}: geri alınınca çalışmalı')
                self.assertIn('INSTRUCTIONS OF ONE', skills.load_skill('one')['content'])

    @unittest.skipUnless(CAN_SYMLINK, 'sembolik bağlantı oluşturulamıyor')
    def test_symlinked_package_folder_is_never_followed(self):
        real = self.root / 'real-package'
        shutil.move(str(self.package()), str(real))
        os.symlink(real, self.package(), target_is_directory=True)
        self.all_tools_deny('paket klasörü bağlantı')


class InstallVectorTests(SecurityBase):
    def hostile(self, name, mutate):
        source = self.make_package(name, {'bad': {'notes.md': 'x'}})
        mutate(source / 'bad')
        return source

    def test_hostile_packages_are_rejected_before_installation(self):
        cases = {
            'dosya bağlantısı': (lambda d: os.symlink(self.outside / 'secret.txt', d / 'l.txt'), CAN_SYMLINK),
            'klasör bağlantısı': (lambda d: os.symlink(self.outside, d / 'ld', target_is_directory=True), CAN_SYMLINK),
            'bayt kodu': (lambda d: ((d / '__pycache__').mkdir(), (d / '__pycache__' / 'x.pyc').write_bytes(b'x')), True),
            '.pyc dosyası': (lambda d: (d / 'x.pyc').write_bytes(b'x'), True),
            'ad uyuşmazlığı': (lambda d: (d / 'SKILL.md').write_text('---\nname: other-name\ndescription: x\n---\n'), True),
            'tire ile başlayan ad': (lambda d: (d / 'SKILL.md').write_text('---\nname: --approve\ndescription: x\n---\n'), True),
            'büyük SKILL.md': (lambda d: (d / 'SKILL.md').write_text('---\nname: bad\ndescription: x\n---\n' + 'a' * (skills.MAX_DOC + 1)), True),
            'çok dosya': (lambda d: [(d / f'f{i}.txt').write_text('x') for i in range(1005)], True),
            'büyük dosya': (lambda d: (d / 'big.bin').write_bytes(b'x' * (skills.MAX_FILE + 1)), True),
            'SKILL.md bir klasör': (lambda d: ((d / 'SKILL.md').unlink(), (d / 'SKILL.md').mkdir()), True),
        }
        for label, (mutate, applicable) in cases.items():
            if not applicable:
                continue
            with self.subTest(label):
                source = self.hostile('hostile-' + label.replace(' ', '-').replace('.', ''), mutate)
                with self.assertRaises(DENIED):
                    skills.install_package(source, 'evil', SHA, approved=True)
                self.assertFalse(self.package('evil').exists())
                self.assertNotIn('bad', skills.list_skills())

    def test_bad_package_names_and_commits_are_rejected(self):
        source = self.make_package('names', {'fine': {}})
        for package in ('../x', '-x', '', 'Pack', 'a b', 'x' * 65, 'a/b'):
            with self.assertRaises(DENIED):
                skills.inspect_package(source, package, SHA)
        for commit in ('main', 'HEAD', 'abc123', 'A' * 40, 'g' * 40, '', 'a' * 41):
            with self.assertRaises(DENIED):
                skills.inspect_package(source, 'fine-pack', commit)
        with self.assertRaises(PermissionError):
            skills.install_package(source, 'fine-pack', SHA, approved=False)


class DataDirectoryTests(SecurityBase):
    def test_data_path_vectors_are_rejected(self):
        for vector in ['../x', '/abs', 'a\\b', 'x:y', '~/.codex/skills/x', '', '..', 'a/../../x', 'a\x00b', 'C:\\x', '\\\\server\\x', 'voice.md:stream']:
            self.assert_denied(repr(vector), lambda v=vector: skills.skill_data_write(v, 'x'))
            self.assert_denied('okuma ' + repr(vector), lambda v=vector: skills.skill_data_read(v))
        self.assert_denied('300 KB', lambda: skills.skill_data_write('youtube/big.txt', 'a' * 300000))
        skills.skill_data_write('~/.codex/youtube/voice.md', 'profil')
        self.assertEqual(skills.skill_data_read('youtube/voice.md'), 'profil')

    @unittest.skipUnless(CAN_SYMLINK, 'sembolik bağlantı oluşturulamıyor')
    def test_symlinks_inside_the_data_directory_cannot_leave_it(self):
        skills.skill_data_write('youtube/voice.md', 'profil')
        link = skills._data() / 'leak'
        os.symlink(self.outside, link, target_is_directory=True)
        self.assert_denied('bağlantı üzerinden yazma', lambda: skills.skill_data_write('leak/pwn.txt', 'x'))
        self.assert_denied('bağlantı üzerinden okuma', lambda: skills.skill_data_read('leak/secret.txt'))
        self.assertFalse((self.outside / 'pwn.txt').exists())


@unittest.skipUnless(os.name == 'nt', 'Windows yol tuzakları')
class WindowsPathTests(SecurityBase):
    def test_windows_specific_path_tricks_are_rejected(self):
        for vector in ['notes.md:evil', 'notes.md::$DATA', 'NUL', 'con', 'aux.txt', 'COM1', 'lpt9.md', 'sub/NUL.txt', 'C:foo', '\\foo', '\\\\?\\C:\\Windows\\win.ini',
                       '\\\\server\\share\\x', 'notes.md.', 'notes.md ']:
            if vector in ('notes.md.', 'notes.md '):
                continue  # Windows bunları gerçek dosyaya çözer; zararsız takma ad, aşağıda devre dışı kardeş için denenir
            self.assert_denied(repr(vector), lambda v=vector: skills.read_skill_file('one', v))

    def test_trailing_dot_and_space_aliases_cannot_reach_a_disabled_sibling(self):
        skills.set_enabled('two', False)
        for vector in ['../two./SKILL.md', '../two /SKILL.md', '../TWO/SKILL.md', '..\\two.\\SKILL.md']:
            self.assert_denied(repr(vector), lambda v=vector: skills.read_skill_file('one', v))


@unittest.skipUnless(os.name == 'nt', 'Windows junction')
class WindowsJunctionTests(SecurityBase):
    def junction(self, link, target):
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def tools_deny(self, label):
        self.assert_denied(label + ': load_skill', lambda: skills.load_skill('one'))
        self.assert_denied(label + ': read_skill_file', lambda: skills.read_skill_file('one', 'notes.md'))
        self.assert_denied(label + ': betik', lambda: self.run_script('one', 'run.py'))

    def test_junctions_are_rejected_by_every_tool_like_symlinks(self):
        # is_symlink() junction için False döner; paket aynı içerikli bir kopyaya junction yapılınca özetler tutar,
        # yine de hiçbir araç bağlantıyı takip etmemeli (önceden read_skill_file kabul ediyordu).
        self.assertFalse(Path(self.package()).is_symlink())
        backup = self.root / 'package-copy'
        shutil.copytree(self.package(), backup)
        shutil.rmtree(self.package())
        self.junction(self.package(), backup)
        self.assertTrue(skills._is_link(self.package()))
        self.tools_deny('paket junction')
        self.assert_denied('paket junction: kaldırma', lambda: skills.remove_package('pack'))
        self.assertTrue((backup / 'one' / 'notes.md').exists(), 'kaldırma bağlantının gösterdiği yere dokunmamalı')
        self.assertIn('one', skills.list_skills(), 'reddedilen kaldırma yarım iş bırakmamalı')
        os.rmdir(self.package())
        shutil.copytree(backup, self.package())
        self.assertEqual(self.run_script('one', 'run.py')['exit_code'], 0)
        two_copy = self.root / 'two-copy'
        shutil.copytree(self.package() / 'two', two_copy)
        shutil.rmtree(self.package() / 'two')
        self.junction(self.package() / 'two', two_copy)
        self.tools_deny('skill klasörü junction')
        os.rmdir(self.package() / 'two')
        shutil.copytree(two_copy, self.package() / 'two')
        self.assertEqual(self.run_script('one', 'run.py')['exit_code'], 0)


class LinkHelperTests(SecurityBase):
    @unittest.skipUnless(CAN_SYMLINK, 'sembolik bağlantı oluşturulamıyor')
    def test_is_link_recognizes_symlinks_and_plain_paths(self):
        link = self.root / 'link'
        os.symlink(self.outside, link, target_is_directory=True)
        self.assertTrue(skills._is_link(link))
        self.assertFalse(skills._is_link(self.outside))
        self.assertFalse(skills._is_link(self.root / 'yok'))


if __name__ == '__main__':
    unittest.main()
