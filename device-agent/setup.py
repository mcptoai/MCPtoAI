"""Bundle shared-core source inside this agent wheel (never a PyPI dependency)."""
from pathlib import Path
from shutil import copytree
from setuptools import setup
from setuptools.command.build_py import build_py


class BundledCoreBuild(build_py):
    def run(self):
        super().run()
        source = Path(__file__).resolve().parent.parent / "shared-core" / "mcptoai_core"
        if not (source / "__init__.py").is_file():
            raise RuntimeError("Shared core source missing; build from repository root")
        copytree(source, Path(self.build_lib) / "mcptoai_core", dirs_exist_ok=True,
                 ignore=lambda _dir, names: {n for n in names if n == "__pycache__" or n.endswith((".pyc", ".pyo"))})


setup(cmdclass={"build_py": BundledCoreBuild})
