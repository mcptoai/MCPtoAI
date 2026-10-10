"""Local, hardened MCP server for macOS — remote access edition.

Auth: Auth0 OAuth (same tenant/pattern as bktyserver), so only your own
Claude/Codex sessions can reach it once it's tunnelled out.
Transport: streamable-http, bound to 127.0.0.1 and reached only through a
Cloudflare Tunnel (never expose the raw port to the internet).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import subprocess
import time
import traceback
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.providers.auth0 import Auth0Provider
from playwright.async_api import Browser, Page, Playwright, async_playwright

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mac-mcp")
logging.getLogger("fastmcp").setLevel(logging.DEBUG)
logging.getLogger("mcp").setLevel(logging.DEBUG)

# --- Auth0 (mirrors bktyserver's setup) -------------------------------------
AUTH0_DOMAIN = os.environ["AUTH0_DOMAIN"]
AUTH0_CLIENT_ID = os.environ["AUTH0_CLIENT_ID"]
AUTH0_CLIENT_SECRET = os.environ["AUTH0_CLIENT_SECRET"]
AUTH0_AUDIENCE = os.environ["AUTH0_AUDIENCE"]
BASE_URL = os.environ["MCP_BASE_URL"]  # public tunnel URL, must match Auth0 app config

auth_provider = Auth0Provider(
    config_url=f"https://{AUTH0_DOMAIN}/.well-known/openid-configuration",
    client_id=AUTH0_CLIENT_ID,
    client_secret=AUTH0_CLIENT_SECRET,
    audience=AUTH0_AUDIENCE,
    base_url=BASE_URL,
    allowed_client_redirect_uris=[
        "https://claude.ai/api/mcp/auth_callback",
        "https://claude.com/api/mcp/auth_callback",
        "https://antigravity.google/oauth-callback",
        "http://localhost:*",
        "http://127.0.0.1:*",
    ],
)

# --- limits -------------------------------------------------------------
MAX_OUTPUT_CHARS = int(os.getenv("MAX_OUTPUT_CHARS", "64000"))
MAX_READ_BYTES = int(os.getenv("MAX_READ_BYTES", "5000000"))
DEFAULT_CMD_TIMEOUT = int(os.getenv("DEFAULT_CMD_TIMEOUT", "300"))
MAX_CMD_TIMEOUT = int(os.getenv("MAX_CMD_TIMEOUT", "1800"))

HOME_DIR = Path.home().resolve()
DEFAULT_ROOTS = [HOME_DIR / name for name in ("Desktop", "Documents", "Downloads", "Projects")]
ALLOWED_ROOTS = [
    Path(p).expanduser().resolve()
    for p in os.getenv("MCP_ALLOWED_ROOTS", ":".join(map(str, DEFAULT_ROOTS))).split(":")
    if p.strip()
]

mcp = FastMCP("mac-local", auth=auth_provider)


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    removed = len(text) - limit
    return f"{text[:half]}\n\n... [truncated {removed} chars] ...\n\n{text[-half:]}"


def _safe_path(path: str, *, must_exist: bool = False) -> Path:
    candidate = Path(path).expanduser().resolve(strict=False)
    if not any(candidate == root or candidate.is_relative_to(root) for root in ALLOWED_ROOTS):
        roots = ", ".join(str(root) for root in ALLOWED_ROOTS)
        raise PermissionError(f"Path is outside MCP_ALLOWED_ROOTS ({roots}): {candidate}")
    if must_exist and not candidate.exists():
        raise FileNotFoundError(candidate)
    return candidate


def _run(args, *, timeout: int = DEFAULT_CMD_TIMEOUT, cwd: Path | None = None, shell: bool = False) -> str:
    timeout = max(1, min(int(timeout), MAX_CMD_TIMEOUT))
    try:
        result = subprocess.run(
            args,
            shell=shell,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
            env={**os.environ, "PATH": os.getenv("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin")},
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return _truncate(f"[ERROR] Timed out after {timeout}s\n{stdout}{stderr}".strip())
    except Exception as exc:
        logger.exception("Process execution failed")
        return f"[ERROR] {type(exc).__name__}: {exc}"

    output = (result.stdout + result.stderr).strip() or "(no output)"
    prefix = f"[exit={result.returncode}]\n" if result.returncode else ""
    return _truncate(prefix + output)


# Matches "sudo" as a standalone word anywhere in a command string (start of
# string, after whitespace/&&/;/|/`/$(  etc.), so "sudo rm -rf /" and
# "echo hi && sudo reboot" are both caught. Not a sandbox against a
# determined attacker -- just a guardrail against running this by accident
# over the remote connection.
_SUDO_PATTERN = re.compile(r"(?:^|[\s;&|`(])sudo(?:[\s]|$)", re.IGNORECASE)


def _reject_sudo(command: str) -> None:
    if _SUDO_PATTERN.search(command):
        raise PermissionError(
            "sudo is blocked over the remote MCP connection. Run privileged commands locally instead."
        )


def safe_tool(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception:
            logger.exception("Tool %s failed", function.__name__)
            return f"[ERROR] {function.__name__} failed:\n{traceback.format_exc(limit=3)}"
    return wrapper


# --- high-risk: full shell -------------------------------------------------
@mcp.tool()
@safe_tool
def run_command(command: str, timeout: int = DEFAULT_CMD_TIMEOUT) -> str:
    """Run a zsh command as the current macOS user. HIGH RISK: not path-restricted. sudo is blocked."""
    logger.info("[TOOL] run_command timeout=%ss command=%s", timeout, command[:200])
    _reject_sudo(command)
    return _run(["/bin/zsh", "-lc", command], timeout=timeout)


@mcp.tool()
@safe_tool
def run_in_project(command: str, project_path: str, timeout: int = DEFAULT_CMD_TIMEOUT) -> str:
    """Run a zsh command with cwd restricted to a directory inside MCP_ALLOWED_ROOTS. sudo is blocked."""
    _reject_sudo(command)
    project = _safe_path(project_path, must_exist=True)
    return _run(["/bin/zsh", "-lc", command], timeout=timeout, cwd=project)


# --- scoped conveniences for "open an app / open a page" ------------------
@mcp.tool()
@safe_tool
def open_app(name: str) -> str:
    """Launch a macOS application by name (e.g. 'Safari', 'Visual Studio Code')."""
    return _run(["/usr/bin/open", "-a", name], timeout=15)


@mcp.tool()
@safe_tool
def open_url(url: str) -> str:
    """Open a URL in the default browser."""
    if not (url.startswith("http://") or url.startswith("https://")):
        return "[ERROR] Only http:// or https:// URLs are allowed"
    return _run(["/usr/bin/open", url], timeout=15)


# --- filesystem, restricted to ALLOWED_ROOTS -------------------------------
@mcp.tool()
@safe_tool
def read_file(path: str) -> str:
    """Read a file inside MCP_ALLOWED_ROOTS, up to MAX_READ_BYTES."""
    file_path = _safe_path(path, must_exist=True)
    if not file_path.is_file():
        return f"[ERROR] Not a regular file: {file_path}"
    size = file_path.stat().st_size
    if size > MAX_READ_BYTES:
        return f"[ERROR] File too large ({size} bytes > {MAX_READ_BYTES} cap)"
    raw = file_path.read_bytes()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("latin-1", errors="replace")
    return _truncate(content)


@mcp.tool()
@safe_tool
def write_file(path: str, content: str, overwrite: bool = False) -> str:
    """Write a UTF-8 file inside MCP_ALLOWED_ROOTS; refuses overwrite by default."""
    file_path = _safe_path(path)
    if file_path.exists() and not overwrite:
        return f"[ERROR] File exists; pass overwrite=true to replace it: {file_path}"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = content.encode("utf-8")
    file_path.write_bytes(encoded)
    return f"Written: {file_path} ({len(encoded)} bytes)"


@mcp.tool()
@safe_tool
def list_dir(path: str) -> str:
    """List a directory inside MCP_ALLOWED_ROOTS."""
    directory = _safe_path(path, must_exist=True)
    if not directory.is_dir():
        return f"[ERROR] Not a directory: {directory}"
    items = sorted(item.name + ("/" if item.is_dir() else "") for item in directory.iterdir())
    return _truncate("\n".join(items) or "(empty directory)")


# --- system info ------------------------------------------------------------
@mcp.tool()
@safe_tool
def disk_usage() -> str:
    """Show macOS filesystem usage."""
    return _run(["/bin/df", "-h"], timeout=10)


@mcp.tool()
@safe_tool
def memory_usage() -> str:
    """Show macOS VM statistics and physical-memory summary."""
    return _run(["/bin/zsh", "-lc", "sysctl -n hw.memsize; vm_stat"], timeout=10)


@mcp.tool()
@safe_tool
def running_processes() -> str:
    """List the top 20 processes by memory usage."""
    return _run(["/bin/zsh", "-lc", "ps aux -m | head -21"], timeout=10)


# --- dev workflow helpers ----------------------------------------------------
@mcp.tool()
@safe_tool
def django_manage(project_path: str, command: str, timeout: int = DEFAULT_CMD_TIMEOUT) -> str:
    """Run manage.py in an allowed Django project directory."""
    project = _safe_path(project_path, must_exist=True)
    manage_py = project / "manage.py"
    if not manage_py.is_file():
        return f"[ERROR] manage.py not found in {project}"
    python = project / ".venv" / "bin" / "python"
    executable = str(python if python.exists() else "python3")
    return _run([executable, "manage.py", *shlex.split(command)], cwd=project, timeout=timeout)


@mcp.tool()
@safe_tool
def expo_command(command: str, project_path: str, timeout: int = 300) -> str:
    """Run an Expo CLI command (e.g. 'start --tunnel') in a project directory."""
    project = _safe_path(project_path, must_exist=True)
    return _run(f"npx expo {command}", timeout=timeout, cwd=project, shell=True)


@mcp.tool()
@safe_tool
def npm_install(project_path: str, packages: str = "") -> str:
    """Run npm install (optionally with package names) in a project."""
    project = _safe_path(project_path, must_exist=True)
    return _run(f"npm install {packages}".strip(), timeout=300, cwd=project, shell=True)


# --- browser automation (Playwright), one shared page across calls --------
_pw_lock = asyncio.Lock()
_pw_state: dict[str, object] = {"playwright": None, "browser": None, "page": None}
SCREENSHOT_DIR = Path(__file__).parent / "screenshots"


async def _get_page() -> Page:
    """Lazily start Chromium and return the single shared Page, creating it if needed."""
    async with _pw_lock:
        if _pw_state["page"] is None:
            pw: Playwright = await async_playwright().start()
            browser: Browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            _pw_state.update(playwright=pw, browser=browser, page=page)
            logger.info("[browser] Chromium started")
        return _pw_state["page"]  # type: ignore[return-value]


@mcp.tool()
@safe_tool
async def browser_goto(url: str, wait_until: str = "load", timeout: int = 30000) -> str:
    """Open a URL in the shared headless browser tab (starts the browser on first use)."""
    if not (url.startswith("http://") or url.startswith("https://")):
        return "[ERROR] Only http:// or https:// URLs are allowed"
    page = await _get_page()
    response = await page.goto(url, wait_until=wait_until, timeout=timeout)
    title = await page.title()
    status = response.status if response else "?"
    return f"Loaded {page.url} (status={status})\nTitle: {title}"


@mcp.tool()
@safe_tool
async def browser_click(selector: str, timeout: int = 10000) -> str:
    """Click the first element matching a CSS selector on the current page."""
    page = await _get_page()
    await page.click(selector, timeout=timeout)
    return f"Clicked: {selector}"


@mcp.tool()
@safe_tool
async def browser_fill(selector: str, text: str, timeout: int = 10000) -> str:
    """Fill a form field matching a CSS selector with text."""
    page = await _get_page()
    await page.fill(selector, text, timeout=timeout)
    return f"Filled {selector} ({len(text)} chars)"


@mcp.tool()
@safe_tool
async def browser_get_text(selector: str = "body", timeout: int = 10000) -> str:
    """Get the visible text content of an element (default: whole page)."""
    page = await _get_page()
    element = page.locator(selector).first
    text = await element.inner_text(timeout=timeout)
    return _truncate(text)


@mcp.tool()
@safe_tool
async def browser_screenshot(full_page: bool = True) -> str:
    """Save a screenshot of the current page under MCP/screenshots and return its path."""
    page = await _get_page()
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SCREENSHOT_DIR / f"shot-{int(time.time())}.png"
    await page.screenshot(path=str(out_path), full_page=full_page)
    return f"Saved: {out_path}"


@mcp.tool()
@safe_tool
async def browser_close() -> str:
    """Close the shared browser and free resources (next browser_goto restarts it)."""
    async with _pw_lock:
        browser = _pw_state.get("browser")
        pw = _pw_state.get("playwright")
        if browser is not None:
            await browser.close()  # type: ignore[union-attr]
        if pw is not None:
            await pw.stop()  # type: ignore[union-attr]
        _pw_state.update(playwright=None, browser=None, page=None)
    return "Browser closed"


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "streamable-http").lower()
    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "streamable-http":
        host = os.getenv("MCP_HOST", "127.0.0.1")
        port = int(os.getenv("MCP_PORT", "8091"))
        logger.info("Starting Auth0-protected MCP on %s:%s (base_url=%s)", host, port, BASE_URL)
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        raise ValueError("MCP_TRANSPORT must be 'stdio' or 'streamable-http'")
