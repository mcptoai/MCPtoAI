"""MCP sunucusu env/header sırları kasada tutulur.

Her harita tek bir değişiklikle (tek kilit, tek yazım) saklanır ya da silinir;
okuma tek kasa okumasıyla yapılır. Boş haritalar kasaya hiç dokunmaz.
"""
from __future__ import annotations

from .secret_store import delete_secrets, get_secrets, set_secrets


def _name(server_id: str, kind: str, key: str) -> str:
    return f"mcp:{server_id}:{kind}:{key}"


def store_map(server_id: str, kind: str, values: dict) -> list[str]:
    keys: list[str] = []
    batch: dict[str, str] = {}
    for k, v in (values or {}).items():
        k = str(k).strip()
        if not k:
            continue
        batch[_name(server_id, kind, k)] = str(v)
        keys.append(k)
    if batch:
        set_secrets(batch)
    return keys


def load_map(server_id: str, kind: str, keys: list[str]) -> dict[str, str]:
    if not keys:
        return {}
    names = {_name(server_id, kind, str(k)): str(k) for k in keys}
    found = get_secrets(names)
    return {names[n]: v for n, v in found.items()}


def delete_map(server_id: str, kind: str, keys: list[str]) -> None:
    if keys:
        delete_secrets(_name(server_id, kind, str(k)) for k in keys)
