"""Beginner-friendly setup wizard for Universal Host Manager MCP."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

console = Console()

_DANGEROUS_PATHS = {"/", "/root", "/etc", "/usr", "/bin", "/sbin", "/var", "/home"}
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)


@dataclass(frozen=True)
class NetworkConfig:
    """Validated networking choices used to generate the final configuration."""

    mode: str
    base_url: str
    port: int
    remote: bool
    follow_up: tuple[str, ...] = ()
    autostart_target: Optional[str] = None


def _is_dangerous(path: Path) -> bool:
    return str(path) in _DANGEROUS_PATHS or path == Path.home()


def _validate_hostname(value: str, *, ngrok: bool = False) -> str:
    hostname = value.strip().lower().rstrip(".")
    if not hostname:
        raise ValueError("Enter a hostname, for example mcp.example.com.")
    if "://" in hostname:
        raise ValueError("Enter only the hostname, without https:// or a path.")
    if any(char in hostname for char in "/?#:@") or any(char.isspace() for char in hostname):
        raise ValueError("A hostname cannot contain a path, port, spaces, or URL parameters.")
    if "." not in hostname:
        raise ValueError("Enter a complete hostname containing a dot, not a short name such as 'test'.")
    if len(hostname) > 253 or any(not _HOST_LABEL.fullmatch(label) for label in hostname.split(".")):
        raise ValueError("That hostname is not valid. Example: mcp.example.com")
    if ngrok and not hostname.endswith(
        (".ngrok-free.dev", ".ngrok-free.app", ".ngrok.dev", ".ngrok.app")
    ):
        raise ValueError(
            "Enter the dev/static domain shown in your ngrok dashboard, such as name.ngrok-free.dev."
        )
    return hostname


def _validate_https_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme != "https":
        raise ValueError("The public URL must start with https://.")
    if not parsed.hostname:
        raise ValueError("Enter a complete URL, for example https://mcp.example.com.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Do not include credentials, query parameters, or fragments in the URL.")
    if parsed.path not in ("", "/"):
        raise ValueError("Enter only the base URL; do not add /mcp or another path.")
    if "." not in parsed.hostname:
        raise ValueError("Use a complete public hostname, not a short name such as 'test'.")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("The URL contains an invalid port.") from exc
    return base_url


def _ask_port() -> int:
    console.print("The local port is a number. [bold]Press Enter[/bold] to accept 8765; do not type y/n.")
    while True:
        raw = Prompt.ask("Local port for the server", default="8765").strip()
        try:
            port = int(raw)
        except ValueError:
            console.print("[red]Please enter a number between 1 and 65535.[/red]")
            continue
        if 1 <= port <= 65535:
            return port
        console.print("[red]Port must be between 1 and 65535.[/red]")


def _ask_hostname(prompt: str, *, ngrok: bool = False) -> str:
    while True:
        try:
            return _validate_hostname(Prompt.ask(prompt), ngrok=ngrok)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")


def _ask_https_base_url() -> str:
    while True:
        try:
            return _validate_https_base_url(Prompt.ask("Public HTTPS base URL (for example https://mcp.example.com; do not add /mcp)"))
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")


def _ask_required(prompt: str, *, password: bool = False, default: Optional[str] = None) -> str:
    """Ask until a non-empty value is entered."""
    while True:
        value = Prompt.ask(prompt, password=password, default=default).strip()
        if value:
            return value
        console.print("[red]This value cannot be empty.[/red]")


def _parse_auth0_env_block(text: str) -> dict[str, str]:
    """Extract and validate Auth0 application values from a copied .env block."""
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in {"AUTH0_DOMAIN", "AUTH0_CLIENT_ID", "AUTH0_CLIENT_SECRET"}:
            continue
        values[key] = value.strip().strip('"').strip("'")

    missing = [
        key for key in ("AUTH0_DOMAIN", "AUTH0_CLIENT_ID", "AUTH0_CLIENT_SECRET")
        if not values.get(key)
    ]
    if missing:
        raise ValueError("Missing required value(s): " + ", ".join(missing))

    secret = values["AUTH0_CLIENT_SECRET"]
    if "MASKED" in secret.upper() or "*" in secret:
        raise ValueError(
            "AUTH0_CLIENT_SECRET is masked. In Auth0, reveal/copy the real Client Secret "
            "from Application > Settings and try again."
        )

    values["AUTH0_DOMAIN"] = _validate_hostname(values["AUTH0_DOMAIN"])
    return values


def _read_clipboard() -> str:
    """Read text from a supported desktop clipboard without displaying secrets."""
    commands = (
        ("pbpaste",),
        ("wl-paste", "--no-newline"),
        ("xclip", "-selection", "clipboard", "-o"),
        ("xsel", "--clipboard", "--output"),
    )
    for command in commands:
        if not shutil.which(command[0]):
            continue
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    raise RuntimeError(
        "Clipboard reading is unavailable. Choose the paste or manual-entry option instead."
    )


def _ask_auth0_application_values() -> dict[str, str]:
    """Collect Auth0 application values by clipboard, block paste, or manual entry."""
    console.print("  [bold]1[/bold] Read the copied Auth0 .env block from clipboard [green](recommended)[/green]")
    console.print("  [bold]2[/bold] Paste the Auth0 .env block in the terminal")
    console.print("  [bold]3[/bold] Enter Domain, Client ID, and Client Secret separately")

    while True:
        choice = Prompt.ask("How would you like to add the Auth0 values?", choices=["1", "2", "3"], default="1")
        if choice == "3":
            domain = _ask_hostname("AUTH0_DOMAIN (for example your-tenant.eu.auth0.com)")
            return {
                "AUTH0_DOMAIN": domain,
                "AUTH0_CLIENT_ID": _ask_required("AUTH0_CLIENT_ID (Application Settings > Client ID)"),
                "AUTH0_CLIENT_SECRET": _ask_required(
                    "AUTH0_CLIENT_SECRET (Application Settings > Client Secret)",
                    password=True,
                ),
            }

        if choice == "1":
            try:
                block = _read_clipboard()
            except RuntimeError as exc:
                console.print(f"[red]{exc}[/red]")
                continue
        else:
            console.print(
                "Paste the complete block below. On a new line, type [bold]END[/bold] and press Enter."
            )
            lines: list[str] = []
            while True:
                line = console.input()
                if line.strip().upper() == "END":
                    break
                lines.append(line)
            block = "\n".join(lines)

        try:
            values = _parse_auth0_env_block(block)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            console.print("Copy the block again, or choose option 3 to enter the values manually.")
            continue

        console.print("[green]✓ Auth0 Domain, Client ID, and Client Secret were imported.[/green]")
        return values


def ask_workspace_dir() -> Path:
    console.print(Panel(
        "Choose the folder the AI should work in. The built-in file tools cannot leave this folder.\n\n"
        "[yellow]Important:[/yellow] shell commands are not sandboxed; they keep the permissions of your "
        "macOS/Linux user. For a first test, use a new empty folder.", title="Workspace"))
    while True:
        path = Path(Prompt.ask("Workspace directory", default=str(Path.cwd() / "workspace"))).expanduser()
        if _is_dangerous(path):
            console.print(f"[yellow]'{path}' is a broad system or home directory.[/yellow]")
            if not Confirm.ask("Are you sure the AI should have read/write access here?", default=False):
                continue
        if not path.exists():
            if Confirm.ask(f"'{path}' doesn't exist. Create it?", default=True):
                path.mkdir(parents=True, exist_ok=True)
            else:
                continue
        elif not path.is_dir():
            console.print(f"[red]'{path}' exists and is not a directory.[/red]")
            continue
        return path.resolve()

def _cloudflare_follow_up(hostname: str, port: int) -> tuple[str, ...]:
    return (
        "Install cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/",
        "macOS with Homebrew: brew install cloudflared",
        "Linux: install cloudflared using the official package-repository commands on the download page.",
        "Authenticate: cloudflared tunnel login",
        "Create the tunnel: cloudflared tunnel create universal-host-manager-mcp",
        f"Create DNS routing: cloudflared tunnel route dns universal-host-manager-mcp {hostname}",
        "Create ~/.cloudflared/config.yml and route the hostname to http://127.0.0.1:{port} as shown in the README.",
        "Start the tunnel in a second terminal: cloudflared tunnel run universal-host-manager-mcp",
        "Keep both the MCP server terminal and the cloudflared terminal running.",
    )


def _ask_autostart_target(tunnel_name: str) -> Optional[str]:
    if not Confirm.ask(
        f"Would you like commands that start both the MCP server and {tunnel_name} automatically?",
        default=False,
    ):
        return None
    console.print("The wizard will create uhm-enable-autostart.sh; review it, then run one command after setup.")
    console.print("  [bold]1[/bold] Linux server (systemd user services)")
    console.print("  [bold]2[/bold] macOS (LaunchAgents)")
    default_target = "1" if sys.platform.startswith("linux") else "2"
    target_choice = Prompt.ask(
        "Which device will run the services?",
        choices=["1", "2"],
        default=default_target,
    )
    return "linux" if target_choice == "1" else "macos"


def _ngrok_follow_up(hostname: str, port: int) -> tuple[str, ...]:
    return (
        "Install ngrok on macOS: brew install ngrok/ngrok/ngrok",
        "Install ngrok on Linux: use https://ngrok.com/download (Ubuntu can use: sudo snap install ngrok)",
        "Open https://dashboard.ngrok.com/get-started/your-authtoken and sign in.",
        "Copy and run: ngrok config add-authtoken YOUR_NGROK_TOKEN",
        "Replace YOUR_NGROK_TOKEN with the authtoken from the dashboard; do not use the domain ID and never share the token.",
        f"Start the tunnel in a second terminal: ngrok http --url={hostname} {port}",
        "Keep both the MCP server terminal and the ngrok terminal running.",
    )


def _cloudflare_autostart_steps(
    target: str,
    config_dir: Path,
    server_command: str,
) -> tuple[str, ...]:
    config_path = str(config_dir)
    if target == "linux":
        script = f"""#!/bin/sh\nset -eu\n# Create and enable both services on Linux.
