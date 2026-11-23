"""Bounded, no-follow subfolder creation under one previously approved workspace.

POSIX uses openat/mkdirat relative to held directory descriptors. Windows uses native NT handle-relative directory creation and rejects reparse points.
"""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import threading
import unicodedata


_LOCK = threading.RLock()
_WINDOWS_RESERVED = re.compile(r'^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$', re.I)
_MAX_COMPONENTS = 16


def _parts(relative: str, *, allow_windows_separators: bool = False) -> tuple[str, ...]:
    if not isinstance(relative, str) or not 0 < len(relative) <= 1024:
        raise ValueError('subfolder_invalid_path')
    if '\x00' in relative or relative.startswith(('/', '~', '\\')) or ('\\' in relative and not allow_windows_separators):
        raise ValueError('subfolder_absolute_or_ambiguous')
    if PureWindowsPath(relative).drive or PurePosixPath(relative).is_absolute():
        raise ValueError('subfolder_absolute_or_ambiguous')
    parts = tuple((relative.replace('\\', '/') if allow_windows_separators else relative).split('/'))
    if not 1 <= len(parts) <= _MAX_COMPONENTS:
        raise ValueError('subfolder_component_limit')
    for name in parts:
        if (not name or name in ('.', '..') or name.startswith('~') or
            name.endswith(('.', ' ')) or ':' in name or
            any(ord(c) < 32 or ord(c) == 127 for c in name) or
            len(name.encode('utf-8')) > 255 or _WINDOWS_RESERVED.match(name) or
            unicodedata.normalize('NFC', name) != name or
            re.search(r'~[0-9]+$', name)):
            raise ValueError('subfolder_invalid_component:' + repr(name[:80]))
    return parts


def _alias_exists(fd: int, name: str) -> bool:
    normalized = unicodedata.normalize('NFC', name).casefold()
    return any(unicodedata.normalize('NFC', existing).casefold() == normalized
               for existing in os.listdir(fd))


def create_subfolder(workspace: str, relative: str, allowed_roots: list[Path], *, check_path) -> Path:
    parts = _parts(relative, allow_windows_separators=True)
    if not isinstance(workspace, str) or not workspace:
        raise ValueError('subfolder_workspace_invalid')
    selected = Path(workspace).expanduser()
    if selected.is_symlink() or not selected.is_absolute():
        raise PermissionError('subfolder_workspace_invalid')
    root = selected.resolve(strict=True)
    permitted = {p.resolve(strict=True) for p in allowed_roots if p.is_dir()}
    if root != selected or root not in permitted or not root.is_dir():
        raise PermissionError('subfolder_workspace_not_approved')
    check_path(root, write=True)
    if os.name == 'nt':
        from ._windows_subfolders import create_windows_subfolder
        return create_windows_subfolder(root, parts, check_path=check_path)
    target = root.joinpath(*parts)
    check_path(target, write=True)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    opened: list[int] = []
    created: list[tuple[int, str]] = []
    success = False
    with _LOCK:
        try:
            fd = os.open(root, flags)
            opened.append(fd)
            if os.fstat(fd).st_ino != root.stat().st_ino or os.fstat(fd).st_dev != root.stat().st_dev:
                raise PermissionError('subfolder_workspace_changed')
            for index, name in enumerate(parts):
                aliases = [entry for entry in os.listdir(fd) if unicodedata.normalize('NFC', entry).casefold() == name.casefold()]
                if aliases and (aliases != [name] or index == len(parts) - 1):
                    raise FileExistsError('subfolder_name_collision')
                if not aliases:
                    try:
                        os.mkdir(name, mode=0o700, dir_fd=fd)
                    except FileExistsError as exc:
                        raise FileExistsError('subfolder_name_collision') from exc
                    created.append((fd, name))
                try:
                    child = os.open(name, flags, dir_fd=fd)
                except OSError as exc:
                    raise PermissionError('subfolder_reparse_symlink_or_not_directory') from exc
                opened.append(child)
                fd = child
                # Defensive post-create check. Directory-FD operations prevent
                # traversing symlinks even when an attacker changes the path.
                current = root.joinpath(*parts[:index+1])
                if current.is_symlink() or current.resolve(strict=True) != current:
                    raise PermissionError('subfolder_path_swapped')
                check_path(current, write=True)
            if not target.is_dir() or target.resolve(strict=True) != target:
                raise PermissionError('subfolder_final_path_changed')
            success = True
            return target
        finally:
            if not success:
                # Only remove our new *empty* directories, via original parent
                # handles. Never remove anything pre-existing or non-empty.
                for parent_fd, name in reversed(created):
                    try:
                        os.rmdir(name, dir_fd=parent_fd)
                    except OSError:
                        pass
            for fd in reversed(opened):
                os.close(fd)


def _tag_inbound_error(exc: OSError, operation: str, kind: str, component: str = '') -> OSError:
    """Attach diagnostic context without logging full user filesystem paths."""
    exc.stage = operation
    exc.operation = operation
    exc.kind = kind
    exc.path_component = component[:120]
    return exc


