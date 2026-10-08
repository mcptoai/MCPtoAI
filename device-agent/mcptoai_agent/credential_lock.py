"""Süreçler arası kimlik bilgisi kilidi.

Vault üzerindeki tüm değişiklikler ve tüm token yenilemeleri bu tek kilidin
altında yapılır. Aynı anda çalışan `connect`, `desktop-chat-jsonl` ve kısa
ömürlü CLI süreçleri (set-key vb.) birbirinin yazdığını ezemez.

Katmanlar:
- Süreçler arası: kilit dosyası üzerinde işletim sistemi kilidi
  (POSIX: fcntl.flock, Windows: msvcrt.locking).
- Süreç içi: thread'e bağlı olmayan bir kapı (threading.Lock). Böylece kilit
  bir asyncio görevinde alınıp aynı görevde, farklı bir noktada bırakılabilir.
- Yeniden girilebilirlik: kilidi tutan sahip (asyncio görevi ya da thread)
  kilidi tekrar alabilir; derinlik sayılır. Tek kilit kullanıldığı için
  "auth kilidi ↔ vault kilidi" sıralama kilitlenmesi (deadlock) oluşamaz.

Olay döngüsü kuralı: async kod kilidi `async_credential_lock()` ile almalıdır.
Olay döngüsü thread'inde senkron alma denemesi, kilit aynı süreçte başka bir
görevdeyse beklemez, hemen CredentialLockBusy fırlatır (beklemek döngüyü ve
dolayısıyla kilit sahibini kilitlerdi).
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time
from pathlib import Path
from typing import Callable

DEFAULT_TIMEOUT = 30.0  # Auth0 HTTP zaman aşımı (20 sn) + pay
_POLL_SECONDS = 0.05


class CredentialLockError(RuntimeError):
    """Kilit kullanımıyla ilgili genel hata."""


class CredentialLockTimeout(CredentialLockError):
    """Kilit süre içinde alınamadı."""


class CredentialLockBusy(CredentialLockError):
    """Olay döngüsü thread'inde senkron alma denemesi; kilit başka görevde."""


def _current_owner() -> object:
    """Kilit sahibini belirler: çalışan asyncio görevi, yoksa thread kimliği."""
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return task if task is not None else ("thread", threading.get_ident())


def _in_event_loop_thread() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


if os.name == "nt":  # pragma: no cover - Windows'ta çalışır
    import msvcrt

    def _try_os_lock(fd: int) -> bool:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _os_unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _try_os_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False

    def _os_unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


class CredentialLock:
    """Yeniden girilebilir, süreçler arası kimlik bilgisi kilidi."""

    def __init__(self, path_fn: Callable[[], Path], timeout: float = DEFAULT_TIMEOUT) -> None:
        self._path_fn = path_fn
        self.timeout = timeout
        self._gate = threading.Lock()      # süreç içi kapı (thread'e bağlı değil)
        self._state = threading.Lock()     # sahip/derinlik alanlarını korur
        self._owner: object | None = None
        self._depth = 0
        self._fd: int | None = None

    # -- yardımcılar -------------------------------------------------------
    def held_by_current(self) -> bool:
        me = _current_owner()
        with self._state:
            return self._owner is not None and self._owner == me

    def _try_reenter(self, me: object) -> bool:
        with self._state:
            if self._owner is not None and self._owner == me:
                self._depth += 1
                return True
        return False

    def _open_lock_file(self) -> int:
        path = Path(self._path_fn())
        path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(path.parent, 0o700)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(path, flags, 0o600)
        # msvcrt.locking() locks a byte range from the current file position.
        # Ensure the lock file has at least one byte on Windows so the same
        # region exists for every process and cross-process exclusion is real.
        if os.name == "nt":
            try:
                if os.fstat(fd).st_size < 1:
                    os.lseek(fd, 0, os.SEEK_SET)
                    os.write(fd, b"\0")
                    os.fsync(fd)
            finally:
                os.lseek(fd, 0, os.SEEK_SET)
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
        return fd

    def _try_os_acquire(self) -> int | None:
        fd = self._open_lock_file()
        if _try_os_lock(fd):
            return fd
        os.close(fd)
        return None

    def _set_owner(self, me: object, fd: int) -> None:
        with self._state:
            self._owner = me
            self._depth = 1
            self._fd = fd

    # -- senkron API ---------------------------------------------------------
    def acquire(self, timeout: float | None = None) -> None:
        me = _current_owner()
        if self._try_reenter(me):
            return
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        if _in_event_loop_thread():
            if not self._gate.acquire(blocking=False):
                raise CredentialLockBusy(
                    "Credential lock is held by another task in this process; use the async API"
                )
        elif not self._gate.acquire(timeout=max(0.0, deadline - time.monotonic())):
            raise CredentialLockTimeout("Timed out waiting for the credential lock")
        try:
            while True:
                fd = self._try_os_acquire()
                if fd is not None:
                    break
                if time.monotonic() >= deadline:
                    raise CredentialLockTimeout("Timed out waiting for the credential lock")
                time.sleep(_POLL_SECONDS)
        except BaseException:
            self._gate.release()
            raise
        self._set_owner(me, fd)

    # -- asenkron API --------------------------------------------------------
    async def aacquire(self, timeout: float | None = None) -> None:
        me = _current_owner()
        if self._try_reenter(me):
            return
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while not self._gate.acquire(blocking=False):
            if time.monotonic() >= deadline:
                raise CredentialLockTimeout("Timed out waiting for the credential lock")
            await asyncio.sleep(_POLL_SECONDS)
        try:
            while True:
                fd = self._try_os_acquire()
                if fd is not None:
                    break
                if time.monotonic() >= deadline:
                    raise CredentialLockTimeout("Timed out waiting for the credential lock")
                await asyncio.sleep(_POLL_SECONDS)
        except BaseException:  # iptal dahil: kapıyı mutlaka bırak
            self._gate.release()
            raise
        self._set_owner(me, fd)

    def release(self) -> None:
        me = _current_owner()
        with self._state:
            if self._owner is None or self._owner != me:
                raise CredentialLockError("Credential lock released by a non-owner")
            self._depth -= 1
            if self._depth:
                return
            fd = self._fd
            self._owner = None
            self._fd = None
        try:
            if fd is not None:
                _os_unlock(fd)
        finally:
            if fd is not None:
                os.close(fd)
            self._gate.release()

    @contextlib.contextmanager
    def hold(self, timeout: float | None = None):
        self.acquire(timeout)
        try:
            yield
        finally:
            self.release()

    @contextlib.asynccontextmanager
    async def ahold(self, timeout: float | None = None):
        await self.aacquire(timeout)
        try:
            yield
        finally:
            self.release()


def _default_lock_path() -> Path:
    from .paths import config_dir
    return config_dir() / "vault.lock"


# Süreç genelinde tek kilit; yol her alımda hesaplanır (testler HOME'u değiştirebilir).
LOCK = CredentialLock(_default_lock_path)


def credential_lock(timeout: float | None = None):
    """Senkron bağlam yöneticisi: `with credential_lock(): ...`"""
    return LOCK.hold(timeout)


def async_credential_lock(timeout: float | None = None):
    """Asenkron bağlam yöneticisi: `async with async_credential_lock(): ...`"""
    return LOCK.ahold(timeout)
