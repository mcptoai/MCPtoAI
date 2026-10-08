"""Conversation history providers.

History storage is intentionally separate from device execution, relay routing,
and the official application update path.  The Desktop IPC still uses the
legacy ``cloud_chat_*`` action names for backwards compatibility; this module
maps those requests to the selected history provider.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .auth import get_access_token
from .config import Settings
from .paths import config_dir


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chat_id(value: Any) -> str:
    value = str(value or "")
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid chat id") from exc


class HistoryProvider(ABC):
    """Storage contract for conversation history."""

    @abstractmethod
    async def list_chats(self, *, archived: bool = False) -> list[dict]: ...

    @abstractmethod
    async def get_chat(self, chat_id: str) -> dict: ...

    @abstractmethod
    async def create_chat(self, *, title: str, provider: str, model: str) -> dict: ...

    @abstractmethod
    async def add_message(
        self,
        chat_id: str,
        *,
        role: str,
        content: str,
        model: str = "",
        tool_name: str = "",
        tool_data: Any = None,
    ) -> dict: ...

    @abstractmethod
    async def update_chat(self, chat_id: str, **changes: Any) -> dict: ...

    @abstractmethod
    async def delete_chat(self, chat_id: str) -> None: ...


class MCPtoAIHistoryProvider(HistoryProvider):
    """Current managed history service hosted by MCPtoAI."""

    def __init__(self, cfg: Settings):
        self.cfg = cfg

    async def _request(self, method: str, path: str = "", *, body: dict | None = None) -> Any:
        token = await get_access_token(self.cfg)
        url = self.cfg.server_url.rstrip("/") + "/api/chats/" + path.lstrip("/")
        async with httpx.AsyncClient(timeout=15) as http:
            response = await http.request(
                method,
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=body if method in {"POST", "PATCH"} else None,
            )
            response.raise_for_status()
            return response.json() if response.content else None

    async def list_chats(self, *, archived: bool = False) -> list[dict]:
        data = await self._request("GET", "?archived=1" if archived else "")
        return data if isinstance(data, list) else []

    async def get_chat(self, chat_id: str) -> dict:
        return await self._request("GET", f"{_chat_id(chat_id)}/")

    async def create_chat(self, *, title: str, provider: str, model: str) -> dict:
        return await self._request("POST", body={
            "title": str(title or "New chat")[:160],
            "provider": str(provider or "")[:80],
            "model": str(model or "")[:120],
        })

    async def add_message(
        self,
        chat_id: str,
        *,
        role: str,
        content: str,
        model: str = "",
        tool_name: str = "",
        tool_data: Any = None,
    ) -> dict:
        return await self._request("POST", f"{_chat_id(chat_id)}/messages/", body={
            "role": str(role or ""),
            "content": str(content or ""),
            "model": str(model or "")[:120],
            "tool_name": str(tool_name or "")[:160],
            "tool_data": tool_data,
        })

    async def update_chat(self, chat_id: str, **changes: Any) -> dict:
        body = {k: changes[k] for k in ("title", "is_pinned", "is_archived") if k in changes}
        return await self._request("PATCH", f"{_chat_id(chat_id)}/", body=body)

    async def delete_chat(self, chat_id: str) -> None:
        await self._request("DELETE", f"{_chat_id(chat_id)}/")


class LocalHistoryProvider(HistoryProvider):
    """SQLite-backed history stored only on this device."""

    def __init__(self, database_path: Path | None = None):
        self.database_path = Path(database_path or (config_dir() / "history.sqlite3"))
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()
        try:
            os.chmod(self.database_path, 0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS chats (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    is_pinned INTEGER NOT NULL DEFAULT 0,
                    is_archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    tool_name TEXT NOT NULL DEFAULT '',
                    tool_data TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_chat_created
                    ON messages(chat_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_chats_archive_updated
                    ON chats(is_archived, updated_at);
                """
            )

    @staticmethod
    def _chat_dict(row: sqlite3.Row, *, message_count: int | None = None) -> dict:
        item = {
            "id": row["id"],
            "title": row["title"],
            "provider": row["provider"],
            "model": row["model"],
            "is_pinned": bool(row["is_pinned"]),
            "is_archived": bool(row["is_archived"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if message_count is not None:
            item["message_count"] = message_count
        return item

    async def list_chats(self, *, archived: bool = False) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*, COUNT(m.id) AS message_count
                FROM chats c LEFT JOIN messages m ON m.chat_id=c.id
                WHERE c.is_archived=?
                GROUP BY c.id
                ORDER BY c.is_pinned DESC, c.updated_at DESC
                """,
                (1 if archived else 0,),
            ).fetchall()
        return [self._chat_dict(row, message_count=int(row["message_count"])) for row in rows]

    async def get_chat(self, chat_id: str) -> dict:
        cid = _chat_id(chat_id)
        with self._connect() as conn:
            chat = conn.execute("SELECT * FROM chats WHERE id=?", (cid,)).fetchone()
            if chat is None:
                raise KeyError("chat_not_found")
            messages = conn.execute(
                "SELECT * FROM messages WHERE chat_id=? ORDER BY created_at ASC, rowid ASC", (cid,)
            ).fetchall()
        data = self._chat_dict(chat)
        data["messages"] = [
            {
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "model": row["model"],
                "tool_name": row["tool_name"],
                "tool_data": json.loads(row["tool_data"]) if row["tool_data"] else None,
                "created_at": row["created_at"],
            }
            for row in messages
        ]
        return data

    async def create_chat(self, *, title: str, provider: str, model: str) -> dict:
        cid, now = str(uuid.uuid4()), _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO chats(id,title,provider,model,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (cid, str(title or "New chat")[:160], str(provider or "")[:80], str(model or "")[:120], now, now),
            )
            row = conn.execute("SELECT * FROM chats WHERE id=?", (cid,)).fetchone()
        return self._chat_dict(row)

    async def add_message(
        self,
        chat_id: str,
        *,
        role: str,
        content: str,
        model: str = "",
        tool_name: str = "",
        tool_data: Any = None,
    ) -> dict:
        cid, mid, now = _chat_id(chat_id), str(uuid.uuid4()), _now()
        encoded = json.dumps(tool_data, ensure_ascii=False, separators=(",", ":")) if tool_data is not None else None
        with self._connect() as conn:
            if conn.execute("SELECT 1 FROM chats WHERE id=?", (cid,)).fetchone() is None:
                raise KeyError("chat_not_found")
            conn.execute(
                """INSERT INTO messages(id,chat_id,role,content,model,tool_name,tool_data,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (mid, cid, str(role or ""), str(content or ""), str(model or "")[:120], str(tool_name or "")[:160], encoded, now),
            )
            conn.execute("UPDATE chats SET updated_at=? WHERE id=?", (now, cid))
        return {
            "id": mid,
            "chat_id": cid,
            "role": str(role or ""),
            "content": str(content or ""),
            "model": str(model or "")[:120],
            "tool_name": str(tool_name or "")[:160],
            "tool_data": tool_data,
            "created_at": now,
        }

    async def update_chat(self, chat_id: str, **changes: Any) -> dict:
        cid = _chat_id(chat_id)
        assignments: list[str] = []
        values: list[Any] = []
        if "title" in changes:
            assignments.append("title=?"); values.append(str(changes["title"] or "New chat")[:160])
        if "is_pinned" in changes:
            assignments.append("is_pinned=?"); values.append(1 if changes["is_pinned"] is True else 0)
        if "is_archived" in changes:
            assignments.append("is_archived=?"); values.append(1 if changes["is_archived"] is True else 0)
        assignments.append("updated_at=?"); values.append(_now())
        values.append(cid)
        with self._connect() as conn:
            if conn.execute("SELECT 1 FROM chats WHERE id=?", (cid,)).fetchone() is None:
                raise KeyError("chat_not_found")
            conn.execute(f"UPDATE chats SET {', '.join(assignments)} WHERE id=?", values)
            row = conn.execute("SELECT * FROM chats WHERE id=?", (cid,)).fetchone()
        return self._chat_dict(row)

    async def delete_chat(self, chat_id: str) -> None:
        cid = _chat_id(chat_id)
        with self._connect() as conn:
            conn.execute("DELETE FROM chats WHERE id=?", (cid,))


def selected_history_provider_name(cfg: Settings) -> str:
    # Desktop can change history storage while the Windows cloud IPC helper is
    # already running. Read the small settings file on each request instead of
    # relying only on the Settings snapshot created when that helper started.
    live_settings: dict[str, Any] = {}
    try:
        raw = json.loads((config_dir() / "settings.json").read_text())
        if isinstance(raw, dict):
            live_settings = raw
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        pass
    value = str(
        os.getenv("MCPTOAI_HISTORY_PROVIDER")
        or live_settings.get("history_provider")
        or cfg.user_settings.get("history_provider")
        or "mcptoai"
    ).strip().lower()
    return value if value in {"mcptoai", "local"} else "mcptoai"


def history_provider(cfg: Settings) -> HistoryProvider:
    name = selected_history_provider_name(cfg)
    if name == "local":
        return LocalHistoryProvider()
    return MCPtoAIHistoryProvider(cfg)


async def handle_history_request(cfg: Settings, req: dict) -> dict:
    action = req.get("action")
    if action not in {
        "cloud_chats_list", "cloud_chat_get", "cloud_chat_create",
        "cloud_chat_add_message", "cloud_chat_delete", "cloud_chat_update",
    }:
        return {"ok": False, "error": "unsupported_action"}
    provider = history_provider(cfg)
    try:
        if action == "cloud_chats_list":
            data = await provider.list_chats(archived=req.get("archived") is True)
        elif action == "cloud_chat_get":
            data = await provider.get_chat(str(req.get("session_id") or ""))
        elif action == "cloud_chat_create":
            data = await provider.create_chat(
                title=str(req.get("title") or "New chat"),
                provider=str(req.get("provider") or ""),
                model=str(req.get("model") or ""),
            )
        elif action == "cloud_chat_add_message":
            data = await provider.add_message(
                str(req.get("session_id") or ""),
                role=str(req.get("role") or ""),
                content=str(req.get("content") or ""),
                model=str(req.get("model") or ""),
                tool_name=str(req.get("tool_name") or ""),
                tool_data=req.get("tool_data"),
            )
        elif action == "cloud_chat_update":
            data = await provider.update_chat(
                str(req.get("session_id") or ""),
                **{k: req[k] for k in ("title", "is_pinned", "is_archived") if k in req},
            )
        else:
            await provider.delete_chat(str(req.get("session_id") or ""))
            data = None
        return {"ok": True, "data": data}
    except KeyError as exc:
        return {"ok": False, "error": str(exc.args[0] if exc.args else "not_found")}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "error": str(exc)}


# Backwards-compatible name used by current Desktop IPC and relay code.
handle_cloud_chat_request = handle_history_request