def _inbound_root(workspace: str, allowed_roots: list[Path]) -> Path:
    """Inbound creation accepts one explicitly approved workspace, not any descendant."""
    if not isinstance(workspace, str) or not workspace:
        raise ValueError('subfolder_workspace_invalid')
    selected = Path(workspace)
    if not selected.is_absolute() or selected.is_symlink():
        raise PermissionError('subfolder_workspace_invalid')
    root = selected.resolve(strict=True)
    permitted = {p.resolve(strict=True) for p in allowed_roots if p.is_dir()}
    if root != selected or root not in permitted or not root.is_dir():
        raise PermissionError('subfolder_workspace_not_approved')
    return root


def _inbound_guard(check_path, path: Path) -> None:
    try:
        check_path(path, write=True)
    except PermissionError as exc:
        raise _tag_inbound_error(PermissionError('subfolder_protected_path'),
                                 'validate_sensitive_path','subfolder',path.name) from exc


def _safe_existing_directory(entry: Path, found) -> None:
    import stat
    if stat.S_ISLNK(found.st_mode) or not stat.S_ISDIR(found.st_mode):
        raise PermissionError('subfolder_reparse_symlink_or_not_directory')
    if os.name == 'nt' and (getattr(found,'st_file_attributes',0) & 0x400):
        from ._windows_subfolders import safe_directory_reparse_tag, _reparse_failure
        tag=getattr(found,'st_reparse_tag',None)
        if not safe_directory_reparse_tag(tag):
            raise _reparse_failure(tag if isinstance(tag,int) else 0)


def plan_inbound_subfolder(workspace: str, relative: str, allowed_roots: list[Path], *, check_path) -> tuple[Path, bool]:
    """Read-only preview: reject aliases and reparse/symlink parents; do not create."""
    import stat
    parts = _parts(relative)
    root = _inbound_root(workspace, allowed_roots)
    _inbound_guard(check_path, root)
    parent = root
    needs_creation = False
    for part in parts:
        candidate = parent / part
        if needs_creation:
            parent = candidate
            continue
        folded = unicodedata.normalize("NFC",part).casefold()
        if any(unicodedata.normalize("NFC",entry.name).casefold()==folded and entry.name!=part for entry in parent.iterdir()):
            raise FileExistsError("subfolder_name_collision")
        try:
            found = os.lstat(candidate)
        except FileNotFoundError:
            needs_creation = True
            parent = candidate
            continue
        _safe_existing_directory(candidate, found)
        if candidate.resolve(strict=True) != candidate:
            raise PermissionError('subfolder_path_changed')
        if any(unicodedata.normalize('NFC', entry.name).casefold() == part.casefold() and entry.name != part
               for entry in parent.iterdir()):
            raise FileExistsError('subfolder_name_collision')
        parent = candidate
    planned = root.joinpath(*parts)
    _inbound_guard(check_path, planned)
    return planned, needs_creation


def ensure_inbound_subfolder(workspace: str, relative: str, allowed_roots: list[Path], *, check_path) -> Path:
    """Only call after consuming the trusted one-use transfer approval grant.

    POSIX holds parent directory FDs and uses mkdirat/openat(O_NOFOLLOW).
    Windows delegates to native handle-relative creation, never Path.mkdir.
    """
    parts = _parts(relative)
    root = _inbound_root(workspace, allowed_roots)
    _inbound_guard(check_path, root)
    if os.name == 'nt':
        from ._windows_subfolders import ensure_windows_inbound_subfolder
        return ensure_windows_inbound_subfolder(root, parts, check_path=lambda p,write=True:_inbound_guard(check_path,p))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    opened, created = [], []
    success = False
    with _LOCK:
        try:
            try:
                fd = os.open(root, flags)
            except OSError as exc:
                raise _tag_inbound_error(exc,'openat_root','workspace',root.name)
            opened.append(fd)
            if (os.fstat(fd).st_dev, os.fstat(fd).st_ino) != (root.stat().st_dev, root.stat().st_ino):
                raise PermissionError('subfolder_workspace_changed')
            for i, part in enumerate(parts):
                aliases = [n for n in os.listdir(fd) if unicodedata.normalize('NFC', n).casefold() == part.casefold()]
                if aliases and aliases != [part]:
                    raise FileExistsError('subfolder_name_collision')
                if not aliases:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=fd)
                    except OSError as exc:
                        raise _tag_inbound_error(exc,'mkdirat','subfolder',part)
                    created.append((fd, part))
                try:
                    child = os.open(part, flags, dir_fd=fd)
                except OSError as exc:
                    raise _tag_inbound_error(exc,'openat_nofollow','subfolder',part)
                opened.append(child)
                fd = child
                path = root.joinpath(*parts[:i+1])
                if path.is_symlink() or path.resolve(strict=True) != path:
                    raise PermissionError('subfolder_path_changed')
                _inbound_guard(check_path, path)
                if (os.fstat(fd).st_dev, os.fstat(fd).st_ino) != (path.stat().st_dev, path.stat().st_ino):
                    raise PermissionError('subfolder_directory_changed')
            success = True
            return root.joinpath(*parts)
        finally:
            if not success:
                for parent_fd, name in reversed(created):
                    try: os.rmdir(name, dir_fd=parent_fd)
                    except OSError: pass
            for fd in reversed(opened):
                os.close(fd)
