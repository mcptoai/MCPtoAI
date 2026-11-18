"""Fail-closed, bounded inbound file transfer primitives (no server-side storage).

The transport must NOT call commit until a trusted Electron-main approval grant
has been consumed for the exact authenticated principal/device/target/digest.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import tempfile
import sys
import time
import ctypes
import zipfile
import unicodedata

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_CHUNK_BYTES = 128 * 1024
ALLOWED_SUFFIXES = frozenset({'.txt', '.md', '.csv', '.json', '.pdf', '.png', '.jpg', '.jpeg', '.webp', '.docx', '.xlsx'})
SAFE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_. ()-]{0,119}$')


class DestinationExistsError(FileExistsError):
    """Distinguishes target collision from staging and parent failures."""
    def __init__(self, kind: str, stage: str):
        self.kind, self.stage = kind, stage
        super().__init__(f"Destination collision ({kind}, {stage})")


def validate_destination(name: str, workspace: str, allowed_roots: list[Path]) -> Path:
    if not isinstance(name, str) or not SAFE_NAME.fullmatch(name) or name in {'.', '..'}:
        raise ValueError('Invalid filename')
    if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError('Unsupported file type')
    root = Path(workspace).resolve(strict=True)
    if not root.is_dir() or not any(root == Path(base).resolve(strict=False) or root.is_relative_to(Path(base).resolve(strict=False)) for base in allowed_roots):
        raise PermissionError('Destination is outside allowed workspace roots')
    target = root / name
    if target.is_symlink():
        raise DestinationExistsError('symlink', 'validation')
    normalized = unicodedata.normalize('NFC', name).casefold()
    for entry in root.iterdir():
        if entry.name != name and unicodedata.normalize('NFC', entry.name).casefold() == normalized:
            raise DestinationExistsError('target_name_equivalent', 'validation')
    if target.exists():
        raise DestinationExistsError('target', 'validation')
    return target


def available_destination(name: str, workspace: str, allowed_roots: list[Path], *, rename_if_exists: bool = False) -> Path:
    """Choose a collision-free basename on device; exclusive create remains mandatory."""
    if not rename_if_exists:
        return validate_destination(name, workspace, allowed_roots)
    from pathlib import PurePath
    suffix = PurePath(name).suffix
    stem = name[:-len(suffix)] if suffix else name
    for index in range(0, 1000):
        candidate = name if index == 0 else f'{stem[:max(1, 120-len(suffix)-len(str(index))-3)]} ({index}){suffix}'
        try:
            return validate_destination(candidate, workspace, allowed_roots)
        except DestinationExistsError:
            continue
    raise DestinationExistsError('target', 'unique_name_exhausted')


class InboundStaging:
    """Local-only bounded temporary staging, not a server artifact."""
    def __init__(self, *, expected_size: int, sha256: str, target: Path):
        if type(expected_size) is not int or not 0 < expected_size <= MAX_FILE_BYTES:
            raise ValueError('File size exceeds limit')
        if not isinstance(sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', sha256):
            raise ValueError('Invalid checksum')
        self.expected_size = expected_size
        self.sha256 = sha256
        self.target = target
        self.count = 0
        self.hasher = hashlib.sha256()
        self.temp = tempfile.TemporaryFile()

    def append(self, chunk: bytes) -> None:
        if not isinstance(chunk, bytes) or not 0 < len(chunk) <= MAX_CHUNK_BYTES or self.count + len(chunk) > self.expected_size:
            raise ValueError('Invalid chunk size')
        self.temp.write(chunk)
        self.hasher.update(chunk)
        self.count += len(chunk)

    def _validate_content(self) -> None:
        # Uzantıya güvenme: imza, kapsayıcı ve makro bileşenlerini denetle.
        suffix = self.target.suffix.lower()
        self.temp.seek(0)
        header = self.temp.read(512)
        self.temp.seek(0)
        forbidden = (b'MZ', b'\x7fELF', b'\xfe\xed\xfa\xce', b'\xcf\xfa\xed\xfe',
                     b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'#!')
        if header.startswith(forbidden) or header.startswith(b'\x00asm'):
            raise ValueError('Executable content rejected')
        if suffix == '.pdf':
            valid = header.startswith(b'%PDF-')
        elif suffix == '.png':
            valid = header.startswith(b'\x89PNG\r\n\x1a\n')
        elif suffix in ('.jpg', '.jpeg'):
            valid = header.startswith(b'\xff\xd8\xff')
        elif suffix == '.webp':
            valid = header.startswith(b'RIFF') and header[8:12] == b'WEBP'
        elif suffix in ('.docx', '.xlsx'):
            valid = False
            if zipfile.is_zipfile(self.temp):
                with zipfile.ZipFile(self.temp) as archive:
                    names = [n.lower() for n in archive.namelist()]
                    forbidden_parts = ('vbaproject.bin', 'activex/', 'embeddings/', 'macros/', '.exe', '.dll', '.sh', '.command')
                    if any(any(part in n for part in forbidden_parts) for n in names):
                        raise ValueError('Executable or macro-enabled Office content rejected')
                    required = 'word/document.xml' if suffix == '.docx' else 'xl/workbook.xml'
                    valid = '[content_types].xml' in names and required in names
        else:
            self.temp.seek(0)
            raw = self.temp.read(MAX_FILE_BYTES + 1)
            try:
                decoded = raw.decode('utf-8-sig')
                valid = '\x00' not in decoded and not decoded.lstrip().lower().startswith(('<script', '<!doctype html', '<html', '<?php'))
            except UnicodeDecodeError:
                valid = False
        self.temp.seek(0)
        if not valid:
            raise ValueError('File content does not match an allowed safe type')

    def _mark_origin(self, fd: int) -> None:
        # Platform işaretlemesi başarısızsa dosya kullanıcıya teslim edilmez.
        if sys.platform == 'darwin':
            value = f'{int(time.time()):08x};0081;MCPtoAI;'.encode('ascii')
            libc = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
            result = libc.fsetxattr(fd, b'com.apple.quarantine', value, len(value), 0, 0)
            if result != 0:
                raise OSError(ctypes.get_errno(), 'Unable to set quarantine')
        elif sys.platform == 'win32':
            # ADS yalnızca NTFS üzerinde kullanılabilir; hata fail-closed olur.
            with open(str(self.target) + ':Zone.Identifier', 'wb') as stream:
                stream.write(b'[ZoneTransfer]\r\nZoneId=3\r\n')
                stream.flush()
                os.fsync(stream.fileno())
        # Linux: MOTW/quarantine eşdeğeri yazılmaz.

    def commit(self, *, approved: bool, revalidate) -> Path:
        """The caller supplies a trusted one-shot grant consumption callback."""
        if self.count != self.expected_size or self.hasher.hexdigest() != self.sha256:
            raise ValueError('File size or checksum mismatch')
        self._validate_content()
        if not approved or not revalidate():
            raise PermissionError('Trusted device approval required')
        # Bind writes to the already validated directory inode, not a mutable
        # pathname. Refuse symlinked parents and a swapped directory entry.
        parent = self.target.parent
        if parent.is_symlink():
            raise PermissionError('Symlinked workspace directory')
        directory = os.open(parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)
                            | getattr(os, 'O_NOFOLLOW', 0))
        created = False
        try:
            if os.stat(parent).st_ino != os.fstat(directory).st_ino or os.stat(parent).st_dev != os.fstat(directory).st_dev:
                raise PermissionError('Workspace directory changed')
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
            try:
                fd = os.open(self.target.name, flags, 0o600, dir_fd=directory)
            except FileExistsError as exc:
                raise DestinationExistsError('target', 'exclusive_create') from exc
            created = True
            try:
                self.temp.seek(0)
                with os.fdopen(fd, 'wb') as dest:
                    while part := self.temp.read(MAX_CHUNK_BYTES):
                        dest.write(part)
                    dest.flush()
                    os.fsync(dest.fileno())
                    self._mark_origin(dest.fileno())
                if os.stat(parent).st_ino != os.fstat(directory).st_ino or os.stat(parent).st_dev != os.fstat(directory).st_dev:
                    raise PermissionError('Workspace directory moved during transfer')
            except BaseException:
                if created:
                    os.unlink(self.target.name, dir_fd=directory)
                raise
        finally:
            os.close(directory)
            self.temp.close()
        return self.target

    def close(self):
        self.temp.close()


def approval_request(*, target: Path, size: int, sha256: str):
    """Exact transfer manifest as a typed #84 action; no file content included."""
    from mcptoai_core.action_contract import ActionRequest
    return ActionRequest.parse({'version': 1, 'name': 'file.receive', 'arguments': {
        'path': str(target), 'name': target.name, 'size': str(size), 'sha256': sha256}})


def approval_preview(request) -> str:
    """Locally constructed display summary; cannot originate from the model."""
    a = request.arguments
    return f"Receive {a['name']} ({a['size']} bytes) into {a['path']} [SHA-256: {a['sha256']}]"
