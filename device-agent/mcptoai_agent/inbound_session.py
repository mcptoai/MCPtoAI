"""Device-side stop-and-wait upload state; transport and UI remain separate.

The caller must obtain a trusted local #84 grant before calling approve().
No bytes are persisted by the relay; this object owns a local temporary file.
"""
import base64
import hashlib
import time
from .inbound_transfer import InboundStaging, approval_request, approval_preview, validate_destination, available_destination


class InboundSession:
    def __init__(self, *, transfer_id, name, size, sha256, workspace, allowed_roots, ttl=120, rename_if_exists=False):
        self.transfer_id = transfer_id
        self.target = available_destination(name, workspace, allowed_roots, rename_if_exists=rename_if_exists)
        self.staging = InboundStaging(expected_size=size, sha256=sha256, target=self.target)
        self.request = approval_request(target=self.target, size=size, sha256=sha256)
        self.preview = approval_preview(self.request)
        self.next_index = 0
        self.approved = False
        self.deadline = time.monotonic() + ttl
        self.closed = False

    def _check(self):
        if self.closed or time.monotonic() > self.deadline:
            self.close()
            raise PermissionError('Transfer closed or expired')

    def approve(self, *, trusted_native_approval):
        self._check()
        if trusted_native_approval is not True:
            self.close()
            raise PermissionError('Device approval denied')
        self.approved = True

    def chunk(self, *, index, data):
        self._check()
        if not self.approved or type(index) is not int or index != self.next_index or index >= 80:
            raise PermissionError('Chunk not authorized or out of order')
        decoded = base64.b64decode(data, validate=True)
        self.staging.append(decoded)
        self.next_index += 1
        return index

    def finish(self, *, consume_grant, revalidate_destination):
        self._check()
        if not self.approved:
            raise PermissionError('No device approval')
        try:
            if revalidate_destination() != self.target:
                raise PermissionError('Destination changed')
            return self.staging.commit(approved=True, revalidate=consume_grant)
        finally:
            self.close()

    async def record_activity(self, phase: str, *, activity=None):
        """Write metadata-only events through the existing device ActivityStore.

        The caller owns the lifecycle and must record requested, approval_pending,
        approved/denied, started and the final outcome. Never record file bytes.
        """
        if activity is None:
            from mcptoai_core.activity_recorder import ActivityRecorder
            if not hasattr(self, '_activity'):
                self._activity = ActivityRecorder(session_id=self.transfer_id).begin(
                    'file.receive', {'path': str(self.target), 'name': self.target.name,
                                     'size': self.staging.expected_size})
            activity = self._activity
        return await activity.mark(phase)

    def close(self):
        self.closed = True
        self.staging.close()
