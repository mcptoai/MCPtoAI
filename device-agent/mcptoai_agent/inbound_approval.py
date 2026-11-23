"""Trusted device-local inbound approval; no web/renderer/model approval channel.

Linux interactive CLI opt-in only. Desktop Electron-main adapter is required
before advertising upload capability in desktop builds.
"""
from __future__ import annotations
import os
import sys
from dataclasses import dataclass
import hmac
from mcptoai_core.action_contract import preview_digest
from mcptoai_core.action_contract import DeviceApprovalGate


def paired_identity():
    from .auth import _auth_bundle, device_removed_state
    bundle = _auth_bundle()
    owner, device = bundle.get('owner_sub'), bundle.get('device_id')
    if not isinstance(owner, str) or not owner.strip() or not isinstance(device, str) or not device.strip():
        raise PermissionError('Unpaired device identity')
    if device_removed_state().get('device_id') == device:
        raise PermissionError('Device pairing revoked')
    return owner, device


def local_cli_prompt(request, preview):
    """Explicit Linux-only TTY approval. Never use stdin or remote relay text."""
    if sys.platform != 'linux' or os.environ.get('MCPTOAI_INBOUND_UPLOAD_CLI') != '1':
        return False
    try:
        with open('/dev/tty', 'r+', encoding='utf-8') as tty:
            tty.write('\nMCPtoAI incoming file (local device approval)\n' + preview + '\nType APPROVE to accept once: ')
            tty.flush()
            return tty.readline().strip() == 'APPROVE'
    except (OSError, EOFError):
        return False


def local_headless_prompt(request, preview, *, transfer_id):
    """Metadata-only local queue; a Docker exec CLI makes the decision."""
    from . import upload_decisions
    args = request.arguments
    upload_decisions.create(transfer_id,args['name'],int(args['size']),
                            str(__import__('pathlib').Path(args['path']).parent),args['sha256'])
    try:
        return upload_decisions.wait_for_decision(transfer_id)
    finally:
        upload_decisions.cancel(transfer_id)


def desktop_socket_path():
    from pathlib import Path
    return Path.home() / '.config' / 'mcptoai' / 'inbound-upload-approval.sock'


def desktop_approval_available():
    import stat
    if sys.platform != 'darwin':
        return False
    path = desktop_socket_path()
    try:
        parent, endpoint = path.parent.stat(), path.lstat()
        return (parent.st_uid == os.getuid() and endpoint.st_uid == os.getuid()
                and (parent.st_mode & 0o077) == 0 and (endpoint.st_mode & 0o077) == 0
                and stat.S_ISSOCK(endpoint.st_mode))
    except OSError:
        return False


def local_desktop_prompt(request, preview, *, transfer_id, chat_scope=None, subfolder_to_create=None):
    """Ask Electron main through local owner-only AF_UNIX socket, fail closed."""
    import json
    import socket
    if not desktop_approval_available():
        return False
    path = desktop_socket_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(65)
            client.connect(str(path))
            args = request.arguments
            payload = {'transfer_id': transfer_id, 'name': args['name'],
                       'size': int(args['size']), 'workspace': str(__import__('pathlib').Path(args['path']).parent),
                       'sha256': args['sha256']}
            if subfolder_to_create is not None:
                payload['create_subfolder'] = subfolder_to_create
                payload['workspace'] = str(__import__('pathlib').Path(args['path']).parents[len(subfolder_to_create.split('/'))])
            if chat_scope is not None:
                payload.update(purpose='chat_image_save',session_id=chat_scope[0],turn_id=chat_scope[1])
            client.sendall((json.dumps(payload, separators=(',', ':')) + '\n').encode())
            response = b''
            while b'\n' not in response and len(response) < 1024:
                block = client.recv(1024)
                if not block:
                    break
                response += block
            return json.loads(response.split(b'\n')[0]).get('approved') is True
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


@dataclass(frozen=True)
class BoundInboundAuthorization:
    """One-use native consent, consumed up front and scoped to one live transfer.

    The relay session's own 600-second deadline controls subsequent byte receipt;
    the generic 60-second ActionGrant must not expire mid-transfer.
    """
    user_id: str
    device_id: str
    transfer_id: str
    action_digest: str
    preview_digest: str


class InboundApproval:
    def __init__(self, gate=None):
        self.gate = gate or DeviceApprovalGate()

    def request(self, session, *, prompt=local_cli_prompt):
        owner, device = paired_identity()
        if prompt(session.request, session.preview) is not True:
            raise PermissionError('Trusted local approval denied')
        # Re-read pairing after the potentially long-lived local dialog.
        if paired_identity() != (owner, device):
            raise PermissionError('Paired identity changed during approval')
        grant = self.gate.record_local_approval(user_id=owner, device_id=device,
            turn_id=session.transfer_id, request=session.request, preview=session.preview, ttl_seconds=60)
        session.approve(trusted_native_approval=True)
        return grant

    def consume(self, session, grant):
        try:
            owner, device = paired_identity()
        except PermissionError:
            return False
        return self.gate.consume(nonce=grant.nonce,user_id=owner,device_id=device,
            turn_id=session.transfer_id,request=session.request,preview=session.preview)

    def bind_for_transfer(self, session, grant):
        """Consume the native grant *before* telling web that upload may start."""
        if not self.consume(session, grant):
            return None
        try:
            owner, device = paired_identity()
        except PermissionError:
            return None
        return BoundInboundAuthorization(owner, device, session.transfer_id,
            session.request.digest(), preview_digest(session.request, session.preview))

    def verify_bound_transfer(self, session, bound):
        """A completed transfer may write only with its original scoped consent."""
        if not isinstance(bound, BoundInboundAuthorization):
            return False
        try:
            owner, device = paired_identity()
            return (session.approved and not session.closed and
                hmac.compare_digest(owner, bound.user_id) and
                hmac.compare_digest(device, bound.device_id) and
                hmac.compare_digest(session.transfer_id, bound.transfer_id) and
                hmac.compare_digest(session.request.digest(), bound.action_digest) and
                hmac.compare_digest(preview_digest(session.request, session.preview), bound.preview_digest))
        except (PermissionError, ValueError, TypeError):
            return False
