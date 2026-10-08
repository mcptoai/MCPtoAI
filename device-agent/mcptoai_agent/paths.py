from __future__ import annotations
import os, platform
from pathlib import Path

def config_dir() -> Path:
    if platform.system() == "Windows":
        return Path(os.getenv("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "MCPtoAI"
    return Path.home() / ".config" / "mcptoai"