CLOUDFLARED_BIN="$(command -v cloudflared)"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/universal-host-manager-mcp.service" <<EOF
[Unit]
Description=Universal Host Manager MCP
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory={config_path}
ExecStart={server_command}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
cat > "$HOME/.config/systemd/user/universal-host-manager-cloudflared.service" <<EOF
[Unit]
Description=Cloudflare Tunnel for Universal Host Manager MCP
After=network-online.target universal-host-manager-mcp.service
Wants=network-online.target universal-host-manager-mcp.service

[Service]
ExecStart=$CLOUDFLARED_BIN tunnel run universal-host-manager-mcp
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now universal-host-manager-mcp.service universal-host-manager-cloudflared.service
sudo loginctl enable-linger "$USER"
systemctl --user status universal-host-manager-mcp.service universal-host-manager-cloudflared.service --no-pager"""
    else:
        script = f"""#!/bin/sh\nset -eu\n# Create and enable both services on macOS.
CLOUDFLARED_BIN="$(command -v cloudflared)"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$HOME/Library/LaunchAgents/io.bkty.universal-host-manager-mcp.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>io.bkty.universal-host-manager-mcp</string>
  <key>ProgramArguments</key><array><string>{server_command}</string></array>
  <key>WorkingDirectory</key><string>{config_path}</string>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/uhm-mcp.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/uhm-mcp-error.log</string>
