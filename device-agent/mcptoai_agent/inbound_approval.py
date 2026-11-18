"""Trusted device-local inbound approval; no web/renderer/model approval channel.

Linux interactive CLI opt-in only. Desktop Electron-main adapter is required
before advertising upload capability in desktop builds.
"""
from __future__ import annotations
import os
import sys
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


def local_desktop_prompt(request, preview, *, transfer_id):
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
