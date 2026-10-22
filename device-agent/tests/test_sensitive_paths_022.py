import os
import platform
from pathlib import Path

import pytest

from mcptoai_agent.sensitive_paths import check_path, _category, _windows_long_path
from mcptoai_agent.config import Settings
from mcptoai_agent.tools.host_tools import build_server


@pytest.mark.parametrize("folder,category", [
    (".ssh", "SSH keys"), (".gnupg", "GPG keys"), (".aws", "AWS credentials"),
    (".kube", "Kubernetes credentials"), (".azure", "Azure credentials"),
    (".terraform.d", "Terraform credentials"),
    (".config/gcloud", "Google Cloud credentials"),
    (".config/gh", "GitHub credentials"), (".docker", "Docker credentials"),
])
def test_protected_directories(tmp_path, folder, category):
    path = tmp_path / folder / "secret.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fake")
    with pytest.raises(PermissionError, match="Protected location: "):
        check_path(path, write=False)


@pytest.mark.parametrize("filename", [
    ".env", ".env.local", "auth.pem", "api.key", "my.p12", "my.pfx",
    "cert.jks", "wallet.keystore", "db.kdbx", "vpn.ovpn", "state.tfstate",
    "credentials.json", "service-account-prod.json", ".htpasswd",
    "id_rsa", "id_ed25519",
])
def test_sensitive_file_names(tmp_path, filename):
    with pytest.raises(PermissionError, match="Protected location: "):
        check_path(tmp_path / filename, write=True)


@pytest.mark.parametrize("filename", [
    "README.md", "environment.txt", "keys.md", "monkey.pem.txt",
    ".env.example", ".env.sample", ".env.template",
])
def test_non_secret_names_are_allowed(tmp_path, filename):
    check_path(tmp_path / filename, write=False)


def test_symlink_cannot_escape_workspace_into_ssh(tmp_path):
    secret_dir = tmp_path / ".ssh"
    secret_dir.mkdir()
    (secret_dir / "id_rsa").write_text("fake")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "link").symlink_to(secret_dir, target_is_directory=True)
    with pytest.raises(PermissionError, match="Protected location"):
        check_path((workspace / "link" / "id_rsa").resolve(), write=False)


def test_parent_components_and_directory_protection(tmp_path):
    secret = tmp_path / ".aws"
    secret.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(PermissionError):
        check_path(workspace / ".." / ".aws", write=False)


def test_agent_configuration_always_protected():
    from mcptoai_agent.paths import config_dir
    with pytest.raises(PermissionError, match="Agent data"):
        check_path(config_dir() / "local-permissions.json", write=True)


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only filesystem controls")
def test_windows_unc_ads_and_trailing_dot(tmp_path):
    for path in ("\\\\server\\share\\secret.txt", "C:\\safe\\file.txt:stream",
                 "C:\\safe\\secret.txt.", "C:\\safe\\file.txt "):
        with pytest.raises(PermissionError):
            _windows_long_path(path)


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only 8.3/Junction")
def test_windows_junction_and_case(tmp_path):
    import subprocess
    protected = tmp_path / ".SSH"
    protected.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    junction = workspace / "alias"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(protected)], check=True, capture_output=True)
    with pytest.raises(PermissionError):
        check_path(junction / "something", write=False)


def test_same_implementation_across_platforms():
    local = Path(__file__).resolve().parents[1] / "mcptoai_agent" / "sensitive_paths.py"
    repo = Path(__file__).resolve().parents[2]
    sibling = repo / ("linux-agent/mcptoai_linux/sensitive_paths.py" if "mcptoai_agent" in str(local) else "device-agent/mcptoai_agent/sensitive_paths.py")
    if sibling.exists():
        assert local.read_bytes() == sibling.read_bytes()


def test_case_insensitive_restriction_even_when_file_does_not_exist(tmp_path):
    with pytest.raises(PermissionError, match="Protected location"):
        check_path(tmp_path / ".SSH" / "KEY.TXT", write=False)


