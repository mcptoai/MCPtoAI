from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    """Linux: $XDG_CONFIG_HOME/mcptoai (varsayılan ~/.config/mcptoai)."""
    base = os.getenv("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    if os.getenv("MCPTOAI_CONTAINER") == "1":
        return Path("/data")
    return Path(base) / "mcptoai"