</dict></plist>
EOF
cat > "$HOME/Library/LaunchAgents/io.bkty.universal-host-manager-cloudflared.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>io.bkty.universal-host-manager-cloudflared</string>
  <key>ProgramArguments</key>
  <array><string>$CLOUDFLARED_BIN</string><string>tunnel</string><string>run</string><string>universal-host-manager-mcp</string></array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/uhm-cloudflared.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/uhm-cloudflared-error.log</string>
</dict></plist>
EOF
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/io.bkty.universal-host-manager-mcp.plist" 2>/dev/null || true
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/io.bkty.universal-host-manager-cloudflared.plist" 2>/dev/null || true
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/io.bkty.universal-host-manager-mcp.plist"
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/io.bkty.universal-host-manager-cloudflared.plist"
launchctl print gui/$(id -u)/io.bkty.universal-host-manager-mcp
launchctl print gui/$(id -u)/io.bkty.universal-host-manager-cloudflared"""
    return (script,)


def _remote_autostart_steps(
    hostname: str,
    port: int,
    target: str,
    config_dir: Path,
    server_command: str,
) -> tuple[str, ...]:
    config_path = str(config_dir)
    if target == "linux":
        script = f"""#!/bin/sh\nset -eu\n# Run after saving the ngrok authtoken; create both Linux services.
NGROK_BIN="$(command -v ngrok)"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/universal-host-manager-mcp.service" <<EOF
[Unit]
Description=Universal Host Manager MCP
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory={config_path}
ExecStart={server_command}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
cat > "$HOME/.config/systemd/user/universal-host-manager-ngrok.service" <<EOF
[Unit]
Description=ngrok tunnel for Universal Host Manager MCP
After=network-online.target universal-host-manager-mcp.service
Wants=network-online.target universal-host-manager-mcp.service

[Service]
ExecStart=$NGROK_BIN http --url={hostname} {port}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now universal-host-manager-mcp.service universal-host-manager-ngrok.service
sudo loginctl enable-linger "$USER"
systemctl --user status universal-host-manager-mcp.service universal-host-manager-ngrok.service --no-pager"""
    else:
        script = f"""#!/bin/sh\nset -eu\n# Run after saving the ngrok authtoken; create both macOS agents.
NGROK_BIN="$(command -v ngrok)"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$HOME/Library/LaunchAgents/io.bkty.universal-host-manager-mcp.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>io.bkty.universal-host-manager-mcp</string>
  <key>ProgramArguments</key>
  <array><string>{server_command}</string></array>
  <key>WorkingDirectory</key><string>{config_path}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/uhm-mcp.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/uhm-mcp-error.log</string>
