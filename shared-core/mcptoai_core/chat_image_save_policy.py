"""Proposal-only contract for chat-image-to-device saves (no file access grant).

An image in a model prompt is not implicitly authorized as a local file.
Only a trusted interactive Desktop approval may authorize a specific staged
image, destination, and bounded one-time tool access in a future executor.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from uuid import UUID

MAX_IMAGE_BYTES = 10 * 1024 * 1024
_ALLOWED_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
_ALLOWED_EXTS = {'image/jpeg': {'.jpg', '.jpeg'}, 'image/png': {'.png'}, 'image/webp': {'.webp'}}
_DIGEST = re.compile(r'^[a-f0-9]{64}$')
_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_. ()-]{0,119}$')


@dataclass(frozen=True)
class ChatImageSaveProposal:
    transfer_id: str
    session_id: str
    turn_id: str
    owner_device_id: str
    name: str
    media_type: str
    size: int
    sha256: str
    destination_workspace: str
    trusted_local_confirmation: bool = False


def _uuid(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('image_save_invalid_id')
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError('image_save_invalid_id') from exc
    if str(parsed) != value:
        raise ValueError('image_save_invalid_id')
    return value


def inspect_save_proposal(proposal: ChatImageSaveProposal, *,
                          active_session_id: str, active_turn_id: str,
                          paired_device_id: str, allowed_roots: set[str]) -> dict[str, str]:
    """Read-only preflight. Never returns authorization to write or run tools."""
    if not isinstance(proposal, ChatImageSaveProposal):
        raise ValueError('image_save_invalid_proposal')
    transfer = _uuid(proposal.transfer_id)
    if (_uuid(proposal.session_id) != _uuid(active_session_id)
            or _uuid(proposal.turn_id) != _uuid(active_turn_id)):
        raise PermissionError('image_save_stale_or_cross_turn')
    if (not isinstance(proposal.owner_device_id, str)
            or not isinstance(paired_device_id, str)
            or not paired_device_id or proposal.owner_device_id != paired_device_id):
        raise PermissionError('image_save_wrong_device')
    if not proposal.trusted_local_confirmation:
        raise PermissionError('image_save_local_approval_required')
    if (not isinstance(proposal.destination_workspace, str)
            or proposal.destination_workspace not in allowed_roots):
        raise PermissionError('image_save_workspace_not_approved')
    if (not isinstance(proposal.media_type, str)
            or proposal.media_type not in _ALLOWED_TYPES
            or not isinstance(proposal.name, str)
            or not _NAME.fullmatch(proposal.name)
            or proposal.name.lower().endswith(tuple(_ALLOWED_EXTS[proposal.media_type])) is False
            or type(proposal.size) is not int or not 0 < proposal.size <= MAX_IMAGE_BYTES
            or not isinstance(proposal.sha256, str) or not _DIGEST.fullmatch(proposal.sha256)):
        raise ValueError('image_save_invalid_metadata')
    fields = {'device': paired_device_id, 'session': active_session_id,
              'turn': active_turn_id, 'transfer': transfer, 'name': proposal.name,
              'media_type': proposal.media_type, 'size': proposal.size,
              'sha256': proposal.sha256, 'workspace': proposal.destination_workspace}
    digest = sha256(json.dumps(fields, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'proposal_sha256': digest, 'authority': 'local_preflight_only',
            'executable': 'false', 'tool_access': 'false'}
