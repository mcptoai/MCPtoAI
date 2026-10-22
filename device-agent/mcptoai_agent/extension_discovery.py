"""Üçüncü taraf depolarını çalıştırmadan sınıflandıran keşif katmanı."""
from __future__ import annotations
from pathlib import Path
from . import skills


def inspect_repository(root: Path, package: str, commit: str) -> dict:
    """Tanıma yalnızca dosya adları ve skill manifestleriyle yapılır; kod çalıştırılmaz."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError('Repository directory not found')
    roots = skills.find_skill_roots(root)
    skill_root = roots[0] if roots else None
    if skill_root:
        preview = skills.inspect_package(skill_root, package, commit)
        return {'kind': 'skill-package', 'supported': True, 'installable': True,
                'requires_user_approval': True, 'execution_allowed': False,
                'skill_root': skill_root.relative_to(root).as_posix(),
                'ignored_skill_folders': [p.relative_to(root).as_posix() for p in roots[1:]],
                'package': package, 'commit': commit, 'preview_digest': skills.preview_digest(preview), 'preview': preview}
    # Diğer proje türlerini yalnızca işaretle; Faz 1'de kurulumları kapalıdır.
    names = {p.name for p in root.iterdir() if p.is_file()}
    if 'mcp.json' in names or '.mcp.json' in names:
        kind = 'mcp-server-candidate'
    elif 'pyproject.toml' in names or 'package.json' in names:
        kind = 'application-or-cli-candidate'
    else:
        kind = 'unknown'
    return {'kind': kind, 'supported': False, 'installable': False,
            'requires_user_approval': True, 'execution_allowed': False,
            'reason': 'Unsupported repository type: no compatible SKILL.md package detected. No code was executed.'}
