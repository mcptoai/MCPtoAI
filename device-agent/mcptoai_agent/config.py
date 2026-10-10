"""MCPtoAI device settings.

Public MCPtoAI service coordinates are application configuration, not user secrets.
Provider API keys and OAuth refresh tokens stay in the OS keychain.
"""
from __future__ import annotations
import os, json
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv
from .paths import config_dir
load_dotenv() if os.getenv("MCPTOAI_LOAD_DOTENV")=="1" else None
def _user_settings()->dict:
    try:
        data=json.loads((config_dir()/'settings.json').read_text())
        return data if isinstance(data,dict) else {}
    except (FileNotFoundError,json.JSONDecodeError):
        return {}
USER_SETTINGS=_user_settings()
def save_user_settings(data: dict) -> None:
    path=config_dir()/"settings.json"; path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(".json.tmp"); tmp.write_text(json.dumps(data,indent=2)); os.chmod(tmp,0o600); tmp.replace(path)

# Yalnızca cihazın kendisinden değiştirilebilen izinler. settings.json'dan ayrı tutulur:
# o dosyaya relay üzerinden gelen istekler de yazabildiği için, bu izinlerin güvenliği
# "relay kodu bu anahtara dokunmuyor" varsayımına bırakılmaz. Bu dosyayı yalnızca yerel
# `mcptoai-agent shell-access` komutu yazar (Desktop uygulaması da onu çağırır).
LOCAL_PERMISSIONS_FILE = "local-permissions.json"
def local_permission(name: str) -> bool:
    try:
        data=json.loads((config_dir()/LOCAL_PERMISSIONS_FILE).read_text())
        return isinstance(data,dict) and data.get(name) is True
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return False
def save_local_permission(name: str, value: bool) -> None:
    path=config_dir()/LOCAL_PERMISSIONS_FILE; path.parent.mkdir(parents=True,exist_ok=True)
    try:
        data=json.loads(path.read_text())
        data=data if isinstance(data,dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        data={}
    data[name]=bool(value)
    tmp=path.with_suffix(".json.tmp"); tmp.write_text(json.dumps(data,indent=2)); os.chmod(tmp,0o600); tmp.replace(path)


# Production defaults. AUTH0_DEVICE_CLIENT_ID is intentionally supplied at build/deploy
# time until the MCPtoAI Native application has been created in Auth0.
PRODUCTION_SERVER_URL = "https://api.mcptoai.com"
PRODUCTION_AUTH0_AUDIENCE = "https://api.mcptoai.com"
PRODUCTION_AUTH0_DOMAIN = "auth.mcptoai.com"
PRODUCTION_AUTH0_DEVICE_CLIENT_ID = "sAqB06RgSeNJrsuYs8G8QBSB2QNEljlF"

def _bool(name: str, default: bool=False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1","true","yes","on"}

def _roots() -> list[Path]:
    # An explicit deployment override wins. Otherwise Desktop can persist one
    # user-selected workspace_root. The legacy three-folder default is retained
    # until the user chooses a workspace.
    explicit=os.getenv("MCP_ALLOWED_ROOTS")
    if explicit:
        return [Path(x).expanduser().resolve() for x in explicit.split(os.pathsep) if x.strip()]
    chosen=str(USER_SETTINGS.get("workspace_root") or "").strip()
    if chosen:
        p=Path(chosen).expanduser().resolve()
        # A configured workspace must fail closed if it disappears. Falling
        # back to broader legacy roots would silently expand filesystem access.
        return [p] if p.exists() and p.is_dir() else []
    home=Path.home()
    return [(home/n).resolve() for n in ("Desktop","Documents","Downloads")]

@dataclass(frozen=True)
class Settings:
    user_settings: dict = field(default_factory=lambda: dict(USER_SETTINGS))
    provider: str = field(default_factory=lambda: str(os.getenv("MCPTOAI_PROVIDER") or USER_SETTINGS.get("provider") or "anthropic"))
    model: str = field(default_factory=lambda: str(os.getenv("MCPTOAI_MODEL") or USER_SETTINGS.get("model") or ("deepseek-v4.1-flash" if str(os.getenv("MCPTOAI_PROVIDER") or USER_SETTINGS.get("provider") or "anthropic") == "evren" else "claude-sonnet-5")))
    openai_base_url: str|None = field(default_factory=lambda: os.getenv("MCPTOAI_OPENAI_BASE_URL") or USER_SETTINGS.get("openai_base_url") or None)
    history_provider: str = field(default_factory=lambda: str(os.getenv("MCPTOAI_HISTORY_PROVIDER") or USER_SETTINGS.get("history_provider") or "mcptoai"))
    allowed_roots: list[Path] = field(default_factory=_roots)
    # Terminal komutları ve uzun süreli görevler: varsayılan kapalı; yalnızca cihazdan açılır.
    enable_shell: bool = field(default_factory=lambda: _bool("MCPTOAI_ENABLE_SHELL") or local_permission("shell"))
    max_output_chars: int = field(default_factory=lambda: int(os.getenv("MAX_OUTPUT_CHARS","64000")))
    max_read_bytes: int = field(default_factory=lambda: int(os.getenv("MAX_READ_BYTES","5000000")))
    default_cmd_timeout: int = field(default_factory=lambda: int(os.getenv("DEFAULT_CMD_TIMEOUT","300")))
    max_cmd_timeout: int = field(default_factory=lambda: int(os.getenv("MAX_CMD_TIMEOUT","1800")))
    max_agent_steps: int = field(default_factory=lambda: int(os.getenv("MCPTOAI_MAX_STEPS","15")))
    # Onay bekleme süresi (sn). Uzun görevlerin ara adımlarında kullanıcı uzakta olabilir.
    approval_timeout_seconds: int = field(default_factory=lambda: min(900, max(1, int(os.getenv("MCPTOAI_APPROVAL_TIMEOUT","900")))))
    auth0_domain: str = PRODUCTION_AUTH0_DOMAIN
    auth0_device_client_id: str = PRODUCTION_AUTH0_DEVICE_CLIENT_ID
    auth0_audience: str = PRODUCTION_AUTH0_AUDIENCE
    server_url: str = PRODUCTION_SERVER_URL
    relay_url: str = field(default_factory=lambda: os.getenv("MCPTOAI_RELAY_URL", "").strip())
    reconnect_max_seconds: int = field(default_factory=lambda: int(os.getenv("MCPTOAI_RECONNECT_MAX_SECONDS","30")))
settings=Settings()
