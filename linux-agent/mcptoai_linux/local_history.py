"""Device-only conversation history for MCPtoAI Linux.

The database lives under the user's MCPtoAI config directory and is never
uploaded by this module. The relay only exposes it to the authenticated web
session for this paired device.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .paths import config_dir

MAX_CHAT_CONTENT_BYTES = 256 * 1024
MAX_TOOL_DATA_BYTES = 256 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_path() -> Path:
    return config_dir() / "history.sqlite3"


class LocalHistoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or default_path())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self):
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _init(self) -> None:
        with self._connect() as con:
            con.executescript(
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
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    tool_name TEXT NOT NULL DEFAULT '',
                    tool_data TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_history_messages_session
                    ON messages(session_id, id);
                """
            )
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    @staticmethod
    def _session(row, message_count=0) -> dict:
        return {
            "id": row["id"], "title": row["title"], "device_id": None,
            "provider": row["provider"], "model": row["model"],
            "is_pinned": bool(row["is_pinned"]), "is_archived": bool(row["is_archived"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "message_count": int(message_count),
        }

    def list_chats(self, archived: bool = False) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                """SELECT c.*, COUNT(m.id) AS message_count
                   FROM chats c LEFT JOIN messages m ON m.session_id=c.id
                   WHERE c.is_archived=? GROUP BY c.id
                   ORDER BY c.is_pinned DESC, c.updated_at DESC LIMIT 100""",
                (1 if archived else 0,),
            ).fetchall()
        return [self._session(r, r["message_count"]) for r in rows]

    def create_chat(self, title="New chat", provider="", model="") -> dict:
        sid = str(uuid.uuid4()); now = _now()
        with self._connect() as con:
            con.execute(
                "INSERT INTO chats(id,title,provider,model,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (sid, str(title or "New chat")[:160], str(provider or "")[:80], str(model or "")[:120], now, now),
            )
            row = con.execute("SELECT * FROM chats WHERE id=?", (sid,)).fetchone()
        return self._session(row, 0)

    def get_chat(self, session_id: str) -> dict | None:
        with self._connect() as con:
            row = con.execute("SELECT * FROM chats WHERE id=?", (str(session_id),)).fetchone()
            if not row:
                return None
            messages = con.execute("SELECT * FROM messages WHERE session_id=? ORDER BY id", (str(session_id),)).fetchall()
        data = self._session(row, len(messages))
        data["messages"] = [{
            "id": m["id"], "role": m["role"], "content": m["content"], "model": m["model"],
            "tool_name": m["tool_name"], "tool_data": json.loads(m["tool_data"]) if m["tool_data"] else None,
            "created_at": m["created_at"],
        } for m in messages]
        return data

    def add_message(self, session_id: str, *, role: str, content="", model="", tool_name="", tool_data=None) -> dict:
        if role not in {"user", "assistant", "tool", "system"}:
            raise ValueError("Invalid role")
        content = str(content or "")
        if len(content.encode("utf-8")) > MAX_CHAT_CONTENT_BYTES:
            raise ValueError("Message content is too large")
        encoded_tool = None
        if tool_data is not None:
            encoded_tool = json.dumps(tool_data, separators=(",", ":"), ensure_ascii=False)
            if len(encoded_tool.encode("utf-8")) > MAX_TOOL_DATA_BYTES:
                raise ValueError("Tool data is too large")
        now = _now()
        with self._connect() as con:
            row = con.execute("SELECT title FROM chats WHERE id=?", (str(session_id),)).fetchone()
            if not row:
                raise KeyError("Chat not found")
            cur = con.execute(
                """INSERT INTO messages(session_id,role,content,model,tool_name,tool_data,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (str(session_id), role, content, str(model or "")[:120], str(tool_name or "")[:160], encoded_tool, now),
            )
            title = row["title"]
            if role == "user" and title == "New chat":
                clean = " ".join(content.split())
                if clean:
                    title = clean[:80]
            con.execute("UPDATE chats SET title=?, updated_at=? WHERE id=?", (title, now, str(session_id)))
            mid = cur.lastrowid
        return {"id": mid, "role": role, "content": content, "model": str(model or "")[:120],
                "tool_name": str(tool_name or "")[:160], "tool_data": tool_data, "created_at": now,
                "session_title": title}

    def update_chat(self, session_id: str, patch: dict) -> dict:
        allowed = {}
        if "title" in patch: allowed["title"] = str(patch.get("title") or "New chat")[:160]
        if "provider" in patch: allowed["provider"] = str(patch.get("provider") or "")[:80]
        if "model" in patch: allowed["model"] = str(patch.get("model") or "")[:120]
        if "is_pinned" in patch: allowed["is_pinned"] = 1 if patch.get("is_pinned") else 0
        if "is_archived" in patch: allowed["is_archived"] = 1 if patch.get("is_archived") else 0
        now = _now(); allowed["updated_at"] = now
        with self._connect() as con:
            exists = con.execute("SELECT 1 FROM chats WHERE id=?", (str(session_id),)).fetchone()
            if not exists: raise KeyError("Chat not found")
            fields = ",".join(f"{k}=?" for k in allowed)
            con.execute(f"UPDATE chats SET {fields} WHERE id=?", (*allowed.values(), str(session_id)))
        return self.get_chat(str(session_id))

    def delete_chat(self, session_id: str) -> None:
        with self._connect() as con:
            cur = con.execute("DELETE FROM chats WHERE id=?", (str(session_id),))
            if not cur.rowcount: raise KeyError("Chat not found")

    def handle(self, req: dict) -> dict:
        try:
            action = req.get("action")
            if action == "cloud_chats_list":
                data = self.list_chats(bool(req.get("archived")))
            elif action == "cloud_chat_get":
                data = self.get_chat(str(req.get("session_id") or ""))
                if data is None: raise KeyError("Chat not found")
            elif action == "cloud_chat_create":
                data = self.create_chat(req.get("title"), req.get("provider"), req.get("model"))
            elif action == "cloud_chat_add_message":
                data = self.add_message(str(req.get("session_id") or ""), role=str(req.get("role") or ""),
                                        content=req.get("content"), model=req.get("model"),
                                        tool_name=req.get("tool_name"), tool_data=req.get("tool_data"))
            elif action == "cloud_chat_update":
                data = self.update_chat(str(req.get("session_id") or ""), req)
            elif action == "cloud_chat_delete":
                self.delete_chat(str(req.get("session_id") or "")); data = None
            else:
                return {"ok": False, "error": "unsupported_action"}
            return {"ok": True, "data": data}
        except (KeyError, ValueError, TypeError, sqlite3.Error) as exc:
            return {"ok": False, "error": str(exc).strip("'") or type(exc).__name__}