def test_error_never_exposes_absolute_path(tmp_path):
    private=tmp_path / ".aws" / "something.txt"
    with pytest.raises(PermissionError) as error:
        check_path(private, write=False)
    assert str(tmp_path) not in str(error.value)
    assert "AWS credentials" in str(error.value)


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows only")
def test_windows_short_alias_handling(tmp_path):
    import ctypes
    # 8.3 takma adı kapalı makinelerde belirsiz kısa yolu kapalı reddet.
    with pytest.raises(PermissionError, match="Ambiguous"):
        _windows_long_path(r"C:\\PROTEC~1\\FILE.TXT")
    cfg = Path.home() / "AppData" / "Roaming" / "MCPtoAI"
    size = ctypes.windll.kernel32.GetShortPathNameW(str(cfg), None, 0)
    if size:
        buf=ctypes.create_unicode_buffer(size+1)
        ctypes.windll.kernel32.GetShortPathNameW(str(cfg),buf,size+1)
        with pytest.raises(PermissionError, match="Application data"):
            check_path(Path(buf.value) / "local-permissions.json", write=False)


@pytest.mark.parametrize("relative", [
    "Projects/MCPtoAI/web/logs/x.txt",
    "Projects/MCPtoAI/web/caches/x.txt",
    "Projects/MCPtoAI/web/appdata/n.txt",
    "Projects/MCPtoAI/web/.cache/n.txt",
    "mcptoai/logs/prune.log",
    "Documents/MCPtoAI/appdata/n.txt",
    "Documents/MCPtoAI/Library/Caches/report.txt",
])
def test_project_folders_named_like_agent_are_allowed(tmp_path, relative):
    check_path(tmp_path / relative, write=False)


@pytest.mark.parametrize("system,relative", [
    ("Windows", "AppData/Roaming/MCPtoAI/config.json"),
    ("Windows", "AppData/Local/MCPtoAI/agent.log"),
    ("Windows", "AppData/LocalLow/MCPtoAI/agent.log"),
    ("Windows", "AppData/Local/mcptoai-updater/update.json"),
    ("Darwin", "Library/Application Support/MCPtoAI/identity"),
    ("Darwin", "Library/Logs/MCPtoAI/agent.log"),
    ("Darwin", "Library/Caches/MCPtoAI-Desktop/state"),
])
def test_real_agent_container_remains_protected(tmp_path, system, relative):
    from mcptoai_agent.sensitive_paths import _category
    candidate = tmp_path / relative
    if system == "Windows":
        candidate = Path("C:/Users/test") / relative
    assert _category(candidate, system) == ("Application data" if system == "Windows" else "Agent data")


@pytest.mark.parametrize("relative,category", [
    (".mozilla/firefox/profiles.ini", "Browser profile"),
    ("snap/firefox/common/.mozilla/firefox/profiles.ini", "Browser profile"),
    ("snap/chromium/common/chromium/Default/Cookies", "Browser profile"),
    (".config/google-chrome/Default/Cookies", "Browser profile"),
    (".config/google-chrome-beta/Default/Local State", "Browser profile"),
    (".config/chromium/Default/Login Data", "Browser profile"),
    ("AppData/Local/Microsoft-Edge/Default/Cookies", "Browser profile"),
    ("Library/Application Support/Firefox/Profiles/a/key4.db", "Browser profile"),
    ("Library/Safari/History.db", "Browser profile"),
    ("Mozilla/Firefox/Profiles/test/logins.json", "Browser profile"),
    ("Mozilla/Firefox/Profiles/test/cookies.sqlite", "Browser profile"),
    ("Mozilla/Firefox/Profiles/test/cert9.db", "Browser profile"),
    (".config/rclone/rclone.conf", "Rclone credentials"),
    (".config/op/config", "Password manager"),
    (".vault-token", "Vault credentials"),
    (".boto", "Cloud credentials"),
    (".s3cfg", "Cloud credentials"),
    (".pgpass", "Database credentials"),
    (".my.cnf", "Database credentials"),
    (".cargo/credentials.toml", "Cargo credentials"),
    (".gem/credentials", "Ruby credentials"),
    (".bash_history", "Shell history"),
    (".zsh_history", "Shell history"),
    (".python_history", "Shell history"),
    (".psql_history", "Shell history"),
    (".mysql_history", "Shell history"),
    ("ConsoleHost_history.txt", "Shell history"),
])
def test_additional_secrets_blocked(tmp_path,relative,category):
    with pytest.raises(PermissionError,match="Protected location: "+category):
        check_path(tmp_path / relative, write=False)


