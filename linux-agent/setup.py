"""Bundle shared-core into Linux wheel and standalone source distribution."""
from pathlib import Path
from shutil import copytree, rmtree
from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

ROOT = Path(__file__).resolve().parent
STAGED = ROOT / '_bundled_core' / 'mcptoai_core'
SOURCE = ROOT.parent / 'shared-core' / 'mcptoai_core'


def copy_core(destination):
    source = SOURCE if (SOURCE / '__init__.py').is_file() else STAGED
    if not (source / '__init__.py').is_file():
        raise RuntimeError('Shared core source missing from checkout and source distribution')
    copytree(source, destination, dirs_exist_ok=True,
             ignore=lambda _dir, names: {n for n in names if n == '__pycache__' or n.endswith(('.pyc', '.pyo'))})


class BundledCoreBuild(build_py):
    def run(self):
        super().run()
        copy_core(Path(self.build_lib) / 'mcptoai_core')


class BundledCoreSdist(sdist):
    def run(self):
        if STAGED.exists():
            raise RuntimeError('Refusing to overwrite pre-existing bundled source')
        try:
            copy_core(STAGED)
            super().run()
        finally:
            rmtree(STAGED.parent, ignore_errors=True)


setup(cmdclass={'build_py': BundledCoreBuild, 'sdist': BundledCoreSdist})
