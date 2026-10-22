"""Send a user-approved local artifact without using the 512 KiB relay message channel.

The backend stores the object privately, validates its SHA-256 and enforces ownership,
expiration, per-user quota and authenticated downloads. A user approval for the
send_artifact tool is mandatory even if a session granted other read/write tools.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

import httpx

from .auth import _auth_bundle, get_access_token
from .config import Settings

CHUNK_SIZE = 4 * 1024 * 1024
MAX_ARTIFACT_SIZE = 1024 * 1024 * 1024


async def upload_artifact(cfg: Settings, file_path: Path, *, session_id: str | None = None) -> dict:
    root = file_path.resolve(strict=True)
    if not any(root == base or root.is_relative_to(base) for base in cfg.allowed_roots):
        raise PermissionError("Artifact is outside the allowed workspace")
    if not root.is_file() or not 0 < root.stat().st_size <= MAX_ARTIFACT_SIZE:
        raise ValueError("Artifact must be a regular file between 1 byte and 1 GiB")
    if root.name.startswith(".") or len(root.name) > 180 or any(ord(c) < 32 for c in root.name):
        raise ValueError("Unsupported filename")
    # The server validates the extension and determines MIME, never trusts a
    # client-provided Content-Type when deciding how to serve an artifact.
    sha = hashlib.sha256()
    with root.open("rb") as source:
        while True:
            chunk = await asyncio.to_thread(source.read, CHUNK_SIZE)
            if not chunk:
                break
            sha.update(chunk)
    token = await get_access_token(cfg)
    device_id = str(_auth_bundle().get("device_id") or "")
    if not device_id:
        raise RuntimeError("Device must be paired before sending an artifact")
    headers = {"Authorization": f"Bearer {token}"}
    endpoint = cfg.server_url.rstrip("/") + "/api/artifacts/"
    timeout = httpx.Timeout(120.0, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        init = await client.post(endpoint, headers=headers, json={
            "device_id": device_id, "filename": root.name,
            "size": root.stat().st_size, "sha256": sha.hexdigest(),
            **({"session_id": session_id} if session_id else {}),
        })
        init.raise_for_status()
        metadata = init.json()
        artifact_id = metadata["id"]
        if metadata.get("chunk_size") != CHUNK_SIZE:
            raise RuntimeError("Unsupported artifact chunk size")
        with root.open("rb") as source:
            index = 0
            while True:
                chunk = await asyncio.to_thread(source.read, CHUNK_SIZE)
                if not chunk:
                    break
                uri = endpoint + artifact_id + f"/chunk/{index}/"
                # Refresh an expiring Auth0 access token on long video uploads.
                if index and index % 16 == 0:
                    headers["Authorization"] = f"Bearer {await get_access_token(cfg)}"
                for attempt in range(3):
                    try:
                        sent = await client.post(
                            uri, headers={**headers, "Content-Type": "application/octet-stream"},
                            content=chunk,
                        )
                        sent.raise_for_status()
                        break
                    except (httpx.TimeoutException, httpx.TransportError):
                        if attempt == 2:
                            raise
                        await asyncio.sleep(attempt + 1)
                index += 1
        headers["Authorization"] = f"Bearer {await get_access_token(cfg)}"
        finished = await client.post(endpoint + artifact_id + "/complete/", headers=headers)
        finished.raise_for_status()
        artifact = finished.json()
        if not artifact.get("ready") or artifact.get("sha256") != sha.hexdigest():
            raise RuntimeError("Artifact verification failed")
        # No signed URL or API token in the tool result; the web proxy requires
        # the user's normal authenticated ChatGPT/MC PtoAI session cookie.
        return {key: artifact[key] for key in ("id", "filename", "mime", "size", "sha256", "expires_at")}
