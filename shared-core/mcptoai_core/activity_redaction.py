"""Fail-closed activity target rendering; never serialize raw tool arguments."""
from __future__ import annotations

import os
import re
import shlex
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

HIDDEN = "[CONTENT HIDDEN]"

# SafeDisplay is an opaque capability value, not a string. The constructor
# rejects direct calls; only this module's allowlisted renderers mint values.
_MINT_KEY = object()


class SafeDisplay:
    __slots__ = ("_value",)

    def __init__(self, value: str, *, _key: object = None):
        if _key is not _MINT_KEY:
            raise TypeError("SafeDisplay must be created by activity_redaction")
        self._value = value

    @property
    def value(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "SafeDisplay(<redacted>)"


def _mint(value: str) -> SafeDisplay:
    if not isinstance(value, str):
        value = HIDDEN
    return SafeDisplay(value, _key=_MINT_KEY)


def hidden() -> SafeDisplay:
    return _mint(HIDDEN)


def safe_summary(value: object) -> SafeDisplay:
    """No arbitrary summaries: callers supply a fixed status code only."""
    allowed = {
        "requested": "Tool requested", "approval_pending": "Permission pending",
        "approved": "Permission approved", "denied": "Permission denied",
        "started": "Tool started", "completed": "Tool completed",
        "failed": "Tool failed", "cancelled": "Tool cancelled",
        "timed_out": "Tool timed out",
    }
    return _mint(allowed.get(value, HIDDEN))


def restore_display(value: object) -> SafeDisplay:
    """Cihazın KENDİ aktivite kaydından okunan gösterim metni.

    Ham argüman değildir (yazılırken render_* ile üretilmiştir); yine de okunurken
    yeniden taranır: gizli anahtar desenleri, uzun kodlanmış diziler ve aşırı uzunluk gizlenir.
    Ağdan gelen (güvenilmeyen) yükler için kullanılmaz.
    """
    if not isinstance(value, str):
        return hidden()
    text = _normalize(value)
    if text == HIDDEN:
        return hidden()
    if not text or len(text) > 256 or not text.isprintable() or _SENSITIVE.search(text):
        return hidden()
    if any(_BASE64.fullmatch(part) for part in text.split()):
        return hidden()
    return _mint(text)


def safe_target(kind: str, value: str, *, home: str | None = None,
                mcp_tool: str = "") -> SafeDisplay:
    return _mint(render_target(kind, value, home=home, mcp_tool=mcp_tool))

_REDACTED = "[REDACTED]"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_SAFE_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
_SAFE_PATH_PART = re.compile(r"^[A-Za-z0-9_. @()+-]{1,120}$")
_SENSITIVE = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{5,}|gh[pousr]_[A-Za-z0-9_]{5,}|AKIA[A-Z0-9]{16}|"
    r"eyJ[A-Za-z0-9_-]{12,}(?:\.[A-Za-z0-9_-]+){1,2}|"
    r"-----BEGIN [^-\n]*PRIVATE KEY-----|"
    r"(?:api[_-]?key|password|secret|token|authorization)\s*[:=]\s*\S+|"
    r"bearer\s+\S+)"
)
_BASE64 = re.compile(r"^[A-Za-z0-9+/]{48,}={0,2}$")


def _normalize(value: str) -> str:
    # Remove formatting controls before scanning; prevents zero-width splitting.
    return "".join(ch for ch in unicodedata.normalize("NFKC", value)
                   if unicodedata.category(ch) != "Cf")


def _safe_label(value: str) -> str:
    value = _normalize(value)
    return value if _SAFE_NAME.fullmatch(value) and not _SENSITIVE.search(value) else HIDDEN


def render_command(command: str) -> str:
    """Show only an allowlisted executable and action, never arbitrary arguments."""
    try:
        if not isinstance(command, str) or not command.strip():
            return HIDDEN
        command = _normalize(command)
        # Do not parse complex shell programs as if they were a single safe command.
        if any(c in command for c in "\n\r\x00" ) or "$(" in command or "`" in command:
            return HIDDEN
        lexer = shlex.shlex(command, posix=True, punctuation_chars='|;&<>')
        lexer.whitespace_split = True
        parts = list(lexer)
        if any(re.fullmatch(r'[|;&<>]+', part) for part in parts):
            return HIDDEN
        if not parts:
            return HIDDEN
        # Leading environment assignments can contain arbitrary secrets; discard.
        while parts and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", parts[0], re.S):
            parts.pop(0)
        if not parts:
            return HIDDEN
        exe = os.path.basename(parts[0]).lower()
        if exe in {"curl", "wget"}:
            return exe + " [arguments hidden]"
        if exe == "git":
            action = parts[1] if len(parts) > 1 else ""
            return "git " + action + " [arguments hidden]" if action in {"clone", "fetch", "pull", "push", "status", "diff", "log", "checkout"} else "git [arguments hidden]"
        if exe in {"python", "python3", "pytest", "node", "npm", "pip", "pip3", "ssh", "scp", "psql", "redis-cli"}:
            return exe + " [arguments hidden]"
        return HIDDEN
    except Exception:
        return HIDDEN


def render_file(path: str, home: str | None = None) -> str:
    """Show a local file path with home abbreviated; never open/read the file."""
    try:
        if not isinstance(path, str) or not path or "\x00" in path:
            return HIDDEN
        path = _normalize(path)
        home = os.path.expanduser("~") if home is None else home
        if home and (path == home or path.startswith(home.rstrip("/") + "/")):
            path = "~" + path[len(home):]
        elif path.startswith("/Users/") or path.startswith("/home/") or re.match(r"(?i)^C:\\Users\\", path):
            return HIDDEN  # Unknown user's home: never expose username.
        parts = re.split(r"[/\\]", path)
        if any(not _SAFE_PATH_PART.fullmatch(p) for p in parts if p and p != "~"):
            return HIDDEN
        if _SENSITIVE.search(path) or _BASE64.fullmatch(path):
            return HIDDEN
        return path[:256]
    except Exception:
        return HIDDEN


def render_url(url: str) -> str:
    """Retain only scheme + hostname + safe path; strip credentials, query and fragment."""
    try:
        if not isinstance(url, str):
            return HIDDEN
        url = _normalize(url)
        parsed = urlsplit(url)
        if parsed.scheme not in {"https", "http", "postgres", "postgresql", "redis", "rediss"}:
            return HIDDEN
        host = parsed.hostname or ""
        if not _SAFE_HOST.fullmatch(host):
            return HIDDEN
        path = parsed.path
        if len(path) > 120 or any(not _SAFE_PATH_PART.fullmatch(p) for p in path.split("/") if p):
            path = "/[path hidden]"
        if _SENSITIVE.search(path):
            path = "/[path hidden]"
        return f"{parsed.scheme}://{host}{path}"
    except Exception:
        return HIDDEN


def render_mcp(server: str, tool: str, arguments: object = None) -> str:
    """Ignore all third-party arguments regardless of shape."""
    try:
        s, t = _safe_label(server), _safe_label(tool)
        return f"{s} / {t}" if HIDDEN not in (s, t) else HIDDEN
    except Exception:
        return HIDDEN


def render_target(kind: str, value: str, *, home: str | None = None, mcp_tool: str = "") -> str:
    if kind == "command":
        return render_command(value)
    if kind == "file":
        return render_file(value, home)
    if kind == "url":
        return render_url(value)
    if kind == "mcp":
        return render_mcp(value, mcp_tool)
    if kind == "application":
        return _safe_label(value)
    return HIDDEN
