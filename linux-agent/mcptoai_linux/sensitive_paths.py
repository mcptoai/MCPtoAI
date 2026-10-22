"""Cihazdan bağımsız, geçersiz kılınamayan korumalı yol kuralları."""
from __future__ import annotations

import ctypes
import os
import platform
import re
from pathlib import Path, PureWindowsPath

from .paths import config_dir

# Bütün ajanlarda aynı kurallar uygulanır. Sistem yolu gizlenir; hata yalnızca kategoriyi söyler.
PROTECTED_COMPONENTS = {
    ".ssh": "SSH keys",
    ".gnupg": "GPG keys",
    ".aws": "AWS credentials",
    ".kube": "Kubernetes credentials",
    ".azure": "Azure credentials",
    ".docker": "Docker credentials",
    ".mozilla": "Browser profile",
    ".terraform.d": "Terraform credentials",
    ".password-store": "Password store",
}
PROTECTED_SEQUENCES = {
    (".config", "gcloud"): "Google Cloud credentials",
    (".config", "gh"): "GitHub credentials",
    (".config", "rclone"): "Rclone credentials",
    (".config", "op"): "Password manager",
    (".gem", "credentials"): "Ruby credentials",
    ("snap", "firefox"): "Browser profile",
    ("snap", "chromium"): "Browser profile",
    ("library", "application support", "firefox"): "Browser profile",
    ("library", "safari"): "Browser profile",
    (".local", "share", "keyrings"): "Password store",
    ("library", "keychains"): "Keychains",
    ("library", "cookies"): "Browser cookies",
    ("microsoft", "credentials"): "Windows credentials",
    ("microsoft", "protect"): "Windows credentials",
    ("microsoft", "vault"): "Windows credentials",
    ("google", "chrome"): "Browser profile",
    ("microsoft", "edge"): "Browser profile",
    ("bravesoftware", "brave-browser"): "Browser profile",
    ("mozilla", "firefox"): "Browser profile",
}
PROTECTED_FILENAMES = {
    ".npmrc": "Package credentials",
    ".pypirc": "Package credentials",
    ".netrc": "Network credentials",
    ".git-credentials": "Git credentials",
    ".htpasswd": "Password file",
    "rclone.conf": "Rclone credentials",
    ".vault-token": "Vault credentials",
    ".boto": "Cloud credentials",
    ".s3cfg": "Cloud credentials",
    ".pgpass": "Database credentials",
    ".my.cnf": "Database credentials",
    ".bash_history": "Shell history",
    ".zsh_history": "Shell history",
    ".python_history": "Shell history",
    ".psql_history": "Shell history",
    ".mysql_history": "Shell history",
    "consolehost_history.txt": "Shell history",
    "credentials.json": "Credentials",
}
SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx", ".ovpn", ".tfstate")
PRIVATE_PREFIXES = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa")
ALLOWED_ENV_TEMPLATES = frozenset({".env.example", ".env.sample", ".env.template"})
WINDOWS_PROFILE_MARKERS = frozenset({"login data", "cookies", "local state", "web data"})
AGENT_DIRECTORY_MARKERS = frozenset({"mcptoai", "mcptoai-desktop", "mcptoai-updater"})


def _windows_long_path(raw: str) -> str:
    """Windows kısa adlarını mevcut yolda uzun biçimine aç; çözülemeyeni kapalı reddet."""
    raw = raw.replace("/", "\\")
    if raw.startswith("\\\\?\\UNC\\"):
        raw = "\\\\" + raw[8:]
    elif raw.startswith("\\\\?\\"):
        raw = raw[4:]
    if raw.startswith("\\\\"):
        raise PermissionError("Protected location: Network share")
    parts = PureWindowsPath(raw).parts
    if any(":" in part for part in parts[1:]):
        raise PermissionError("Protected location: Alternate data stream")
    if any(part.endswith((".", " ")) for part in parts[1:]):
        raise PermissionError("Protected location: Ambiguous Windows path")
    if os.name == "nt":
        # GetLongPathNameW yalnızca mevcut yol için çalışır; olmayan dosyanın mevcut
        # ebeveyni açılır ve kalan bileşenler korunur.
        path = Path(raw)
        tail = []
        while not path.exists() and path.parent != path:
            tail.insert(0, path.name)
            path = path.parent
        try:
            size = ctypes.windll.kernel32.GetLongPathNameW(str(path), None, 0)
            if size:
                buf = ctypes.create_unicode_buffer(size + 1)
                if ctypes.windll.kernel32.GetLongPathNameW(str(path), buf, size + 1):
                    path = Path(buf.value)
        except (AttributeError, OSError, ValueError):
            pass
        raw = str(path.joinpath(*tail))
    if any(re.search(r"~[0-9]+$", part, flags=re.I) for part in PureWindowsPath(raw).parts):
        raise PermissionError("Protected location: Ambiguous Windows path")
    return raw


def _segments(path: str, system: str) -> tuple[str, ...]:
    if system == "Windows":
        return tuple(part.casefold() for part in PureWindowsPath(path).parts[1:])
    return tuple(part.casefold() for part in Path(path).parts[1:])


def _contains(parts: tuple[str, ...], seq: tuple[str, ...]) -> bool:
    length = len(seq)
    return any(parts[i:i + length] == seq for i in range(len(parts) - length + 1))


