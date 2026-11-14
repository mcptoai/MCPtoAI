"""Local-only activity storage path (never a relay URL)."""
import os
from pathlib import Path

def config_dir():
    if os.getenv("MCPTOAI_CONTAINER") == "1":
        return Path("/data")
    if os.name == "nt":
        return Path(os.getenv("APPDATA") or (Path.home()/"AppData"/"Roaming"))/"MCPtoAI"
    return Path(os.getenv("XDG_CONFIG_HOME") or (Path.home()/".config"))/"mcptoai"
