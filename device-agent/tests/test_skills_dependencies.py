"""Faz 1 kararı: eksik Python bağımlılığı açık hata verir; MCPtoAI hiçbir paketi kendisi kurmaz."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcptoai_agent import skills

SHA = 'a' * 40


class DependencyErrorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patcher = patch.object(skills, 'config_dir', return_value=self.root / 'config')
        patcher.start()
        self.addCleanup(patcher.stop)
        base = self.root / 'source'
        for name, files in {
            'one': {'absent.py': 'import mcptoai_absent_dep\n', 'nested.py': 'import mcptoai_absent_dep.sub.mod\n',
                    'sibling.py': 'import helpers\n', 'mixed.py': 'import helpers\nimport mcptoai_absent_dep\n',
                    'fails.py': 'raise ValueError("ordinary failure")\n', 'ok.py': 'print("fine")\n'},
            'two': {'helpers.py': 'VALUE = 1\n'},
        }.items():
            directory = base / name
            directory.mkdir(parents=True)
            (directory / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: {name}\n---\n')
            for filename, text in files.items():
                (directory / filename).write_text(text)
        skills.install_package(base, 'pack', SHA, approved=True)

    def run_script(self, script):
        return skills.run_skill_script('one', script, [], allowed_roots=[self.root])

    def test_missing_package_gets_a_structured_error_and_tells_the_model_not_to_install(self):
        result = self.run_script('absent.py')
        self.assertEqual(result['exit_code'], 1)
        self.assertEqual(result['error'], 'missing_python_dependency')
        self.assertEqual(result['missing_modules'], ['mcptoai_absent_dep'])
        self.assertIn('does not install packages automatically', result['message'])
        self.assertIn('do NOT install anything yourself', result['message'])
        self.assertNotIn('pip install', result['message'])
        self.assertTrue(result['python'])
        self.assertIn('ModuleNotFoundError', result['output'])  # özgün hata çıktısı da korunur

    def test_nested_import_reports_the_top_level_package(self):
        self.assertEqual(self.run_script('nested.py')['missing_modules'], ['mcptoai_absent_dep'])

    def test_module_that_belongs_to_the_package_is_a_path_problem_not_a_missing_package(self):
        result = self.run_script('sibling.py')  # helpers.py kardeş skill'de, içe aktarma yoluna eklenmemiş
        self.assertEqual(result['error'], 'package_module_not_found')
        self.assertEqual(result['missing_modules'], ['helpers'])
        self.assertIn('installed nothing', result['message'])

    def test_a_local_module_never_hides_a_missing_external_package(self):
        # Bir betik tek seferde yalnızca ilk eksik içe aktarmada durur; ikisini birden gösteren çıktı (ör. try/except
        # zinciri) sentetik izle sınanır: yerel modül raporlanmaz, dış paket raporlanır.
        package_root = self.root / 'config' / 'skills' / 'pack'
        raw = b"ModuleNotFoundError: No module named 'helpers'\nModuleNotFoundError: No module named 'mcptoai_absent_dep'\n"
        report = skills._dependency_report(raw, '/usr/bin/python3', package_root)
        self.assertEqual(report['error'], 'missing_python_dependency')
        self.assertEqual(report['missing_modules'], ['mcptoai_absent_dep'])

    def test_ordinary_failures_and_successes_carry_no_dependency_error(self):
        failed = self.run_script('fails.py')
        self.assertEqual(failed['exit_code'], 1)
        self.assertNotIn('error', failed)
        ok = self.run_script('ok.py')
        self.assertEqual(ok['exit_code'], 0)
        self.assertNotIn('error', ok)

    def test_known_import_names_map_to_pip_names_for_the_user(self):
        raw = b"Traceback...\nModuleNotFoundError: No module named 'PIL'\nModuleNotFoundError: No module named 'lxml.etree'\n"
        report = skills._dependency_report(raw, '/usr/bin/python3', self.root)
        self.assertEqual(report['missing_modules'], ['PIL', 'lxml'])
        self.assertEqual(report['pip_names'], {'PIL': 'Pillow'})  # bilinmeyen adlar için tahmin yürütülmez
        self.assertEqual(report['python'], '/usr/bin/python3')

    def test_pip_is_never_executed(self):
        commands = []
        real_run = subprocess.run

        def recording_run(cmd, *args, **kwargs):
            commands.append(list(cmd))
            return real_run(cmd, *args, **kwargs)
        with patch.object(skills.subprocess, 'run', recording_run):
            self.run_script('absent.py')
        self.assertTrue(commands)
        for command in commands:
            self.assertNotIn('pip', ' '.join(command).lower().replace('-m pip', 'pip'))
            self.assertEqual(command[-1].endswith('absent.py'), True)


if __name__ == '__main__':
    unittest.main()
