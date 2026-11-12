"""Cihazda tutulan, yalnızca meta veri içeren SQLite aktivite geçmişi (sunucuya gitmez)."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

from .activity_events import ActivityEvent, validate_stored_payload
from .paths import config_dir

logger = logging.getLogger(__name__)

MAX_EVENTS = 10_000
RETENTION_SECONDS = 30 * 24 * 60 * 60
# Kota veritabanı dosyası ile -wal / -shm / -journal dosyalarının TOPLAMI için geçerlidir.
MAX_BYTES = 100 * 1024 * 1024
# Kota aşıldığında en eski kayıtlar bu orana inilene kadar silinir (her yazmada küçültme yapılmasın).
PRUNE_TARGET_RATIO = 0.8
BUSY_TIMEOUT_MS = 10_000
_SIDE_SUFFIXES = ('-wal', '-shm', '-journal')
# Bozulma belirtisi sayılan SQLite hata metinleri; "database is locked" gibi geçici hatalar burada YOK.
_CORRUPTION_MARKERS = ('malformed', 'not a database', 'disk image', 'file is encrypted', 'quick_check', 'incompatible schema')
_COLUMNS = ('sequence', 'activity_id', 'session_id', 'timestamp_utc', 'recorded_at', 'payload')
# Sürümlü dosya adı: önceki prototiplerin activity.sqlite3 dosyasına (ve içindeki tablolara) dokunulmaz.
DEFAULT_FILENAME = 'activity-v1.sqlite3'


def _is_corruption(exc: BaseException) -> bool:
    if not isinstance(exc, sqlite3.DatabaseError):
        return False
    text = str(exc).lower()
    return any(marker in text for marker in _CORRUPTION_MARKERS)


class ActivityStore:
    """Doğrulanmış aktivite meta verisini saklar; araç argümanı ya da çıktısı asla saklanmaz.

    Birden çok süreç (connect, Desktop sohbeti, IPC) aynı dosyaya yazabilir: WAL + busy_timeout.
    """

    def __init__(self, path: Path | None = None, *, max_bytes: int = MAX_BYTES, busy_timeout_ms: int = BUSY_TIMEOUT_MS):
        self.path = Path(path) if path is not None else config_dir() / DEFAULT_FILENAME
        self.max_bytes = int(max_bytes)
        self._busy_timeout_ms = int(busy_timeout_ms)
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != 'nt' and self.path.parent == config_dir():
            os.chmod(self.path.parent, 0o700)
        if self.path.is_symlink():
            raise ValueError('Activity store path must not be a symlink')
        self._db = self._open_or_recover()

    # --- Dosyalar ---------------------------------------------------------------
    def _files(self) -> list[Path]:
        return [self.path] + [Path(str(self.path) + suffix) for suffix in _SIDE_SUFFIXES]

    def disk_usage(self) -> int:
        """Veritabanı ve yan dosyalarının (WAL/SHM/journal) toplam boyutu."""
        total = 0
        for file in self._files():
            try:
                total += file.stat().st_size
            except FileNotFoundError:
                pass
        return total

    def _harden_permissions(self) -> None:
        if os.name == 'nt':
            return
        for file in self._files():
            try:
                os.chmod(file, 0o600)
            except FileNotFoundError:
                pass

    def _remove_files(self) -> None:
        for file in self._files():
            try:
                file.unlink()
            except FileNotFoundError:
                pass

    # --- Açılış ve kurtarma -----------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), check_same_thread=False, timeout=self._busy_timeout_ms / 1000)
        try:
            db.execute(f'PRAGMA busy_timeout={self._busy_timeout_ms}')
            db.execute('PRAGMA journal_mode=WAL')
            # Silinen içerik boş sayfalarda kalmasın.
            db.execute('PRAGMA secure_delete=ON')
            row = db.execute('PRAGMA quick_check').fetchone()
            if not row or row[0] != 'ok':
                raise sqlite3.DatabaseError('quick_check failed')
            db.execute('''CREATE TABLE IF NOT EXISTS activity (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                timestamp_utc TEXT NOT NULL,
                recorded_at REAL NOT NULL,
                payload TEXT NOT NULL
            )''')
            columns = tuple(row[1] for row in db.execute('PRAGMA table_info(activity)'))
            if columns != _COLUMNS:
                # Şema farklıysa yazmalar sessizce başarısız olurdu; dosya yeniden oluşturulur.
                raise sqlite3.DatabaseError('incompatible schema')
            db.execute('CREATE INDEX IF NOT EXISTS activity_session_seq ON activity(session_id, sequence)')
            db.commit()
        except BaseException:
            db.close()
            raise
        self._harden_permissions()
        return db

    def _open_or_recover(self) -> sqlite3.Connection:
        try:
            return self._connect()
        except sqlite3.DatabaseError as exc:
            # Kilitli ya da geçici olarak açılamayan bir veritabanı ASLA silinmez.
            if not _is_corruption(exc):
                raise
            logger.warning('Activity history is corrupted (%s); starting a new history', exc)
            self._remove_files()
            return self._connect()

    # --- Yazma ------------------------------------------------------------------
    def append(self, event: ActivityEvent) -> int:
        if not isinstance(event, ActivityEvent):
            raise TypeError('ActivityStore accepts only ActivityEvent')
        # Saklanmadan önce kanonik biçim yeniden doğrulanır.
        payload = validate_stored_payload(event.payload()).payload()
        encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        with self._lock:
            with self._db:
                cur = self._db.execute(
                    'INSERT INTO activity(activity_id,session_id,timestamp_utc,recorded_at,payload) VALUES(?,?,?,?,?)',
                    (event.activity_id, event.session_id, event.timestamp_utc, time.time(), encoded))
                self._prune_locked()
            if self.disk_usage() > self.max_bytes:
                self._enforce_quota_locked()
            return int(cur.lastrowid)

    def _prune_locked(self) -> None:
        self._db.execute('DELETE FROM activity WHERE recorded_at < ?', (time.time() - RETENTION_SECONDS,))
        self._db.execute('DELETE FROM activity WHERE sequence <= (SELECT COALESCE(MAX(sequence)-?,0) FROM activity)', (MAX_EVENTS,))

    def _compact_locked(self) -> None:
        """Silinen veriyi dosyadan da kaldırır: VACUUM, ardından WAL'i boşaltır."""
        try:
            self._db.execute('VACUUM')
            self._db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        except sqlite3.OperationalError as exc:
            # Başka bir süreç okuyorsa bir sonraki fırsatta yeniden denenir.
            logger.info('Activity history compaction deferred: %s', exc)
        self._harden_permissions()

    def _enforce_quota_locked(self) -> None:
        try:
            self._db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        except sqlite3.OperationalError as exc:
            logger.info('Activity history checkpoint deferred: %s', exc)
        if self.disk_usage() <= self.max_bytes:
            return
        target = int(self.max_bytes * PRUNE_TARGET_RATIO)
        for _ in range(20):
            count = self._db.execute('SELECT COUNT(*) FROM activity').fetchone()[0]
            if count == 0:
                break
            with self._db:
                self._db.execute(
                    'DELETE FROM activity WHERE sequence IN (SELECT sequence FROM activity ORDER BY sequence ASC LIMIT ?)',
                    (max(1, count // 5),))
            self._compact_locked()
            if self.disk_usage() <= target:
                break

    # --- Okuma ve silme ---------------------------------------------------------
    def list_events(self, *, session_id: str | None = None, limit: int = 100, before: int | None = None) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('Invalid limit')
        if before is not None and (type(before) is not int or before <= 0):
            raise ValueError('Invalid cursor')
        clauses, args = [], []
        if session_id is not None:
            if not isinstance(session_id, str) or not session_id:
                raise ValueError('Invalid session')
            clauses.append('session_id = ?'); args.append(session_id)
        if before is not None:
            clauses.append('sequence < ?'); args.append(before)
        query = 'SELECT sequence,payload FROM activity'
        if clauses:
            query += ' WHERE ' + ' AND '.join(clauses)
        query += ' ORDER BY sequence DESC LIMIT ?'; args.append(limit)
        with self._lock:
            rows = self._db.execute(query, args).fetchall()
        return [{'sequence': seq, **validate_stored_payload(json.loads(raw)).payload()} for seq, raw in rows]

    def clear(self, *, session_id: str | None = None) -> int:
        """Geçmişi (ya da tek bir sohbetin geçmişini) siler ve dosyayı küçültür."""
        if session_id is not None and (not isinstance(session_id, str) or not session_id):
            raise ValueError('Invalid session')
        with self._lock:
            with self._db:
                if session_id is None:
                    cur = self._db.execute('DELETE FROM activity')
                else:
                    cur = self._db.execute('DELETE FROM activity WHERE session_id = ?', (session_id,))
            self._compact_locked()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            try:
                self._db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            except sqlite3.Error:
                pass
            self._db.close()
