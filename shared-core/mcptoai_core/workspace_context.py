"""Trusted workspace scope instructions shared by Desktop and Linux agents."""
from __future__ import annotations
import json
from pathlib import Path


def workspace_prompt(roots: list[Path]) -> str:
    # Only existing configured roots are advertised. JSON-escaping prevents a
    # malicious folder name from altering the surrounding instruction framing.
    valid = [str(Path(root).resolve()) for root in roots if Path(root).is_dir()]
    return (" Allowed filesystem workspace roots (absolute paths, use these instead of '.'): "
            + json.dumps(valid, ensure_ascii=True)
            + ". If this list is empty, do not attempt local file operations; ask the user to configure or mount a workspace. Never access outside these roots.")
