"""Device-side stop-and-wait upload state; transport and UI remain separate.

The caller must obtain a trusted local #84 grant before calling approve().
No bytes are persisted by the relay; this object owns a local temporary file.
"""
import base64
import hashlib
import time
from .inbound_transfer import InboundStaging, approval_request, approval_preview, validate_destination, available_destination, SAFE_NAME, ALLOWED_SUFFIXES


class InboundSession:
    def __init__(self, *, transfer_id, name, size, sha256, workspace, allowed_roots, ttl=600, rename_if_exists=False, subfolder=None):
        self.transfer_id = transfer_id
        from .sensitive_paths import check_path
        self._check_subfolder_path = check_path
        self.subfolder = subfolder or None
        self.workspace_root = workspace
        self.allowed_roots = allowed_roots
        self.rename_if_exists = rename_if_exists
        self.create_folder = False
        if self.subfolder:
            from mcptoai_core.safe_subfolders import plan_inbound_subfolder
            from pathlib import Path
            directory, self.create_folder = plan_inbound_subfolder(workspace,self.subfolder,allowed_roots,check_path=check_path)
            if not SAFE_NAME.fullmatch(name) or Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
                raise ValueError('invalid_upload_filename')
            if self.create_folder:
                self.target = directory / name
            else:
                self.target = available_destination(name,str(directory),allowed_roots,rename_if_exists=rename_if_exists)
        else:
            self.target = available_destination(name, workspace, allowed_roots, rename_if_exists=rename_if_exists)
        self.staging = InboundStaging(expected_size=size, sha256=sha256, target=self.target)
        self.request = approval_request(target=self.target, size=size, sha256=sha256)
        self.preview = approval_preview(self.request)
        if self.create_folder:
            self.preview += f'\nOluşturulacak klasör: {self.subfolder}'
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
        if not self.approved or type(index) is not int or index != self.next_index or index >= 400:
            raise PermissionError('Chunk not authorized or out of order')
        decoded = base64.b64decode(data, validate=True)
        self.staging.append(decoded)
        self.next_index += 1
        return index

    def finish(self, *, consume_grant, revalidate_destination, atomic_chat_image=False):
        self._check()
        if not self.approved:
            raise PermissionError('No device approval')
        try:
            if self.subfolder:
                from mcptoai_core.safe_subfolders import plan_inbound_subfolder, ensure_inbound_subfolder
                directory, needs_creation = plan_inbound_subfolder(self.workspace_root,self.subfolder,self.allowed_roots,check_path=self._check_subfolder_path)
                # Folder existence is part of the local approval intent.
                # Never create a folder that was existing at offer, and never
                # silently reuse a folder that appeared after a create request.
                if directory != self.target.parent or needs_creation != self.create_folder:
                    raise PermissionError('subfolder_path_changed')
                # Ensure content and checksum are valid BEFORE the one-use
                # grant is consumed and before any directory is created.
                if self.staging.count != self.staging.expected_size or self.staging.hasher.hexdigest() != self.staging.sha256:
                    raise ValueError('File size or checksum mismatch')
                self.staging._validate_content()
                if not consume_grant():
                    from mcptoai_core.safe_subfolders import _tag_inbound_error
                    raise _tag_inbound_error(PermissionError('inbound_approval_scope_invalid'),
                        'verify_bound_approval','approval',self.subfolder or '')
                ensure_inbound_subfolder(self.workspace_root,self.subfolder,self.allowed_roots,check_path=self._check_subfolder_path)
                try:
                    validated = available_destination(self.target.name,str(directory),self.allowed_roots,rename_if_exists=False)
                except OSError as exc:
                    from mcptoai_core.safe_subfolders import _tag_inbound_error
                    raise _tag_inbound_error(exc,'validate_post_mkdir','target',self.target.name)
                if self.target != validated or revalidate_destination() != self.target:
                    from mcptoai_core.safe_subfolders import _tag_inbound_error
                    raise _tag_inbound_error(PermissionError('subfolder_destination_changed'),
                        'validate_post_mkdir','target',self.target.name)
                # Trusted approval already consumed for the exact request+preview.
                return self.staging.commit(approved=True,revalidate=lambda:True)
            if revalidate_destination() != self.target:
                raise PermissionError('Destination changed')
            if atomic_chat_image:
                return self.staging.commit_atomic_chat_image(approved=True, revalidate=consume_grant)
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
