"""Win32 handle-relative, fail-closed directory creation for approved roots.

This module is imported only on Windows. Child operations use NtCreateFile with
RootDirectory set to a held directory handle; they never traverse a mutable
absolute path after the workspace has been opened. Do not replace this with
Path.mkdir / CreateDirectoryW on concatenated user strings.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import unicodedata

_KERNEL = ctypes.WinDLL('kernel32', use_last_error=True)
_NT = ctypes.WinDLL('ntdll', use_last_error=True)
_INVALID = ctypes.c_void_p(-1).value
_FILE_LIST_DIRECTORY = 0x0001
_FILE_ADD_SUBDIRECTORY = 0x0004
_FILE_READ_ATTRIBUTES = 0x0080
_DELETE = 0x00010000
_SYNCHRONIZE = 0x00100000
_READ_CONTROL = 0x00020000
_SHARE_ALL = 7
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_CREATE = 2
_FILE_DIRECTORY_FILE = 1
_FILE_SYNCHRONOUS_IO_NONALERT = 0x20
_OBJ_CASE_INSENSITIVE = 0x40
_OBJ_DONT_REPARSE = 0x1000
_FILE_ATTRIBUTE_TAG_INFO = 9
_FILE_DISPOSITION_INFO = 4
_STATUS_OBJECT_NAME_COLLISION = 0xC0000035

class _UnicodeString(ctypes.Structure):
    _fields_ = [('Length', wintypes.USHORT), ('MaximumLength', wintypes.USHORT),
                ('Buffer', wintypes.LPWSTR)]

class _ObjectAttributes(ctypes.Structure):
    _fields_ = [('Length', wintypes.ULONG), ('RootDirectory', wintypes.HANDLE),
                ('ObjectName', ctypes.POINTER(_UnicodeString)),
                ('Attributes', wintypes.ULONG), ('SecurityDescriptor', ctypes.c_void_p),
                ('SecurityQualityOfService', ctypes.c_void_p)]

class _IOStatusBlock(ctypes.Structure):
    _fields_ = [('Status', ctypes.c_void_p), ('Information', ctypes.c_size_t)]

class _DispositionInfo(ctypes.Structure):
    _fields_ = [('DeleteFile', wintypes.BOOL)]

class _AttributeTagInfo(ctypes.Structure):
    _fields_ = [('FileAttributes', wintypes.DWORD), ('ReparseTag', wintypes.DWORD)]

_KERNEL.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_KERNEL.CreateFileW.restype = wintypes.HANDLE
_KERNEL.CloseHandle.argtypes = [wintypes.HANDLE]
_KERNEL.CloseHandle.restype = wintypes.BOOL
_KERNEL.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                   ctypes.c_void_p, wintypes.DWORD]
_KERNEL.GetFileInformationByHandleEx.restype = wintypes.BOOL
_KERNEL.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
_KERNEL.SetFileInformationByHandle.restype = wintypes.BOOL
_KERNEL.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR,
                                              wintypes.DWORD, wintypes.DWORD]
_KERNEL.GetFinalPathNameByHandleW.restype = wintypes.DWORD
_NT.NtCreateFile.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                             ctypes.POINTER(_ObjectAttributes), ctypes.POINTER(_IOStatusBlock),
                             ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG,
                             wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG]
_NT.NtCreateFile.restype = ctypes.c_long


def _win_error(operation):
    raise PermissionError('subfolder_win32_' + operation)


# Microsoft CFAPI placeholder tags: CLOUD and CLOUD_1..CLOUD_F.
# These are not name-surrogate redirections; never permit symlink, junction,
# mount-point or unknown reparse tags just because a path is under OneDrive.
_CLOUD_BASE_TAG = 0x9000001A
_SYMLINK_TAG = 0xA000000C
_MOUNT_POINT_TAG = 0xA0000003


def safe_directory_reparse_tag(tag: int) -> bool:
    return isinstance(tag,int) and (tag & 0xFFFF0FFF) == _CLOUD_BASE_TAG


def _reparse_failure(tag: int) -> PermissionError:
    label = ('symlink' if tag == _SYMLINK_TAG else
             'junction_or_mount_point' if tag == _MOUNT_POINT_TAG else
             'unknown_reparse_tag')
    return PermissionError('subfolder_reparse_' + label + ':' + hex(tag))


def _tag_check(handle):
    info = _AttributeTagInfo()
    if not _KERNEL.GetFileInformationByHandleEx(handle, _FILE_ATTRIBUTE_TAG_INFO,
                                                 ctypes.byref(info), ctypes.sizeof(info)):
        _win_error('metadata_unavailable')
    if info.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        if not safe_directory_reparse_tag(info.ReparseTag):
            raise _reparse_failure(info.ReparseTag)
    if not info.FileAttributes & _FILE_ATTRIBUTE_DIRECTORY:
        _win_error('not_directory')


def _remove_created_empty_directory(handle):
    # DELETE is granted at creation. A non-empty directory will not be removed.
    marker = _DispositionInfo(1)
    _KERNEL.SetFileInformationByHandle(handle, _FILE_DISPOSITION_INFO,
                                        ctypes.byref(marker), ctypes.sizeof(marker))


def _real_name(handle):
    length = _KERNEL.GetFinalPathNameByHandleW(handle, None, 0, 0)
    if not 0 < length <= 32768:
        _win_error('path_unavailable')
    buf = ctypes.create_unicode_buffer(length + 2)
    used = _KERNEL.GetFinalPathNameByHandleW(handle, buf, len(buf), 0)
    if used < 1 or used >= len(buf):
        _win_error('path_unavailable')
    name = buf.value
    if name.startswith('\\\\?\\UNC\\'):
        _win_error('network_share')
    if name.startswith('\\\\?\\'):
        name = name[4:]
    if name.startswith('\\\\'):
        _win_error('network_share')
    return os.path.normcase(os.path.normpath(name))


def _open_root(path):
    handle = _KERNEL.CreateFileW(str(path),
        _FILE_LIST_DIRECTORY | _FILE_ADD_SUBDIRECTORY | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE | _READ_CONTROL,
        _SHARE_ALL, None, _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT, None)
    if handle == _INVALID or handle is None:
        _win_error('root_open_denied')
    try:
        _tag_check(handle)
        if _real_name(handle) != os.path.normcase(os.path.normpath(str(path))):
            _win_error('root_changed')
        return handle
    except BaseException:
        _KERNEL.CloseHandle(handle)
        raise


def _make_child(parent, component):
    # A component-only native name with an owned parent HANDLE prevents junction
    # traversal or substitution of intermediate paths between checks and create.
    buffer = ctypes.create_unicode_buffer(component)
    name = _UnicodeString(len(component.encode('utf-16-le')),
                          (len(component.encode('utf-16-le')) + 2), ctypes.cast(buffer, wintypes.LPWSTR))
    attrs = _ObjectAttributes(ctypes.sizeof(_ObjectAttributes), parent,
                              ctypes.pointer(name), _OBJ_CASE_INSENSITIVE | _OBJ_DONT_REPARSE,
                              None, None)
    result = wintypes.HANDLE()
    iosb = _IOStatusBlock()
    status = _NT.NtCreateFile(ctypes.byref(result),
        _FILE_LIST_DIRECTORY | _FILE_ADD_SUBDIRECTORY | _FILE_READ_ATTRIBUTES | _DELETE | _SYNCHRONIZE | _READ_CONTROL,
        ctypes.byref(attrs), ctypes.byref(iosb), None,
        _FILE_ATTRIBUTE_DIRECTORY, _SHARE_ALL, _FILE_CREATE,
        _FILE_DIRECTORY_FILE | _FILE_SYNCHRONOUS_IO_NONALERT | _FILE_FLAG_OPEN_REPARSE_POINT,
        None, 0)
    if status != 0:
        if status & 0xffffffff == _STATUS_OBJECT_NAME_COLLISION:
            raise FileExistsError('subfolder_name_collision')
        _win_error('create_denied')
    try:
        _tag_check(result)
        return result
    except BaseException:
        _remove_created_empty_directory(result)
        _KERNEL.CloseHandle(result)
        raise


def create_windows_subfolder(root: Path, parts: tuple[str, ...], *, check_path) -> Path:
    """Create missing path components under held handles; refuse existing target."""
    target = root.joinpath(*parts)
    handle = _open_root(root)
    handles = [handle]
    created = []
    success = False
    try:
        parent = root
        for index, component in enumerate(parts):
            folded = unicodedata.normalize('NFC', component).casefold()
            try:
                entries = os.listdir(parent)
            except OSError:
                _win_error('enumeration_denied')
            aliases = [entry for entry in entries if unicodedata.normalize('NFC', entry).casefold() == folded]
            if aliases and (aliases != [component] or index == len(parts)-1):
                raise FileExistsError('subfolder_name_collision')
            child_path = parent / component
            check_path(child_path, write=True)
            if _real_name(handle) != os.path.normcase(os.path.normpath(str(parent))):
                _win_error('parent_changed')
            child = _open_existing_child(handle, component) if aliases else _make_child(handle, component)
            if not aliases:
                created.append(child)
            handles.append(child)
            if _real_name(child) != os.path.normcase(os.path.normpath(str(child_path))):
                _win_error('child_moved')
            parent, handle = child_path, child
        check_path(target, write=True)
        if _real_name(handle) != os.path.normcase(os.path.normpath(str(target))):
            _win_error('final_path_changed')
        success = True
        return target
    finally:
        if not success:
            for child in reversed(created):
                _remove_created_empty_directory(child)
        for handle in reversed(handles):
            _KERNEL.CloseHandle(handle)


def _open_existing_child(parent, component):
    """Open a child without following a junction; RootDirectory is held."""
    buffer = ctypes.create_unicode_buffer(component)
    encoded = component.encode('utf-16-le')
    name = _UnicodeString(len(encoded), len(encoded)+2, ctypes.cast(buffer, wintypes.LPWSTR))
    attrs = _ObjectAttributes(ctypes.sizeof(_ObjectAttributes), parent,
                              ctypes.pointer(name), _OBJ_CASE_INSENSITIVE,
                              None, None)
    result = wintypes.HANDLE()
    iosb = _IOStatusBlock()
    status = _NT.NtCreateFile(ctypes.byref(result),
        _FILE_LIST_DIRECTORY | _FILE_ADD_SUBDIRECTORY | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE | _READ_CONTROL,
        ctypes.byref(attrs), ctypes.byref(iosb), None,
        _FILE_ATTRIBUTE_DIRECTORY, _SHARE_ALL, 1,  # FILE_OPEN, not create
        _FILE_DIRECTORY_FILE | _FILE_SYNCHRONOUS_IO_NONALERT | _FILE_FLAG_OPEN_REPARSE_POINT,
        None, 0)
    if status != 0:
        _win_error('existing_child_open_denied')
    try:
        _tag_check(result)
        return result
    except BaseException:
        _KERNEL.CloseHandle(result)
        raise


def ensure_windows_inbound_subfolder(root: Path, parts: tuple[str, ...], *, check_path) -> Path:
    """Never traverse reparse points, including pre-existing intermediate dirs."""
    handle = _open_root(root)
    opened = [handle]
    created = []
    success = False
    try:
        parent = root
        for component in parts:
            folded = unicodedata.normalize('NFC', component).casefold()
            entries = os.listdir(parent)
            aliases = [name for name in entries if unicodedata.normalize('NFC', name).casefold() == folded]
            if aliases and aliases != [component]:
                raise FileExistsError('subfolder_name_collision')
            child = _open_existing_child(handle, component) if aliases else _make_child(handle, component)
            if not aliases:
                created.append(child)
            opened.append(child)
            target = parent / component
            check_path(target, write=True)
            if _real_name(child) != os.path.normcase(os.path.normpath(str(target))):
                _win_error('child_changed')
            parent, handle = target, child
        success = True
        return parent
    finally:
        if not success:
            for child in reversed(created):
                _remove_created_empty_directory(child)
        for item in reversed(opened):
            _KERNEL.CloseHandle(item)