def _agent_roots(system: str) -> tuple[str, ...]:
    home = Path.home()
    roots = [config_dir(), home / ".config" / "mcptoai"]
    if system == "Darwin":
        roots += [home / "Library" / "Application Support" / "MCPtoAI",
                  home / "Library" / "Application Support" / "mcptoai-desktop",
                  home / "Library" / "Logs" / "MCPtoAI",
                  home / "Library" / "Caches" / "mcptoai-desktop"]
    elif system == "Windows":
        for name in ("APPDATA", "LOCALAPPDATA"):
            if os.environ.get(name):
                root = Path(os.environ[name])
                roots += [root / "MCPtoAI", root / "mcptoai-desktop", root / "MCPtoAI-updater"]
    else:
        roots += [home / ".local" / "share" / "mcptoai", home / ".cache" / "mcptoai"]
    return tuple(str(root.resolve(strict=False)) for root in roots)


def _category(candidate: Path, system: str) -> str | None:
    raw = str(candidate)
    if system == "Windows":
        raw = _windows_long_path(raw)
    parts = _segments(raw, system)
    # Kendi veri konumlarını önce denetle; konuma taşınmış bağlantılar da kapsanır.
    for root in _agent_roots(system):
        if system == "Windows":
            root = _windows_long_path(root)
        root_parts = _segments(root, system)
        if parts[:len(root_parts)] == root_parts:
            return "Agent data"
    # Windows kullanıcı profilindeki AppData ağacının tamamı hassastır.
    # Kullanıcı projelerindeki "appdata" adlı klasörleri etkilemez.
    if system == "Windows" and any(
        parts[i] == "users" and parts[i + 2:i + 4] in (
            ("appdata", "roaming"), ("appdata", "local"), ("appdata", "locallow")
        )
        for i in range(max(0, len(parts) - 3))
    ):
        return "Application data"
    # Apple iCloud Library/Mobile Documents serbesttir; yalnızca bilinen
    # parola yöneticisi konteynerleri korunur.
    if system == "Darwin":
        if (_contains(parts, ("library", "application support", "1password")) or
            _contains(parts, ("library", "application support", "bitwarden")) or
            any(parts[i:i + 2] == ("library", "group containers") and
                "1password" in parts[i + 2]
                for i in range(len(parts) - 2)) or
            any(parts[i:i + 2] == ("library", "containers") and
                parts[i + 2].startswith("com.bitwarden.")
                for i in range(len(parts) - 2))):
            return "Password manager"
    # Marker yalnızca işletim sisteminin gerçek uygulama veri konteynerinin
    # doğrudan altındaysa korunur; kullanıcı proje klasörleri engellenmez.
    containers = (
        ("appdata", "roaming"), ("appdata", "local"), ("appdata", "locallow"),
        ("library", "application support"), ("library", "logs"),
        ("library", "caches"),
    )
    if any(_contains(parts, container + (marker,))
           for container in containers for marker in AGENT_DIRECTORY_MARKERS):
        return "Agent data"
    # Taşınmış tarayıcı profilleri de, güvenli dosya uzantıları taşısalar bile korunur.
    browser_components = ("google-chrome", "chromium", "microsoft-edge")
    browser_dir = lambda value: (value in browser_components or
                                 any(value.startswith(prefix + "-") for prefix in ("google-chrome", "microsoft-edge")))
    if any(browser_dir(part) for part in parts[:-1]) or (parts and browser_dir(parts[-1])):
        return "Browser profile"
    if any(part in {"firefox", "mozilla", ".mozilla"} for part in parts) and any(
        part in {"profiles", "profile", "snap", "application support", "mozilla", ".mozilla"}
        for part in parts
    ):
        return "Browser profile"
    for name, category in PROTECTED_COMPONENTS.items():
        if name in parts:
            return category
    for seq, category in PROTECTED_SEQUENCES.items():
        if _contains(parts, seq):
            return category
    # Tarayıcı profilinin taşınması halinde bile standart hassas içerik korunur.
    if parts and parts[-1] in WINDOWS_PROFILE_MARKERS and any(
        "chrome" in part or "firefox" in part or "edge" in part or "brave" in part
        for part in parts[:-1]
    ):
        return "Browser profile"
    if not parts:
        return None
    filename = parts[-1]
    if filename.startswith(".env") and filename not in ALLOWED_ENV_TEMPLATES:
        if filename == ".env" or filename.startswith(".env."):
            return "Environment secrets"
    if filename in PROTECTED_FILENAMES:
        return PROTECTED_FILENAMES[filename]
    if "credentials" in filename and _contains(parts, (".cargo", filename)):
        return "Cargo credentials"
    # Firefox profiline taşınmış kimlik/veritabanı dosyalarının konumu ayrıca korunur.
    if filename in {"logins.json", "key4.db", "cookies.sqlite", "cert9.db"} and any(
        segment in {"firefox", "mozilla", ".mozilla"} for segment in parts[:-1]
    ):
        return "Browser profile"
    if filename.startswith("service-account") and filename.endswith(".json"):
        return "Service account"
    if filename.startswith(PRIVATE_PREFIXES):
        return "Private key"
    if filename.endswith(SENSITIVE_SUFFIXES):
        return "Private key"
    return None


def check_path(real_path: Path, *, write: bool) -> None:
    """Çözülmüş yolu doğrular; sistem yolu veya sır içeriği hata metnine girmez."""
    system = platform.system()
    candidate = Path(real_path).expanduser().resolve(strict=False)
    category = _category(candidate, system)
    if category is not None:
        raise PermissionError(f"Protected location: {category}")
