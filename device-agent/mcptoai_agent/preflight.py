"""Araç onayından önce yan etkisiz yol, uzantı ve boyut doğrulaması."""
from __future__ import annotations

from pathlib import Path

from .sensitive_paths import check_path, _windows_long_path
from .workspace_policy import within_allowed_roots

ARTIFACT_EXTENSIONS = frozenset({
    ".mp4", ".webm", ".mov", ".mp3", ".wav", ".m4a",
    ".png", ".jpg", ".jpeg", ".webp", ".pdf", ".docx", ".xlsx",
    ".csv", ".txt", ".zip", ".pptx", ".md", ".json", ".log",
    ".srt", ".vtt", ".gif", ".7z", ".gz",
})
MAX_ARTIFACT_BYTES = 1024 * 1024 * 1024
PATH_FIELDS = {"read_file": "path", "write_file": "path", "list_dir": "path",
               "find_files": "root", "send_artifact": "path", "create_folder": "workspace"}
# Shell araçları ve uzak MCP sunucuları burada kasıtlı olarak kapsam dışındadır.


def validate(tool: str, args: dict, cfg, language: str = "en") -> tuple[str | None, dict]:
    """(Ret gerekçesi, onay kartı metaverisi); ret modeli yönlendirir."""
    field = PATH_FIELDS.get(tool)
    if field is None:
        return None, {}
    raw = args.get(field)
    if not isinstance(raw, str) or not raw.strip():
        if tool == "create_folder":
            from .folder_errors import localized_folder_status
            return localized_folder_status("invalid_root", language), {}
        return "Invalid path argument", {}
    if tool == "create_folder":
        from mcptoai_core.safe_subfolders import _parts, plan_inbound_subfolder
        from .folder_errors import folder_error_localized, localized_folder_status
        try:
            _parts(args.get("relative_path"), allow_windows_separators=True)
            raw_workspace = args.get("workspace")
            if not isinstance(raw_workspace, str) or not raw_workspace:
                return localized_folder_status("invalid_root", language), {}
            selected = Path(raw_workspace).expanduser()
            if not selected.is_absolute() or selected.is_symlink():
                return localized_folder_status("invalid_root", language), {}
            selected = selected.resolve(strict=True)
            if selected not in {root.resolve(strict=True) for root in cfg.allowed_roots if root.is_dir()}:
                return localized_folder_status("unapproved_root", language), {}
            normalized = '/'.join(_parts(args['relative_path'], allow_windows_separators=True))
            planned, _missing = plan_inbound_subfolder(str(selected), normalized,cfg.allowed_roots,check_path=check_path)
            if planned.exists():
                # Validation above already rejected aliases, junctions, symlinks,
                # and files. This is a successful idempotent no-op, not a denial.
                return None, {"file_action": "already exists (no change)",
                              "relative_path": normalized, "folders_to_create": [],
                              "already_exists": True}
            parts = _parts(args['relative_path'], allow_windows_separators=True)
            missing = []
            for index in range(len(parts)):
                candidate = selected.joinpath(*parts[:index+1])
                if not candidate.exists():
                    missing.append('/'.join(parts[:index+1]))
            return None, {"file_action": "create folder", "relative_path": '/'.join(parts),
                          "folders_to_create": missing}

        except (ValueError, PermissionError, OSError) as exc:
            return folder_error_localized(exc, language), {}
    try:
        candidate = Path(_windows_long_path(raw) if __import__("os").name == "nt" else raw).expanduser().resolve(strict=False)
        check_path(candidate, write=tool == "write_file")
        if not within_allowed_roots(candidate, cfg.allowed_roots):
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
            if not candidate.parent.is_dir():
                return "Parent folder must already exist", {}
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
