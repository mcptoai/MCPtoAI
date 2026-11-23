"""Single containment policy for all Agent filesystem tools.

Roots are resolved once by Settings._roots (including SHGetKnownFolderPath on
Windows). A tool must never infer an additional root from a request path:
explicit overrides and narrower user-selected workspaces remain authoritative.
"""
from __future__ import annotations
from pathlib import Path
from collections.abc import Iterable


def within_allowed_roots(path: Path, roots: Iterable[Path]) -> bool:
    candidate = Path(path).expanduser().resolve(strict=False)
    for root in roots:
        approved = Path(root).expanduser().resolve(strict=False)
        if candidate == approved or candidate.is_relative_to(approved):
            return True
    return False
