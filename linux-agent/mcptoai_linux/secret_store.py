"""Tek, sürümlü kimlik bilgisi kasası (vault).

Tüm sırlar işletim sisteminin kimlik deposunda TEK kayıtta tutulur:
    service = com.bkty.mcptoai, account = vault
    içerik  = {"v": 1, "secrets": {"<ad>": "<değer>", ...}}

Temel kurallar:
- Süreç içi önbellek yoktur; her okuma doğrudan anahtarlıktan yapılır.
  (Kasa imzalı agent tarafından oluşturulduğundan ACL agent'a güvenir;
  tekrar okumak onay penceresi açmaz.)
- Her değişiklik süreçler arası kilit altında yapılır:
  kilidi al → anahtarlıktan taze oku → doğrula → yalnız istenen anahtarı
  değiştir → kasanın tamamını yaz → yeniden oku → doğrula → kilidi bırak.
  Yazmanın kaynağı asla bellekteki eski bir kopya değildir.
- Bozuk, okunamayan, yapısı geçersiz ya da sürümü desteklenmeyen kasa ASLA
  boş kasa sayılmaz ve ASLA otomatik ezilmez; açık bir hata fırlatılır.
  Hata mesajları sır değerlerini içermez.
- macOS keyring yazımı "sil + ekle" şeklindedir (atomik değil). Bu yüzden
  iki aşamalı yazılır: önce `vault.next`, doğrula; sonra `vault`, doğrula;
  en son `vault.next` silinir. `vault` yoksa ama geçerli `vault.next` varsa
  (iki adım arasında çökme) okuma `vault.next` üzerinden yapılır ve bir
  sonraki değişiklikte `vault` onarılır.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Callable, Iterable, Protocol

from .paths import config_dir
from .credential_lock import LOCK, async_credential_lock, credential_lock

logger = logging.getLogger(__name__)

SERVICE = "com.bkty.mcptoai"
VAULT_ACCOUNT = "vault"
STAGING_ACCOUNT = "vault.next"
SCHEMA_VERSION = 1
MAX_VAULT_BYTES = 512 * 1024
MAX_NAME_CHARS = 256
MAX_VALUE_BYTES = 128 * 1024


# --- Hatalar ---------------------------------------------------------------
class CredentialStoreError(RuntimeError):
    """Kimlik deposu genel hatası (mesajlar sır içermez)."""


class CredentialBackendError(CredentialStoreError):
    """Anahtarlığa erişilemedi (reddedildi, kilitli, bilinmeyen hata)."""


class VaultCorruptError(CredentialStoreError):
    """Kasa içeriği çözülemedi ya da yapısı geçersiz."""


class VaultUnsupportedVersionError(VaultCorruptError):
    """Kasa şema sürümü bu agent tarafından desteklenmiyor."""


class VaultVerifyError(CredentialStoreError):
    """Yazma sonrası yeniden okuma beklenen içeriği vermedi."""


# --- Backend ---------------------------------------------------------------
class Backend(Protocol):
    def get(self, account: str) -> str | None: ...
    def set(self, account: str, value: str) -> None: ...
    def delete(self, account: str) -> bool: ...


class KeyringBackend:
    name = "secret-service"
    """Gerçek işletim sistemi anahtarlığı (macOS Keychain / Windows Credential Manager)."""

    def __init__(self, service: str = SERVICE) -> None:
        self.service = service

    def get(self, account: str) -> str | None:
        import keyring
        import keyring.errors
        try:
            # Bulunamayan kayıt için None döner; ret/kilitli için hata fırlatır.
            return keyring.get_password(self.service, account)
        except keyring.errors.KeyringError as exc:
            raise CredentialBackendError(f"Credential store read failed ({type(exc).__name__})") from None

    def set(self, account: str, value: str) -> None:
        import keyring
        import keyring.errors
        try:
            keyring.set_password(self.service, account, value)
        except keyring.errors.KeyringError as exc:
            raise CredentialBackendError(f"Credential store write failed ({type(exc).__name__})") from None

    def delete(self, account: str) -> bool:
        import keyring
        import keyring.errors
        try:
            keyring.delete_password(self.service, account)
            return True
        except keyring.errors.PasswordDeleteError:
            # "Bulunamadı" ile gerçek hatayı ayırmak için tekrar kontrol et.
            if self.get(account) is None:
                return False
            raise CredentialBackendError("Credential store delete failed") from None
        except keyring.errors.KeyringError as exc:
            raise CredentialBackendError(f"Credential store delete failed ({type(exc).__name__})") from None


class FileBackend:
    """Ekransız Linux kasası: hesap başına 0600 izinli dosya, dizin 0700.

    Sunucuda Secret Service ve kullanıcı modunda systemd-creds (systemd 256+) yoksa
    gerçekçi seçenek budur; gh, aws ve ssh'nin sunucudaki modeliyle aynıdır. Aynı diskte
    duran bir anahtarla şifrelemek gerçek bir koruma sağlamaz. İzinler gevşekse ya da
    dosya başka bir kullanıcıya aitse kasa okunmaz.
    """

    name = "file"

    def __init__(self, root: Path | None = None):
        self._root = root

    @property
    def root(self) -> Path:
        return self._root or (config_dir() / "vault")

    def _path(self, account: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", account or "") or account in {".", ".."}:
            raise CredentialBackendError("Invalid vault account name")
        return self.root / account

    def get(self, account: str) -> str | None:
        path = self._path(account)
        try:
            st = path.stat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise CredentialBackendError(f"Vault file is not readable: {exc.strerror}") from None
        if st.st_mode & 0o077 or st.st_uid != os.getuid():
            raise CredentialBackendError(f"Vault file permissions are unsafe: {path} (must be 0600 and owned by you)")
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CredentialBackendError(f"Vault file is not readable: {exc.strerror}") from None

    def set(self, account: str, value: str) -> None:
        root = self.root
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        path = self._path(account)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(value)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
            dir_fd = os.open(root, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise

    def delete(self, account: str) -> bool:
        try:
            self._path(account).unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise CredentialBackendError(f"Vault file could not be deleted: {exc.strerror}") from None


def _select_backend() -> Backend:
    """Kasa arka ucu. Varsayılan dosya; masaüstü Linux'ta MCPTOAI_VAULT_BACKEND=secret-service
    ile Secret Service seçilebilir. Seçim kendiliğinden değişmez: SSH ve masaüstü oturumunda
    farklı arka uçlar seçilip sırlar "kaybolmuş" görünmesin."""
    choice = (os.getenv("MCPTOAI_VAULT_BACKEND") or "file").strip().lower()
    if choice == "secret-service":
        return KeyringBackend()
    if choice != "file":
        raise CredentialBackendError(f"Unknown vault backend: {choice}")
    return FileBackend()


_backend: Backend = _select_backend()


def backend_name() -> str:
    return getattr(_backend, "name", "secret-service")


def set_backend(backend: Backend) -> Backend:
    """Backend'i değiştirir (yalnızca testler için). Eski backend'i döndürür."""
    global _backend
    previous, _backend = _backend, backend
    return previous


def get_backend() -> Backend:
    return _backend


# --- Doğrulama / serileştirme ---------------------------------------------
def _check_name(name: str) -> str:
    if not isinstance(name, str) or not name or len(name) > MAX_NAME_CHARS or any(ord(c) < 32 for c in name):
        raise ValueError("Invalid credential name")
    return name


def _check_value(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Credential value must be a string")
    if len(value.encode("utf-8")) > MAX_VALUE_BYTES:
        raise ValueError("Credential value is too large")
    return value


def _parse(raw: str, source: str) -> dict[str, str]:
    try:
        doc = json.loads(raw)
    except (ValueError, TypeError):
        # `from None`: JSONDecodeError.doc kasanın tamamını taşır; traceback'e sızmasın.
        raise VaultCorruptError(f"{source}: not valid JSON") from None
    if not isinstance(doc, dict) or set(doc) != {"v", "secrets"}:
        raise VaultCorruptError(f"{source}: invalid structure")
    version = doc["v"]
    if not isinstance(version, int) or isinstance(version, bool):
        raise VaultCorruptError(f"{source}: invalid schema version field")
    if version != SCHEMA_VERSION:
        raise VaultUnsupportedVersionError(f"{source}: unsupported schema version {version}")
    secrets = doc["secrets"]
    if not isinstance(secrets, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in secrets.items()):
        raise VaultCorruptError(f"{source}: invalid secrets map")
    return dict(secrets)


def _serialize(secrets: dict[str, str]) -> str:
    doc = json.dumps({"v": SCHEMA_VERSION, "secrets": secrets}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(doc.encode("utf-8")) > MAX_VAULT_BYTES:
        raise CredentialStoreError("Credential vault is too large")
    return doc


# --- Okuma -------------------------------------------------------------------
def _read_state() -> tuple[str, dict[str, str] | None]:
    """Kasayı taze okur.

    Dönüş: ("ok", sırlar) | ("staged", sırlar) | ("absent", None)
    "absent" yalnızca hem vault hem vault.next anahtarlıkta YOKSA döner.
    Okuma hatası ya da bozuk içerik her zaman hata fırlatır.
    """
    raw = _backend.get(VAULT_ACCOUNT)
    if raw is not None:
        return "ok", _parse(raw, "vault")
    staged = _backend.get(STAGING_ACCOUNT)
    if staged is None:
        return "absent", None
    return "staged", _parse(staged, "vault.next")


def read_vault() -> dict[str, str] | None:
    """Kasa yoksa None, varsa sırların kopyasını döndürür."""
    return _read_state()[1]


def vault_status() -> str:
    """Sır göstermeden durum: absent | ok | recovering | corrupt | unsupported | error"""
    try:
        state, _ = _read_state()
    except VaultUnsupportedVersionError:
        return "unsupported"
    except VaultCorruptError:
        return "corrupt"
    except CredentialStoreError:
        return "error"
    return {"ok": "ok", "staged": "recovering", "absent": "absent"}[state]


def get_secret(name: str) -> str | None:
    _check_name(name)
    secrets = read_vault()
    return None if secrets is None else secrets.get(name)


def get_secrets(names: Iterable[str]) -> dict[str, str]:
    """Birden çok sırrı tek okumayla döndürür (olmayanlar atlanır)."""
    names = [_check_name(n) for n in names]
    secrets = read_vault() or {}
    return {n: secrets[n] for n in names if n in secrets}


# --- Yazma -------------------------------------------------------------------
def _commit(secrets: dict[str, str]) -> None:
    """İki aşamalı yazım; her aşama yeniden okunarak birebir doğrulanır."""
    doc = _serialize(secrets)
    _backend.set(STAGING_ACCOUNT, doc)
    if _backend.get(STAGING_ACCOUNT) != doc:
        raise VaultVerifyError("Staged credential vault verification failed")
    _backend.set(VAULT_ACCOUNT, doc)
    if _backend.get(VAULT_ACCOUNT) != doc:
        raise VaultVerifyError("Credential vault verification failed")
    try:
        _backend.delete(STAGING_ACCOUNT)
    except CredentialStoreError:
        # Zararsız: vault yetkili kayıttır, artık vault.next bir sonraki yazımda yenilenir.
        logger.warning("Could not remove staged credential vault entry")


def _mutate_locked(fn: Callable[[dict[str, str]], None]) -> dict[str, str]:
    if not LOCK.held_by_current():
        raise RuntimeError("credential lock must be held")
    state, current = _read_state()          # taze okuma; bozuksa burada durur
    base = dict(current or {})
    updated = dict(base)
    fn(updated)
    for k, v in updated.items():
        _check_name(k)
        _check_value(v)
    if updated == base and state == "ok":
        return updated                        # değişiklik yok
    if state == "absent" and not updated:
        return updated                        # boş kasa oluşturmaya gerek yok
    _commit(updated)
    state_after, after = _read_state()
    if state_after != "ok" or after != updated:
        raise VaultVerifyError("Credential vault mutation verification failed")
    return updated


def mutate(fn: Callable[[dict[str, str]], None]) -> dict[str, str]:
    """Senkron değişiklik (CLI ve thread'ler için)."""
    with credential_lock():
        return _mutate_locked(fn)


async def amutate(fn: Callable[[dict[str, str]], None]) -> dict[str, str]:
    """Asenkron değişiklik (olay döngüsündeki kod için)."""
    async with async_credential_lock():
        return _mutate_locked(fn)


def set_secret(name: str, value: str) -> None:
    _check_name(name); _check_value(value)
    mutate(lambda s: s.__setitem__(name, value))


async def aset_secret(name: str, value: str) -> None:
    _check_name(name); _check_value(value)
    await amutate(lambda s: s.__setitem__(name, value))


def set_secrets(values: dict[str, str]) -> None:
    clean = {_check_name(k): _check_value(v) for k, v in values.items()}
    if clean:
        mutate(lambda s: s.update(clean))


def delete_secret(name: str) -> None:
    _check_name(name)
    mutate(lambda s: s.pop(name, None))


async def adelete_secret(name: str) -> None:
    _check_name(name)
    await amutate(lambda s: s.pop(name, None))


def delete_secrets(names: Iterable[str]) -> None:
    names = [_check_name(n) for n in names]
    if names:
        mutate(lambda s: [s.pop(n, None) for n in names])


def destroy_vault() -> None:
    """Kasayı içeriğine bakmadan siler (bozuk kasa için tek çıkış yolu).

    Yalnızca açık kullanıcı eylemiyle (clear-local-data) çağrılmalıdır.
    """
    with credential_lock():
        for account in (STAGING_ACCOUNT, VAULT_ACCOUNT):
            _backend.delete(account)
        if _backend.get(VAULT_ACCOUNT) is not None or _backend.get(STAGING_ACCOUNT) is not None:
            raise VaultVerifyError("Credential vault deletion verification failed")


# --- Ad yardımcıları ----------------------------------------------------------
def api_key_name(provider: str) -> str:
    return f"api_key:{provider}"


def device_id_name() -> str:
    # Uyumluluk: cihaz kimliği artık device_auth paketinin içindedir.
    return "device_id"


def provider_key_fingerprint(provider: str) -> str:
    """Oturum önbellek anahtarı için kısa parmak izi; anahtar değişince oturum yenilenir."""
    key = get_secret(api_key_name(provider))
    if not key:
        return "none"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
