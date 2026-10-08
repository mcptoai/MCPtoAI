"""Testler için sahte kimlik deposu backend'leri (gerçek Keychain'e asla dokunmaz)."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from mcptoai_linux.secret_store import CredentialBackendError


class MemoryBackend:
    """Süreç içi sahte backend; hata enjeksiyonu destekler.

    set() macOS keyring'i taklit eder: önce siler, sonra ekler (atomik değil).
    """

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.fail_get: set[str] = set()
        self.fail_set: set[str] = set()            # silmeden önce hata
        self.fail_add_after_delete: set[str] = set()  # sil + ekle arasında hata
        self.corrupt_after_set: set[str] = set()   # yazılanı bozarak sakla
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def get(self, account: str) -> str | None:
        with self._lock:
            self.calls.append(("get", account))
            if account in self.fail_get:
                raise CredentialBackendError("Credential store read failed (Injected)")
            return self.data.get(account)

    def set(self, account: str, value: str) -> None:
        with self._lock:
            self.calls.append(("set", account))
            if account in self.fail_set:
                raise CredentialBackendError("Credential store write failed (Injected)")
            self.data.pop(account, None)
            if account in self.fail_add_after_delete:
                raise CredentialBackendError("Credential store write failed (Injected after delete)")
            self.data[account] = value[:-1] if account in self.corrupt_after_set else value

    def delete(self, account: str) -> bool:
        with self._lock:
            self.calls.append(("delete", account))
            return self.data.pop(account, None) is not None


class FileBackend:
    """Süreçler arası paylaşılan sahte backend (her hesap bir dosya).

    set(): sil + atomik oluştur (os.replace). macOS'taki "sil + ekle"
    boşluğunu birebir taklit eder; kısmen yazılmış içerik görünmez.
    """

    def __init__(self, root: str | os.PathLike) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, account: str) -> Path:
        return self.root / (account.replace("/", "_") + ".item")

    def get(self, account: str) -> str | None:
        try:
            return self._p(account).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def set(self, account: str, value: str) -> None:
        p = self._p(account)
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        tmp = p.with_suffix(f".tmp{os.getpid()}.{threading.get_ident()}")
        tmp.write_text(value, encoding="utf-8")
        os.replace(tmp, p)

    def delete(self, account: str) -> bool:
        try:
            self._p(account).unlink()
            return True
        except FileNotFoundError:
            return False


def block_real_keyring(target) -> None:
    """Gerçek keyring çağrılarını hata fırlatacak şekilde değiştirir.

    `target`: monkeypatch nesnesi ya da (setattr(obj, name, value)) sağlayan herhangi bir şey.
    """
    import keyring
    from mcptoai_linux import secret_store

    def _blocked(*_a, **_k):
        raise AssertionError("Tests must never touch the real OS credential store")

    for name in ("get_password", "set_password", "delete_password"):
        target.setattr(keyring, name, _blocked)
    for name in ("get", "set", "delete"):
        target.setattr(secret_store.KeyringBackend, name, _blocked)