@pytest.mark.parametrize("relative", [
    ".git/config", "browser-README.md", "Firefox-setup.txt", "readme.key.txt",
    "project/.cache/notes.txt", "project/Logs/notes.txt", "project/.env.example",
    "project/keynotes.md", "project/chromium-notes.txt", "project/.cargo/README.md",
])
def test_additional_normal_files_allowed(tmp_path,relative):
    check_path(tmp_path / relative,write=False)


def test_keynote_extension_necessarily_blocked(tmp_path):
    with pytest.raises(PermissionError,match="Private key"):
        check_path(tmp_path / "presentation.key",write=False)


@pytest.mark.parametrize("relative", [
    "AppData/Roaming/gcloud/credentials.db",
    "AppData/Roaming/GitHub CLI/hosts.yml",
    "AppData/Roaming/rclone/rclone.conf",
    "AppData/Roaming/npm/etc/npmrc",
    "AppData/Local/1Password/settings.json",
    "AppData/Roaming/Bitwarden/data.json",
    "AppData/Roaming/WinSCP.ini",
    "AppData/Roaming/FileZilla/sitemanager.xml",
    "AppData/LocalLow/ExampleApp/settings.ini",
    "appdata/ROAMING/example.txt",
])
def test_windows_user_appdata_tree_is_fully_blocked(relative):
    from mcptoai_agent.sensitive_paths import _category
    path = Path("C:/Users/test") / relative
    assert _category(path, "Windows") == "Application data"


@pytest.mark.parametrize("relative", [
    "Documents/AppData/Roaming/notes.txt",
    "Documents/MCPtoAI/appdata/n.txt",
    "Desktop/notes.txt",
    "Downloads/notes.txt",
    "OneDrive/Documents/report.pdf",
    "Projects/MCPtoAI/web/logs/report.txt",
])
def test_windows_user_documents_are_not_appdata(relative):
    from mcptoai_agent.sensitive_paths import _category
    assert _category(Path("C:/Users/test") / relative, "Windows") is None


@pytest.mark.parametrize("relative", [
    "Library/Application Support/1Password/data.db",
    "Library/Application Support/Bitwarden/state.json",
    "Library/Group Containers/2BUA8C4S2C.com.1password/db.sqlite",
    "Library/Group Containers/group.1PASSWORD/shared",
    "Library/Containers/com.bitwarden.desktop/Data/config.json",
])
def test_macos_password_manager_directories_are_blocked(relative):
    from mcptoai_agent.sensitive_paths import _category
    assert _category(Path("/Users/example") / relative, "Darwin") == "Password manager"


def test_macos_icloud_mobile_documents_remains_accessible():
    from mcptoai_agent.sensitive_paths import _category
    candidate=Path("/Users/example/Library/Mobile Documents/com~apple~CloudDocs/x.pdf")
    assert _category(candidate,"Darwin") is None


def test_rclone_paths_blocked_everywhere():
    from mcptoai_agent.sensitive_paths import _category
    for system in ("Windows", "Darwin", "Linux"):
        path=(Path("C:/Users/test") if system == "Windows" else Path("/home/test"))
        assert _category(path / ".config/rclone/config.txt", system)=="Rclone credentials"
        assert _category(path / "safe/rclone.conf", system)=="Rclone credentials"
