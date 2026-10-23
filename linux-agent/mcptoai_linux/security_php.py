"""Read-only, local PHP version advisory for MCPtoAI diagnostics.

Only examines the PHP executable on PATH. Does not scan containers, servers,
other installations or distribution backported security patches.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

# Minimum upstream versions from php.net releases, 21 October 2026.
MINIMUM_UPSTREAM = {(8, 5): (8, 5, 12), (8, 4): (8, 4, 27),
                    (8, 3): (8, 3, 36), (8, 2): (8, 2, 35)}
_VERSION = re.compile(r"\bPHP\s+(\d+)\.(\d+)\.(\d+)\b", re.I)


@dataclass(frozen=True)
class PHPFinding:
    status: str  # absent, updated, review, error
    detail: str


def inspect_php() -> PHPFinding:
    """Never invoke a shell or modify local files; no network requests."""
    executable = shutil.which("php")
    if not executable:
        return PHPFinding("absent", "PHP not found on PATH (other installations not scanned).")
    try:
        result = subprocess.run([executable, "-v"], capture_output=True,
                                text=True, errors="replace", timeout=4, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return PHPFinding("error", f"PHP version check failed: {type(exc).__name__}.")
    match = _VERSION.search(result.stdout + "\n" + result.stderr)
    if not match:
        return PHPFinding("review", "PHP detected, version could not be verified; review manually.")
    version = tuple(int(part) for part in match.groups())
    version_text = ".".join(map(str, version))
    minimum = MINIMUM_UPSTREAM.get(version[:2])
    if minimum is None:
        return PHPFinding("review", f"PHP {version_text}: unsupported or unassessed branch; check php.net security support.")
    if version < minimum:
        target = ".".join(map(str, minimum))
        return PHPFinding("review", f"PHP {version_text} below upstream security baseline {target}; update or verify vendor backported patches. Other PHP installs/containers not scanned.")
    return PHPFinding("updated", f"PHP {version_text} meets the published upstream baseline; this is not a full vulnerability scan.")