</dict>
</plist>
EOF
cat > "$HOME/Library/LaunchAgents/io.bkty.universal-host-manager-ngrok.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>io.bkty.universal-host-manager-ngrok</string>
  <key>ProgramArguments</key>
  <array>
    <string>$NGROK_BIN</string>
    <string>http</string>
    <string>--url={hostname}</string>
    <string>{port}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/uhm-ngrok.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/uhm-ngrok-error.log</string>
</dict>
</plist>
EOF
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/io.bkty.universal-host-manager-mcp.plist" 2>/dev/null || true
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/io.bkty.universal-host-manager-ngrok.plist" 2>/dev/null || true
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/io.bkty.universal-host-manager-mcp.plist"
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/io.bkty.universal-host-manager-ngrok.plist"
launchctl print gui/$(id -u)/io.bkty.universal-host-manager-mcp
launchctl print gui/$(id -u)/io.bkty.universal-host-manager-ngrok"""
    return (script,)


def ask_networking() -> NetworkConfig:
    console.print(Panel(
        "Choose [bold]Local-only test[/bold] for your first installation. It needs no domain, tunnel, "
        "or Auth0 account and is reachable only from this computer.\n\n"
        "Remote options require a real HTTPS address and Auth0 authentication.",
        title="How will you use the server?"))
    console.print("  [bold]1[/bold] Local-only test [green](recommended for first-time users)[/green]")
    console.print("  [bold]2[/bold] Remote access with Cloudflare Tunnel (you own a domain)")
    console.print("  [bold]3[/bold] Remote access with an ngrok static domain")
    console.print("  [bold]4[/bold] Remote access with an HTTPS URL you already manage")
    choice = Prompt.ask("Choose", choices=["1", "2", "3", "4"], default="1")
    port = _ask_port()
    if choice == "1":
        return NetworkConfig("Local-only test", f"http://127.0.0.1:{port}", port, False)
    if choice == "2":
        console.print(Panel(
            "1. Install cloudflared from the official guide:\n"
            "   [link=https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/]"
            "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/[/link]\n"
            "2. macOS: [cyan]brew install cloudflared[/cyan]\n"
            "3. Ubuntu/Debian: use the package-repository commands on that page.\n"
            "4. Sign in: [cyan]cloudflared tunnel login[/cyan]\n\n"
            "You must own a domain added to your Cloudflare account for this option.",
            title="Cloudflare Tunnel setup",
        ))
        hostname = _ask_hostname("Public hostname routed through Cloudflare (for example mcp.example.com)")
        return NetworkConfig(
            "Cloudflare Tunnel",
            f"https://{hostname}",
            port,
            True,
            _cloudflare_follow_up(hostname, port),
            _ask_autostart_target("Cloudflare Tunnel"),
        )
    if choice == "3":
        console.print(Panel(
            "1. On Ubuntu install ngrok: [cyan]sudo snap install ngrok[/cyan]\n"
            "2. Claim a domain: [link=https://dashboard.ngrok.com/domains]https://dashboard.ngrok.com/domains[/link]\n"
            "3. Open the authtoken page: [link=https://dashboard.ngrok.com/get-started/your-authtoken]https://dashboard.ngrok.com/get-started/your-authtoken[/link]\n"
            "4. Copy and run: [cyan]ngrok config add-authtoken YOUR_NGROK_TOKEN[/cyan]\n\n"
            "Replace the placeholder with the authtoken, not the domain ID. Never share the token. "
            "If it was exposed, reset it in the ngrok dashboard.",
            title="ngrok setup"))
        hostname = _ask_hostname(
            "Your ngrok dev/static domain (for example your-name.ngrok-free.dev)", ngrok=True
        )
        autostart_target = _ask_autostart_target("ngrok")
        return NetworkConfig(
            "ngrok static domain", f"https://{hostname}", port, True,
            _ngrok_follow_up(hostname, port), autostart_target
        )
    return NetworkConfig("Existing HTTPS URL", _ask_https_base_url(), port, True)


def _check_auth0_domain(domain: str) -> bool:
    try:
        with urllib.request.urlopen(f"https://{domain}/.well-known/openid-configuration", timeout=5) as response:  # noqa: S310
            return response.status == 200
    except Exception:
        return False


def _auth0_settings(public_origin: str) -> tuple[tuple[str, str], ...]:
    """Return the exact Auth0 dashboard values for this FastMCP deployment."""
    origin = public_origin.rstrip("/")
    return (
        ("Application Ownership", "First-party"),
        ("Application Type", "Regular Web Application"),
        ("Application Login URI", "Leave blank"),
        ("Allowed Callback URLs", f"{origin}/auth/callback"),
        ("Allowed Logout URLs", origin),
        ("Allowed Web Origins", origin),
        ("Allowed Origins (CORS)", origin),
        ("Allow Cross-Origin Authentication", "Off / disabled"),
        ("Cross-Origin Verification Fallback URL", "Leave blank"),
        ("API Identifier / Audience", f"{origin}/"),
        ("Signing Algorithm", "RS256"),
        ("Application > API Access", "Enable User-delegated Access for this API"),
        ("MCP endpoint (for AI clients)", f"{origin}/mcp"),
    )


def _show_auth0_settings(public_origin: str) -> None:
    table = Table(title="Values to enter in Auth0", show_header=True, header_style="bold cyan")
    table.add_column("Auth0 field", style="bold")
    table.add_column("Value", overflow="fold")
    for field, value in _auth0_settings(public_origin):
        table.add_row(field, value)
    console.print(table)


def ask_auth0(default_audience: str) -> Optional[dict[str, str]]:
    public_origin = default_audience.rstrip("/")
    console.print(Panel(
        "1. Open [link=https://auth0.com/]https://auth0.com/[/link], create an account, and open Dashboard.\n"
        "2. Go to [bold]Applications > APIs > Create API[/bold]. Give it a name and use the suggested "
        "Audience shown below as its Identifier character-for-character (including the trailing /), and select RS256.\n"
        "3. Go to [bold]Applications > Applications > Create Application[/bold], choose "
        "[bold]Regular Web Application[/bold].\n"
        "4. Set [bold]Application Ownership[/bold] to [bold]First-party[/bold]. Under "
        "[bold]Application > API Access[/bold], enable [bold]User-delegated Access[/bold] for the API you "
        "created in step 2.\n"
        "5. On Auth0's [bold]Integrate into your application[/bold] page, click [bold]Copy[/bold] "
        "above the .env block. The wizard can read it directly from your clipboard.\n"
        "6. If the secret says MASKED, open the application's [bold]Settings[/bold] page and copy "
        "the real Client Secret instead.\n"
        "7. In the application's [bold]Settings[/bold], enter the exact values shown below. "
        "Do not enter Claude, ChatGPT, or Grok callback URLs in Auth0; FastMCP handles those "
        "client redirects through the MCP registration flow.\n"
        "8. Click [bold]Save Changes[/bold] after entering the values.\n\n"
        "Client ID identifies the Regular Web Application. Client Secret is its real, unmasked password. "
        "Auth0 Domain is the tenant hostname. Audience is the API Identifier and must match it exactly.\n\n"
        "Auth0's AUTH0_SECRET, APP_BASE_URL and PORT quickstart values belong to its sample "
        "web application and are not used by this MCP server.\n\n"
        "Never publish the Client Secret or commit the generated .env file to Git.",
        title="Auth0 required for remote access"))
    _show_auth0_settings(public_origin)
    if not Confirm.ask("Do you have these Auth0 values ready?", default=False):
        return None
    application_values = _ask_auth0_application_values()
    domain = application_values["AUTH0_DOMAIN"]
    while True:
        with console.status(f"Checking {domain}..."):
            reachable = _check_auth0_domain(domain)
        if reachable:
            console.print(f"[green]✓ {domain} looks reachable.[/green]")
            break
        if Confirm.ask(f"[yellow]Couldn't verify {domain}. Use it anyway?[/yellow]", default=False):
            break
    audience = _ask_required(
        "AUTH0_AUDIENCE (API Settings > Identifier)", default=default_audience
    )
    if audience != default_audience:
        console.print(
            "[bold yellow]AUTH0_AUDIENCE must exactly match the API Identifier and "
            f"{default_audience!r}.[/bold yellow]"
        )
    return {**application_values, "AUTH0_AUDIENCE": audience}


def _write_autostart_script(env_path: Path, network: NetworkConfig, hostname: str) -> Path:
    """Create the executable installer which writes and enables the selected service files."""
    if network.mode == "Cloudflare Tunnel":
        steps = _cloudflare_autostart_steps(
            network.autostart_target or "linux", env_path.parent, _server_command()
        )
    else:
        steps = _remote_autostart_steps(
            hostname, network.port, network.autostart_target or "linux",
            env_path.parent, _server_command(),
        )
    path = env_path.parent / "uhm-enable-autostart.sh"
    path.write_text("\n".join(steps).rstrip() + "\n", encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return path


def write_env(path: Path, values: dict[str, str]) -> None:
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        os.chmod(backup, stat.S_IRUSR | stat.S_IWUSR)
        console.print(f"[dim]Existing .env backed up to {backup}[/dim]")
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _server_command() -> str:
    candidate = Path(sys.executable).parent / "universal-host-manager-mcp"
    return str(candidate) if candidate.exists() else (shutil.which("universal-host-manager-mcp") or "universal-host-manager-mcp")


def _macos_permission_steps(server_path: str) -> tuple[str, ...]:
    """macOS izinleri (Full Disk Access, Automation, Accessibility) TCC
    tarafindan calisan surecin TAM binary yoluna gore takip edilir, script'e
    gore degil -- ve Apple bunlari kasitli olarak script/CLI ile programatik
    verilemez sekilde tasarlamistir; System Settings'te elle onaylanmalari
    gerekir. Bu sunucu uzaktan (insansiz) calisacagi icin, izin penceresi
    goruntulendiginde tiklayacak kimse olmayabilir -- bu yuzden bunlarin
    kuruluma once, elle, tek seferde verilmesi onerilir.
    """
    python_path = str(Path(sys.executable).resolve())
    return (
        f"Server command path: {server_path}",
        f"Python interpreter used by this installation: {python_path}",
        "Grant Full Disk Access to this exact path once, now: System Settings > "
        "Privacy & Security > Full Disk Access > click '+' and add it. This covers "
        "commands that touch Desktop, Documents, Downloads, Photos, Mail, or other "
        "TCC-protected locations.",
        "If a remote command ever needs to control another app via AppleScript/"
        "osascript, macOS will show a one-time Automation prompt for that specific "
        "app pair; nobody may be there to click it, so test that command locally "
        "first, before relying on it remotely.",
        "These grants are tied to this exact path. Recreating the virtual "
        "environment, switching Python versions, or reinstalling elsewhere counts "
        "as a new path to macOS and asks again -- keep using this same "
        "installation for remote/unattended use.",
    )


def _offer_to_open_macos_privacy_settings() -> None:
    """Kullanicinin System Settings > Privacy & Security > Full Disk Access
    panelini elle aramasina gerek kalmasin diye dogrudan acmayi teklif eder.
    Yine de son onay tiklamasini kullanici yapmak zorunda -- bu adim
    programatik olarak atlatilamaz, sadece gezinme surtunmesini azaltir.
    """
    if not Confirm.ask(
        "Open System Settings > Privacy & Security > Full Disk Access now?",
        default=True,
    ):
        return
    try:
        subprocess.run(
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"],
            check=False,
        )
    except OSError:
        console.print("[yellow]Could not open System Settings automatically; open it by hand.[/yellow]")


_MACOS_PRIVACY_PANES = {
    "full_disk_access": "Privacy_AllFiles",
    "automation": "Privacy_Automation",
    "accessibility": "Privacy_Accessibility",
    "screen_recording": "Privacy_ScreenCapture",
}


def _open_macos_privacy_pane(pane: str) -> bool:
    """Open one macOS Privacy & Security pane without attempting to bypass TCC."""
    pane_id = _MACOS_PRIVACY_PANES[pane]
    try:
        result = subprocess.run(
            [
                "open",
                "x-apple.systempreferences:com.apple.preference.security?"
                + pane_id,
            ],
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def _test_workspace_access(workspace: Path) -> tuple[bool, str]:
    """Perform a harmless create/read/delete check inside the configured workspace."""
    probe = workspace / f".uhm-readiness-{os.getpid()}"
    try:
        probe.write_text("Universal Host Manager readiness test\n", encoding="utf-8")
        if probe.read_text(encoding="utf-8") != "Universal Host Manager readiness test\n":
            return False, "The test file was written but its contents could not be verified."
        return True, "Read, write, and delete access works."
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass


def _ask_macos_readiness_capabilities() -> dict[str, bool]:
    """Ask only for capabilities the user expects to use remotely."""
    console.print(Panel(
        "Select only the capabilities you plan to use remotely. macOS grants "
        "these permissions interactively and does not allow this wizard to click "
        "Allow on your behalf.\n\n"
        "[bold]Opening applications and ordinary URLs does not require an extra "
        "privacy permission.[/bold] Chrome Automation means controlling Chrome "
        "with AppleScript, not merely opening google.com.",
        title="Choose remote capabilities",
    ))
    return {
        "workspace": Confirm.ask(
            "Test read/write access to the configured workspace?",
            default=True,
        ),
        "full_disk_access": Confirm.ask(
            "Will remote commands access Desktop, Documents, Downloads, Photos, "
            "Mail, or other protected locations?",
            default=False,
        ),
        "chrome_automation": Confirm.ask(
            "Will remote commands control Google Chrome with AppleScript?",
            default=False,
        ),
        "accessibility": Confirm.ask(
            "Will remote commands control the mouse, keyboard, or app user interfaces?",
            default=False,
        ),
        "screen_recording": Confirm.ask(
            "Will remote commands capture or inspect the screen?",
            default=False,
        ),
    }


def _confirm_permission_in_settings(
    *,
    pane: str,
    permission_name: str,
    server_path: str,
) -> tuple[bool, str]:
    console.print(
        f"\n[bold]{permission_name}[/bold]\n"
        f"Server command:\n[cyan]{server_path}[/cyan]\n"
        f"Python interpreter:\n[cyan]{Path(sys.executable).resolve()}[/cyan]\n"
        "macOS may attribute command-line privacy access to the interpreter or "
        "the launching application. Add the path shown by the permission prompt; "
        "for a LaunchAgent deployment, use the Python interpreter above. "
        "Return to this terminal after approving it. The permission cannot be "
        "granted automatically."
    )
    if not _open_macos_privacy_pane(pane):
        console.print(
            f"[yellow]Open System Settings > Privacy & Security > "
            f"{permission_name} manually.[/yellow]"
        )
    confirmed = Confirm.ask(
        f"Have you enabled {permission_name} for the executable shown above?",
        default=False,
    )
    if confirmed:
        return True, "User confirmed the permission is enabled."
    return False, "Not confirmed; remote tasks needing this permission may stop."


def _test_chrome_automation(server_path: str) -> tuple[bool, str]:
    """Trigger Chrome's one-time Apple Events prompt with a read-only request."""
    try:
        chrome_check = subprocess.run(
            ["open", "-Ra", "Google Chrome"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return False, f"Could not look for Google Chrome: {exc}"
    if chrome_check.returncode != 0:
        return False, "Google Chrome is not installed or could not be found."

    console.print(
        "\n[bold]Google Chrome Automation[/bold]\n"
        "A read-only AppleScript will ask Chrome for the active tab title. "
        "Approve the macOS Automation dialog if it appears.\n"
        f"Server command: [cyan]{server_path}[/cyan]\n"
        f"Python interpreter: [cyan]{Path(sys.executable).resolve()}[/cyan]\n"
        "[yellow]This probe is started by the wizard. After installing the "
        "LaunchAgent, run one real Chrome Automation command through MCP while "
        "you are still beside the Mac, because macOS can track the launching "
        "process separately.[/yellow]"
    )
    script = (
        'tell application "Google Chrome"\n'
        "launch\n"
        'if (count of windows) is 0 then make new window\n'
        "return title of active tab of front window\n"
        "end tell"
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _open_macos_privacy_pane("automation")
        return False, f"Automation test could not complete: {exc}"

    if result.returncode == 0:
        return True, "Chrome accepted the read-only AppleScript request."

    _open_macos_privacy_pane("automation")
    detail = (result.stderr or result.stdout).strip()
    if len(detail) > 240:
        detail = detail[:237] + "..."
    return False, detail or "Chrome Automation was denied or not completed."


def _show_macos_readiness_report(
    results: list[tuple[str, bool, str]],
) -> bool:
    table = Table(
        title="macOS Remote Access Readiness Report",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Capability", style="bold")
    table.add_column("Status")
    table.add_column("Details", overflow="fold")
    ready = True
    for capability, passed, details in results:
        status = "[green]READY[/green]" if passed else "[red]ACTION REQUIRED[/red]"
        table.add_row(capability, status, details)
        ready = ready and passed
    console.print(table)
    if ready:
        console.print(
            "[bold green]Remote readiness: READY for every selected capability.[/bold green]"
        )
    else:
        console.print(
            "[bold yellow]Remote readiness: NOT READY. Complete the actions above "
            "while you are beside the Mac, then run uhm-setup again to retest.[/bold yellow]"
        )
    console.print(
        "[dim]After changing a macOS privacy permission, restart the MCP "
        "LaunchAgent before relying on it remotely.[/dim]"
    )
    return ready


def _run_macos_readiness_test(workspace: Path, server_path: str) -> Optional[bool]:
    """Interactively prepare selected macOS permissions before unattended use."""
    if not Confirm.ask(
        "Run macOS Remote Access Readiness Test now?",
        default=True,
    ):
        console.print(
            "[yellow]Readiness test skipped. Run uhm-setup again while beside the "
            "Mac before depending on protected features remotely.[/yellow]"
        )
        return None

    selected = _ask_macos_readiness_capabilities()
    results: list[tuple[str, bool, str]] = []

    if selected["workspace"]:
        passed, details = _test_workspace_access(workspace)
        results.append(("Workspace files", passed, details))

    if selected["full_disk_access"]:
        passed, details = _confirm_permission_in_settings(
            pane="full_disk_access",
            permission_name="Full Disk Access",
            server_path=server_path,
        )
        results.append(("Protected files", passed, details))

    if selected["chrome_automation"]:
        passed, details = _test_chrome_automation(server_path)
        results.append(("Chrome Automation", passed, details))

    if selected["accessibility"]:
        passed, details = _confirm_permission_in_settings(
            pane="accessibility",
            permission_name="Accessibility",
            server_path=server_path,
        )
        results.append(("Mouse, keyboard, and UI control", passed, details))

    if selected["screen_recording"]:
        passed, details = _confirm_permission_in_settings(
            pane="screen_recording",
            permission_name="Screen Recording",
            server_path=server_path,
        )
        results.append(("Screen capture", passed, details))

    if not results:
        console.print(
            "[yellow]No capabilities were selected, so no permission checks were run.[/yellow]"
        )
        return True
    return _show_macos_readiness_report(results)

def _show_summary(env_path: Path, workspace: Path, network: NetworkConfig, *, auth_configured: bool) -> None:
    lines = ["[bold green]Setup complete[/bold green]", "", f"Mode: [cyan]{network.mode}[/cyan]",
             f"Configuration: [cyan]{env_path}[/cyan]", f"Workspace: [cyan]{workspace}[/cyan]",
             f"MCP endpoint: [cyan]{network.base_url}/mcp[/cyan]", "",
             "Start the server from this configuration directory:",
             f"  [cyan]cd {shlex.quote(str(env_path.parent))}[/cyan]",
             f"  [cyan]{shlex.quote(_server_command())}[/cyan]"]
    if not network.remote:
        lines += ["", "[yellow]Local test mode has no authentication, but HOST is fixed to 127.0.0.1 so other computers cannot connect.[/yellow]", "Press Ctrl+C to stop the server."]
    elif auth_configured:
        if network.follow_up:
            lines += ["", "Before connecting a remote client, complete these networking steps:"]
            lines += [f"  [cyan]{escape(item)}[/cyan]" for item in network.follow_up]
        if network.mode in {"Cloudflare Tunnel", "ngrok static domain"}:
            lines += [
                "",
                "[bold yellow]The MCP server and the tunnel must both remain running. "
                "Closing either one takes the public endpoint offline.[/bold yellow]",
            ]
        else:
            lines += [
                "",
                "[bold yellow]The MCP server must remain running or the endpoint goes offline.[/bold yellow]",
            ]
        if network.autostart_target:
            hostname = urlparse(network.base_url).hostname
            if hostname:
                script_path = _write_autostart_script(env_path, network, hostname)
                lines += [
                    "", f"Autostart installer created: [cyan]{script_path}[/cyan]",
                    "Review it, then run:",
                    f"  [cyan]{escape(shlex.quote(str(script_path)))}[/cyan]",
                ]
        lines += [
            "", "Connection checks (after the server and tunnel are running):",
            f"  [cyan]curl -i {escape(network.base_url)}/mcp[/cyan]  [dim]# expect HTTP 401[/dim]",
            f"  [cyan]curl -i {escape(network.base_url)}/.well-known/oauth-authorization-server[/cyan]  [dim]# expect HTTP 200[/dim]",
        ]
        lines += ["", "Then add the MCP endpoint above to ChatGPT, Claude, or another MCP client."]
    console.print(Panel.fit("\n".join(lines)))


def main() -> None:
    config_dir = Path.cwd().resolve()
    console.print(Panel.fit(
        "[bold]Universal Host Manager MCP — setup wizard[/bold]\n\n"
        "This wizard explains each choice and creates a protected .env file.\n"
        f"Configuration directory: [cyan]{config_dir}[/cyan]\n\n"
        "Run the server from this same directory so it can find the .env file."))
    workspace = ask_workspace_dir()
    network = ask_networking()
    auth0: Optional[dict[str, str]] = None
    if network.remote:
        auth0 = ask_auth0(network.base_url + "/")
        if auth0 is None:
            console.print("\n[yellow]Remote setup was not written because Auth0 is required.[/yellow]")
            if Confirm.ask("Configure a safe local-only test instead?", default=True):
                network = NetworkConfig("Local-only test", f"http://127.0.0.1:{network.port}", network.port, False)
            else:
                console.print("No configuration was changed. Run uhm-setup again when ready.")
                return
    values = {"HOST": "127.0.0.1", "PORT": str(network.port), "MCP_BASE_URL": network.base_url,
              "MCP_WORKSPACE_DIR": str(workspace),
              "ALLOW_INSECURE_NO_AUTH": "false" if network.remote else "true"}
    if auth0:
        values.update(auth0)
    env_path = config_dir / ".env"
    write_env(env_path, values)
    _show_summary(env_path, workspace, network, auth_configured=auth0 is not None)
    if sys.platform == "darwin" and network.remote:
        console.print(Panel.fit(
            "\n".join(_macos_permission_steps(_server_command())),
            title="macOS permissions before unattended remote use",
        ))
        _run_macos_readiness_test(workspace, _server_command())


if __name__ == "__main__":
    main()
