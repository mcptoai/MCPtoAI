"""Araç onayından önce yan etkisiz yol, uzantı ve boyut doğrulaması."""
from __future__ import annotations

from pathlib import Path

from .sensitive_paths import check_path, _windows_long_path

ARTIFACT_EXTENSIONS = frozenset({
    ".mp4", ".webm", ".mov", ".mp3", ".wav", ".m4a",
    ".png", ".jpg", ".jpeg", ".webp", ".pdf", ".docx", ".xlsx",
    ".csv", ".txt", ".zip", ".pptx", ".md", ".json", ".log",
    ".srt", ".vtt", ".gif", ".7z", ".gz",
})
MAX_ARTIFACT_BYTES = 1024 * 1024 * 1024
PATH_FIELDS = {"read_file": "path", "write_file": "path", "list_dir": "path",
               "find_files": "root", "send_artifact": "path"}
# Shell araçları ve uzak MCP sunucuları burada kasıtlı olarak kapsam dışındadır.


def validate(tool: str, args: dict, cfg) -> tuple[str | None, dict]:
    """(Ret gerekçesi, onay kartı metaverisi); ret modeli yönlendirir."""
    field = PATH_FIELDS.get(tool)
    if field is None:
        return None, {}
    raw = args.get(field)
    if not isinstance(raw, str) or not raw.strip():
        return "Invalid path argument", {}
    try:
        candidate = Path(_windows_long_path(raw) if __import__("os").name == "nt" else raw).expanduser().resolve(strict=False)
        check_path(candidate, write=tool == "write_file")
        allowed = any(candidate == root.resolve(strict=False) or
                      candidate.is_relative_to(root.resolve(strict=False))
                      for root in cfg.allowed_roots)
        if not allowed:
            return "Path is outside allowed workspace", {}
        if tool in {"read_file", "send_artifact", "list_dir", "find_files"}:
            if not candidate.exists():
                return "Path does not exist", {}
        if tool in {"read_file", "send_artifact"} and not candidate.is_file():
            return "Expected a regular file", {}
        if tool in {"list_dir", "find_files"} and not candidate.is_dir():
            return "Expected a directory", {}
        if tool == "read_file" and candidate.stat().st_size > cfg.max_read_bytes:
            return "File is too large to read", {}
        if tool == "send_artifact":
            size = candidate.stat().st_size
            if size <= 0 or size > MAX_ARTIFACT_BYTES:
                return "Artifact file size must be between 1 byte and 1 GiB", {}
            ext = candidate.suffix.casefold()
            if ext not in ARTIFACT_EXTENSIONS:
                return "Unsupported artifact file extension", {}
            return None, {"file_size_bytes": size, "file_type": ext}
        if tool == "write_file":
            content = args.get("content")
            if not isinstance(content, str):
                return "Invalid content argument", {}
            if candidate.exists() and not candidate.is_file():
                return "Cannot overwrite a directory", {}
            overwrite = bool(args.get("overwrite", False))
            if candidate.exists() and not overwrite:
                return "File already exists; overwrite=true required", {}
            # Henüz var olmayan yolun var olan üst dizinini de doğrula.
            parent = candidate.parent
            while not parent.exists() and parent.parent != parent:
                parent = parent.parent
            check_path(parent.resolve(strict=False), write=True)
            return None, {"file_action": "overwrite" if candidate.exists() else "new file"}
    except PermissionError as exc:
        # Yalnızca kategori döner; mutlak dosya adı döndürülmez.
        message = str(exc)
        return message if message.startswith("Protected location:") else "Path is not permitted", {}
    except (OSError, ValueError) as exc:
        return f"Invalid or unavailable path ({type(exc).__name__})", {}
    return None, {}
